"""

NZBLeecher - Downloads article segments from an NZBQueue, then passes them off for
decoding

The NZBLeecher module (ArticleDecoder, NZBModel etc) is a rewrite of pynewsleecher by
Freddie (freddie@madcowdisease.org) utilizing the twisted framework

(c) Copyright 2005 Philip Jenvey, Ben Bangert
[See end of file]
"""
import logging, os, sys, Hellanzb
from twisted.copyright import version as twistedVersion
from twisted.internet import reactor
from twisted.internet.tcp import Connector
from Hellanzb.Core import shutdownAndExit, finishShutdown
from Hellanzb.Log import *
from Hellanzb.Logging import NZBLeecherTicker
from Hellanzb.Util import isWindows
from Hellanzb.NZBLeecher.NZBSegmentQueue import FillServerQueue, NZBSegmentQueue
from Hellanzb.NZBLeecher.NZBLeecherUtil import HellaThrottler, HellaThrottlingFactory
from Hellanzb.NZBLeecher.Protocol import NZBLeecherFactory

__id__ = '$Id$'

def initNZBLeecher():
    """ Init """
    # Note what version of twisted/python/os being used
    twistedVersionMsg = 'Using: Twisted-%s' % twistedVersion
    if twistedVersion >= '2.0.0':
        from twisted.web import __version__ as twistedWebVersion
        twistedVersionMsg += ', TwistedWeb-%s' % twistedWebVersion
    debug(twistedVersionMsg)
    pythonVersion = 'python: %s' % sys.version
    [debug(line) for line in pythonVersion.splitlines()]
    if isWindows():
        debug('platform: %s' % sys.platform)
    else:
        uname = os.uname()
        debug('os: %s-%s (%s)' % (uname[0], uname[2], uname[4]))

    # Create the one and only download queue
    if initFillServers():
        Hellanzb.queue = FillServerQueue()
    else:
        Hellanzb.queue = NZBSegmentQueue()

    # The NZBLeecherFactories
    Hellanzb.nsfs = []
    Hellanzb.totalSpeed = 0
    Hellanzb.totalArchivesDownloaded = 0
    Hellanzb.totalFilesDownloaded = 0
    Hellanzb.totalSegmentsDownloaded = 0
    Hellanzb.totalBytesDownloaded = 0

    # this class handles updating statistics via the SCROLL level (the UI)
    Hellanzb.scroller = NZBLeecherTicker()

    Hellanzb.ht = HellaThrottler(Hellanzb.MAX_RATE * 1024)
    Hellanzb.getCurrentRate = NZBLeecherFactory.getCurrentRate

    # loop to scan the queue dir during download
    Hellanzb.downloadScannerID = None

    ACODE = Hellanzb.ACODE
    Hellanzb.NZBLF_COLORS = [ACODE.F_DBLUE, ACODE.F_DMAGENTA, ACODE.F_LRED, ACODE.F_DGREEN,
                             ACODE.F_YELLOW, ACODE.F_DCYAN, ACODE.F_BWHITE]

def initFillServers():
    """ Determine if fill servers are enabled (more than 1 fillserver priorities are set in
    the config file). Flatten out the fill server priorities so that they begin at 0 and
    increment by 1 """
    fillServerPriorities = {}
    for serverId, serverDict in Hellanzb.SERVERS.iteritems():
        if serverDict.get('enabled') is False:
            continue
        fillServerPriority = serverDict.get('fillserver')
        # Consider = None as = 0
        if fillServerPriority is None:
            fillServerPriority = serverDict['fillserver'] = 0
        try:
            fillServerPriority = int(fillServerPriority)
        except ValueError, ve:
            # Let's not assume what the user wanted -- raise a FatalError so they can
            # fix the priority value
            shutdownAndExit(1,
                            message='There was a problem with the fillserver value of server: %s:\n%s' \
                             % (serverId, str(ve)))
        if fillServerPriority not in fillServerPriorities:
            fillServerPriorities.setdefault(fillServerPriority, []).append(serverDict)
        serverDict['fillserver'] = fillServerPriority

    if len(fillServerPriorities) < 2:
        debug('initFillServers: fillserver support disabled')
        return False

    # Flatten out the priorities. priority list of [1, 4, 5] will be converted to [0, 1, 2]
    priorityKeys = fillServerPriorities.keys()
    priorityKeys.sort()
    for i in range(len(priorityKeys)):
        oldPriority = priorityKeys[i]
        for serverDict in fillServerPriorities[oldPriority]:
            serverDict['fillserver'] = i

    debug('initFillServers: fillserver support enabled')
    return True
    
def setWithDefault(dict, key, default):
    """ Return value for the specified key set via the config file. Use the default when the
    value is blank or doesn't exist """
    value = dict.get(key, default)
    if value != None and value != '':
        return value
    
    return default

def connectServer(serverName, serverDict, defaultAntiIdle, defaultIdleTimeout):
    """ Establish connections to the specified server according to the server information dict
    (constructed from the config file). Returns the number of connections that were attempted
    to be made """
    defaultConnectTimeout = 30
    connectionCount = 0
    hosts = serverDict['hosts']
    connections = int(serverDict['connections'])

    for host in hosts:
        antiIdle = int(setWithDefault(serverDict, 'antiIdle', defaultAntiIdle))
        idleTimeout = int(setWithDefault(serverDict, 'idleTimeout', defaultIdleTimeout))
        skipGroupCmd = setWithDefault(serverDict, 'skipGroupCmd', False)
        fillServer = setWithDefault(serverDict, 'fillserver', 0)

        nsf = NZBLeecherFactory(serverDict['username'], serverDict['password'],
                                idleTimeout, antiIdle, host, serverName, skipGroupCmd,
                                fillServer)
        color = nsf.color
        Hellanzb.nsfs.append(nsf)

        split = host.split(':')
        host = split[0]
        if len(split) == 2:
            port = int(split[1])
        else:
            port = 119
        nsf.host, nsf.port = host, port

        preWrappedNsf = nsf
        nsf = HellaThrottlingFactory(nsf)

        for connection in range(connections):
            if serverDict.has_key('bindTo') and serverDict['bindTo'] != None and \
                    serverDict['bindTo'] != '':
                if antiIdle != 0:
                    reactor.connectTCP(host, port, nsf,
                                       bindAddress = (serverDict['bindTo'], 0))
                else:
                    connector = Connector(host, port, nsf, defaultConnectTimeout,
                                          (serverDict['bindTo'], 0), reactor=reactor)
            else:
                if antiIdle != 0:
                    reactor.connectTCP(host, port, nsf)
                else:
                    connector = Connector(host, port, nsf, defaultConnectTimeout, None,
                                          reactor=reactor)
            if antiIdle == 0:
                preWrappedNsf.leecherConnectors.append(connector)
            connectionCount += 1
        preWrappedNsf.setConnectionCount(connectionCount)

    if antiIdle == 0:
        action = ''
    else:
        action = 'Opening '
    fillServerStatus = ''
    if isinstance(Hellanzb.queue, FillServerQueue):
        fillServerStatus = '[fillserver: %i] ' % preWrappedNsf.fillServerPriority
    msg = preWrappedNsf.color + '(' + serverName + ') ' + Hellanzb.ACODE.RESET + \
        fillServerStatus + action + str(connectionCount)
    logFileMsg = '(' + serverName + ') ' + fillServerStatus + 'Opening ' + \
        str(connectionCount)
    if connectionCount == 1:
        suffix = ' connection'
    else:
        suffix = ' connections'
    msg += suffix
    logFileMsg += suffix
    if antiIdle != 0:
        msg += '...'
        logFileMsg += '...'
    logFile(logFileMsg)
    noLogFile(msg)
    # HACK: remove this as a recentLog entry -- replace it with the version without color
    # codes
    Hellanzb.recentLogs.logEntries.pop()
    Hellanzb.recentLogs.append(logging.INFO, logFileMsg)

    # Let the queue know about this new serverPool
    Hellanzb.queue.serverAdd(preWrappedNsf)
        
    return connectionCount

def startNZBLeecher():
    """ gogogo """
    defaultAntiIdle = int(4.5 * 60) # 4.5 minutes
    defaultIdleTimeout = 30
    
    totalCount = 0
    # Order the initialization of servers by the fillserver priority, if fillserver
    # support is enabled
    serverDictsByPriority = Hellanzb.SERVERS.items()
    if isinstance(Hellanzb.queue, FillServerQueue):
        serverDictsByPriority.sort(lambda x, y: cmp(x[1].get('fillserver'),
                                                    y[1].get('fillserver')))
    for serverId, serverDict in serverDictsByPriority:
        if not serverDict.get('enabled') is False:
            totalCount += connectServer(serverId, serverDict, defaultAntiIdle, defaultIdleTimeout)

    # How large the scroll ticker should be
    Hellanzb.scroller.maxCount = totalCount

    # Initialize the retry queue, (this only initializes it when it's necessary) for
    # automatic failover. It contains multiple sub-queues that work within the NZBQueue,
    # for queueing segments that failed to download on particular serverPools.
    Hellanzb.queue.initRetryQueue()

    # Allocate only one thread, just for decoding
    reactor.suggestThreadPoolSize(1)

    # Well, there's egg and bacon; egg sausage and bacon; egg and spam; egg bacon and
    # spam; egg bacon sausage and spam; spam bacon sausage and spam; spam egg spam spam
    # bacon and spam; spam sausage spam spam bacon spam tomato and spam;
    reactor.run()
    # Spam! Spam! Spam! Spam! Lovely spam! Spam! Spam!

    # Safely tear down the app only after the reactor shutdown
    finishShutdown()
    
"""
Copyright (c) 2005 Philip Jenvey <pjenvey@groovie.org>
                   Ben Bangert <bbangert@groovie.org>
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
