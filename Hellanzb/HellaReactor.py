"""

HellaReactor - Custom reactor (extends the default SelectReactor). Ties into the twisted
reactor system so it can catch signals, and shutdown hellanzb cleanly

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import Hellanzb, sys, time

import twisted.copyright
if twisted.copyright.version >= '2.0.0':
    from twisted.internet.selectreactor import SelectReactor
    from twisted.internet.selectreactor import _NO_FILENO
    from twisted.internet.selectreactor import _NO_FILEDESC
else:
    from twisted.internet.default import SelectReactor
    from twisted.internet.default import _NO_FILENO
    from twisted.internet.default import _NO_FILEDESC

from twisted.internet.main import installReactor
from twisted.python import log, failure
from Hellanzb.Log import *

# overwrite Log.error
from twisted.internet import error

__id__ = '$Id$'

# FIXME: this class is unnecessary, from the mailing list:
#
# | Hi,
# | 
# | There was a discussion here recently about registering
# | a callback to be called prior to shutdown (using
# | addSystemEventTrigger), and I just wanted to ask, what
# | does Twisted allow before shutdown, and what gets
# | stopped in the middle; ex. if I want to do something
# | prior to shutdown that involves communication with
# | some server, and hence a deffered chain, how do I make
# | sure that it gets a chance to happen?
#
#You can return a Deferred from your shutdown function and Twisted will
#wait until it's got a result before shutting down.

class HellaReactor(SelectReactor):
    """ Handle taking care of PostProcessors during a SIGINT """

    def sigInt(self, *args):
        """ Core's signal handler will shut the app down appropriately (including the reactor) """
        try:
            from Hellanzb.Core import signalHandler
            signalHandler(*args)
        except SystemExit:
            pass

    def sigTerm(self, *args):
        """ Exit gracefully """
        from twisted.internet import reactor
        from Hellanzb.Core import shutdown
        reactor.callLater(0, shutdown, **dict(killPostProcessors = True,
                                              message = 'Caught SIGTERM, exiting..'))

    def _doReadOrWrite(self, selectable, method, dict, faildict={
        error.ConnectionDone: failure.Failure(error.ConnectionDone()),
        error.ConnectionLost: failure.Failure(error.ConnectionLost())
        }):
        """ Handle IOErrors/out of disk space """
        try:
            why = getattr(selectable, method)()
            handfn = getattr(selectable, 'fileno', None)
            if not handfn:
                why = _NO_FILENO
            elif handfn() == -1:
                why = _NO_FILEDESC
        except IOError, ioe:
            # NOTE: Importing this in the module causes TimeoutMixin to not work. ???
            from twisted.protocols.policies import ThrottlingProtocol
            
            # Handle OutOfDiskSpace exceptions. Piggybacking this check into the reactor
            # here uses less CPU than try: excepting in NZBLeecher.dataReceived
            if selectable.protocol.__class__ is ThrottlingProtocol:
                from Hellanzb.Util import OutOfDiskSpace
                from Hellanzb.NZBLeecher.ArticleDecoder import handleIOError
                try:
                    handleIOError(ioe)
                except OutOfDiskSpace:
                    # handleIOError would have just paused the downloader for us
                    selectable.protocol.wrappedProtocol.transport.loseConnection()
                    selectable.protocol.wrappedProtocol.isLoggedIn = False
                    selectable.protocol.wrappedProtocol.deactivate()
                    return
                except:
                    pass
            why = sys.exc_info()[1]
            log.err()
        except:
            why = sys.exc_info()[1]
            log.err()
        if why:
            self.removeReader(selectable)
            self.removeWriter(selectable)
            f = faildict.get(why.__class__)
            if f:
                selectable.connectionLost(f)
            else:
                selectable.connectionLost(failure.Failure(why))

    def install(klass):
        """ Install custom reactor """
        if sys.modules.has_key('twisted.internet.reactor'):
            del sys.modules['twisted.internet.reactor']
        Hellanzb.reactor = HellaReactor()
        installReactor(Hellanzb.reactor)
    install = classmethod(install)

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
