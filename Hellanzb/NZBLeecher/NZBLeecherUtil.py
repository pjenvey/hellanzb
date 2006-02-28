"""
NZBLeecherUtil - Misc. code for NZBLeecher and its related modules

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import os, stat, sys, Hellanzb
from twisted.internet import reactor
from twisted.python import log
from twisted.protocols.policies import ThrottlingProtocol, WrappingFactory

__id__ = '$Id$'

class HellaThrottler:
    """ This is twisted.protocols.policies.ThrottlingFactory abstracted away from
    Factory. Multiple factories all share the same HellaThrottler singlteton -- thus this
    provides global bandwidth throttling for all twisted HellaThrottlingFactories """
    def __init__(self, readLimit=None, writeLimit=None):
        self.connectionCount = 0
        #self.maxConnectionCount = maxConnectionCount
        self.readLimit = readLimit # max bytes we should read per second
        self.writeLimit = writeLimit # max bytes we should write per second
        self.readThisSecond = 0
        self.writtenThisSecond = 0
        self.unthrottleReadsID = None
        self.checkReadBandwidthID = None
        self.unthrottleWritesID = None
        self.checkWriteBandwidthID = None
        
        self.factories = [] # All throttling factories

    def registerWritten(self, length):
        """Called by protocol to tell us more bytes were written."""
        self.writtenThisSecond += length

    def registerRead(self, length):
        """Called by protocol to tell us more bytes were read."""
        self.readThisSecond += length

    def checkReadBandwidth(self):
        """Checks if we've passed bandwidth limits."""
        if self.readThisSecond > self.readLimit:
            self.throttleReads()
            throttleTime = (float(self.readThisSecond) / self.readLimit) - 1.0
            self.unthrottleReadsID = reactor.callLater(throttleTime,
                                                       self.unthrottleReads)
        self.readThisSecond = 0
        self.checkReadBandwidthID = reactor.callLater(1, self.checkReadBandwidth)

    def checkWriteBandwidth(self):
        if self.writtenThisSecond > self.writeLimit:
            self.throttleWrites()
            throttleTime = (float(self.writtenThisSecond) / self.writeLimit) - 1.0
            self.unthrottleWritesID = reactor.callLater(throttleTime,
                                                        self.unthrottleWrites)
        # reset for next round    
        self.writtenThisSecond = 0
        self.checkWriteBandwidthID = reactor.callLater(1, self.checkWriteBandwidth)

    def throttleReads(self):
        """Throttle reads on all protocols."""
        for f in self.factories:
            log.msg("Throttling reads on %s" % f)
            for p in f.protocols.keys():
                p.throttleReads()

    def unthrottleReads(self):
        """Stop throttling reads on all protocols."""
        # unthrottling reads just means the protocls startReading() again. Obviously we
        # don't want to ever begin reading when the download is currently paused
        if Hellanzb.downloadPaused:
            return
        
        self.unthrottleReadsID = None
        for f in self.factories:
            log.msg("Stopped throttling reads on %s" % f)
            for p in f.protocols.keys():
                p.unthrottleReads()

    def throttleWrites(self):
        """Throttle writes on all protocols."""
        for f in self.factories:
            log.msg("Throttling writes on %s" % f)
            for p in f.protocols.keys():
                p.throttleWrites()

    def unthrottleWrites(self):
        """Stop throttling writes on all protocols."""
        self.unthrottleWritesID = None
        for f in self.factories:
            log.msg("Stopped throttling writes on %s" % f)
            for p in f.protocols.keys():
                p.unthrottleWrites()

class HellaThrottlingFactory(WrappingFactory):
    """Throttles bandwidth and number of connections via the parent HellaThrottler

    Write bandwidth will only be throttled if there is a producer
    registered.
    """

    protocol = ThrottlingProtocol

    def __init__(self, wrappedFactory, maxConnectionCount=sys.maxint):
        WrappingFactory.__init__(self, wrappedFactory)
        self.connectionCount = 0
        self.maxConnectionCount = maxConnectionCount

        self.ht = Hellanzb.ht
        self.ht.factories.append(self)

    def registerWritten(self, length):
        """Called by protocol to tell us more bytes were written."""
        self.ht.registerWritten(length)

    def registerRead(self, length):
        """Called by protocol to tell us more bytes were read."""
        self.ht.registerRead(length)

    def checkReadBandwidth(self):
        self.ht.checkReadBandwidth()

    def checkWriteBandwidth(self):
        self.ht.checkWriteBandwidth()

    def buildProtocol(self, addr):
        if self.ht.connectionCount == 0:
            if self.ht.readLimit:
                self.ht.checkReadBandwidth()
            if self.ht.writeLimit:
                self.ht.checkWriteBandwidth()

        if self.connectionCount < self.maxConnectionCount:
            self.connectionCount += 1
            self.ht.connectionCount += 1
            return WrappingFactory.buildProtocol(self, addr)
        else:
            log.msg("Max connection count reached!")
            return None

    def cancelScheduled(self, scheduled):
        if scheduled is not None and not scheduled.cancelled and \
                not scheduled.called:
            scheduled.cancel()

    def unregisterProtocol(self, p):
        WrappingFactory.unregisterProtocol(self, p)
        self.connectionCount -= 1
        self.ht.connectionCount -= 1
        
        if self.ht.connectionCount == 0:
            for name in ('unthrottleReadsID', 'checkReadBandwidthID',
                         'unthrottleWritesID', 'checkWriteBandwidthID'):
                self.cancelScheduled(getattr(self.ht, name))

def validWorkingFile(file, overwriteZeroByteFiles = False):
    """ Determine if the specified file path is a valid, existing file in the WORKING_DIR """
    # Overwrite (return True) 0 byte segment files if specified
    if Hellanzb.SYSNAME != 'Darwin':
        from Hellanzb.Util import fromUnicode
        file = fromUnicode(file)
    if os.path.exists(file) and \
            (os.stat(file)[stat.ST_SIZE] != 0 or not overwriteZeroByteFiles):
        return True
    return False

"""
Copyright (c) 2005 Philip Jenvey <pjenvey@groovie.org>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:
1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.
3. The name of the author or contributors may not be used to endorse or
   promote products derived from this software without specific prior
   written permission.

THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
SUCH DAMAGE.

$Id$
"""
