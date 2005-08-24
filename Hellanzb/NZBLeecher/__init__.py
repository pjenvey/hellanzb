"""

NZBLeecher - Downloads article segments from an NZBQueue, then passes them off for
decoding

The NZBLeecher module (ArticleDecoder, NZBModel etc) is a rewrite of pynewsleecher by
Freddie (freddie@madcowdisease.org) utilizing the twisted framework

(c) Copyright 2005 Philip Jenvey, Ben Bangert
[See end of file]
"""
import os, re, time, Hellanzb
from sets import Set
from shutil import move
from twisted.internet import reactor
from twisted.internet.error import ConnectionRefusedError, DNSLookupError
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.protocols.basic import LineReceiver
from twisted.protocols.policies import TimeoutMixin, ThrottlingFactory
from twisted.python import log
from Hellanzb.Daemon import cancelCurrent, endDownload, scanQueueDir
from Hellanzb.Log import *
from Hellanzb.Logging import LogOutputStream, NZBLeecherTicker
from Hellanzb.Util import prettySize, rtruncate, truncateToMultiLine, EmptyForThisPool, PoolsExhausted
from Hellanzb.NZBLeecher.nntp import NNTPClient, extractCode
from Hellanzb.NZBLeecher.ArticleDecoder import decode
from Hellanzb.NZBLeecher.NZBModel import NZBQueue
from Hellanzb.NZBLeecher.NZBLeecherUtil import HellaThrottler, HellaThrottlingFactory
from Queue import Empty

__id__ = '$Id$'

def initNZBLeecher():
    """ Init """
    # Direct twisted log output to the debug level
    fileStream = LogOutputStream(debug)
    log.startLogging(fileStream)

    # Create the one and only download queue
    Hellanzb.queue = NZBQueue()

    Hellanzb.totalReadBytes = 0
    Hellanzb.totalStartTime = None
    
    # The NZBLeecherFactories
    Hellanzb.nsfs = []
    Hellanzb.totalSpeed = 0
    Hellanzb.totalArchivesDownloaded = 0
    Hellanzb.totalFilesDownloaded = 0
    Hellanzb.totalSegmentsDownloaded = 0
    Hellanzb.totalBytesDownloaded = 0

    # this class handles updating statistics via the SCROLL level (the UI)
    Hellanzb.scroller = NZBLeecherTicker()

    if hasattr(Hellanzb, 'MAX_RATE'):
        Hellanzb.ht = HellaThrottler(int(Hellanzb.MAX_RATE) * 1024)
    else:
        Hellanzb.ht = HellaThrottler()

    # loop to scan the queue dir during download
    Hellanzb.downloadScannerID = None

    startNZBLeecher()

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
    connectionCount = 0
    hosts = serverDict['hosts']
    connections = int(serverDict['connections'])
    info('(' + serverName + ') ', appendLF = False)

    for host in hosts:
        antiIdle = int(setWithDefault(serverDict, 'antiIdle', defaultAntiIdle))
        idleTimeout = int(setWithDefault(serverDict, 'idleTimeout', defaultIdleTimeout))

        nsf = NZBLeecherFactory(serverDict['username'], serverDict['password'],
                                idleTimeout, antiIdle, host,
                                serverName)
        Hellanzb.nsfs.append(nsf)

        # FIXME: pass this to the factory constructor
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
                reactor.connectTCP(host, port, nsf,
                                   bindAddress = serverDict['bindTo'])
            else:
                reactor.connectTCP(host, port, nsf)
            connectionCount += 1
        preWrappedNsf.setConnectionCount(connectionCount)

    if connectionCount == 1:
        info('Opening ' + str(connectionCount) + ' connection...')
    else:
        info('Opening ' + str(connectionCount) + ' connections...')

    # Let the queue know about this new serverPool
    Hellanzb.queue.serverAdd(serverName)
        
    return connectionCount

def startNZBLeecher():
    """ gogogo """
    defaultAntiIdle = int(4.5 * 60) # 4.5 minutes
    defaultIdleTimeout = 30
    
    totalCount = 0
    for serverId, serverDict in Hellanzb.SERVERS.iteritems():
        totalCount += connectServer(serverId, serverDict, defaultAntiIdle, defaultIdleTimeout)

    if len(Hellanzb.SERVERS) > 1:
        # Initialize the retry queue. It contains multiple sub-queues that work within the
        # NZBQueue, for queueing segments that failed to download on particular
        # serverPools. Obviously there's no need for this unless we're using multiple
        # serverPools
        Hellanzb.queue.initRetryQueue()

    # How large the scroll ticker should be
    Hellanzb.scroller.maxCount = totalCount

    # Allocate only one thread, just for decoding
    reactor.suggestThreadPoolSize(1)

    # Well, there's egg and bacon; egg sausage and bacon; egg and spam; egg bacon and
    # spam; egg bacon sausage and spam; spam bacon sausage and spam; spam egg spam spam
    # bacon and spam; spam sausage spam spam bacon spam tomato and spam;
    reactor.run()
    # Spam! Spam! Spam! Spam! Lovely spam! Spam! Spam!

PHI = 1.6180339887498948 # (1 + math.sqrt(5)) / 2
class NZBLeecherFactory(ReconnectingClientFactory):

    def __init__(self, username, password, activeTimeout, antiIdleTimeout, hostname,
                 serverPoolName):
        self.username = username
        self.password = password
        self.antiIdleTimeout = antiIdleTimeout
        self.activeTimeout = activeTimeout
        self.hostname = hostname
        self.serverPoolName = serverPoolName

        self.host = None
        self.port = None

        # statistics for the current session (sessions end when downloading stops on all
        # clients). used for the more accurate total speeds shown in the UI
        self.sessionReadBytes = 0
        self.sessionSpeed = 0
        self.sessionStartTime = None

        # all of this factory's clients 
        self.clients = []
        # The factory maintains the NZBLeecher id, and recycles them when building new
        # clients
        self.clientIds = []

        # all clients that are actively leeching FIXME: is a Set necessary here?
        self.activeClients = Set()

        # Maximum delay before reconnecting after disconnection
        self.maxDelay = 2 * 60

        self.connectionCount = 0

        # server reconnecting drop off factor, by default e. PHI (golden ratio) is a lower
        # factor than e
        self.factor = PHI # (Phi is acceptable for use as a factor if e is too large for
                          # your application.)

        # FIXME: after too many disconnections and or no established
        # connections, info('Unable to connect!: + str(error)')

    def buildProtocol(self, addr):
        p = NZBLeecher(self.username, self.password)
        p.factory = self
        p.id = self.clientIds[0]
        self.clientIds.remove(p.id)
        
        # All clients inherit the factory's anti idle timeout setting
        p.activeTimeout = self.activeTimeout
        p.antiIdleTimeout = self.antiIdleTimeout
        
        self.clients.append(p)

        # FIXME: registerScrollingClient
        Hellanzb.scroller.size += 1
        return p

    def clientConnectionFailed(self, connector, reason):
        """ Handle failed connection attempts """
        debug('clientConnectionFailed: ' + str(connector) + ' reason: ' + str(reason) + '  ' + \
              'class: ' + str(reason.value.__class__) + ' args: ' + str(reason.value.args), reason)
        if isinstance(reason.value, DNSLookupError):
            error('DNS lookup failed for hostname: ' + connector.getDestination().host)
        elif isinstance(reason.value, ConnectionRefusedError):
            # FIXME: this spams too much
            #error('Connection refused, hostname: ' + connector.getDestination().host)
            pass
            
        # Overwrite ReconnectClientFactory so reconnecting happens after a connection
        # timeout (TimeoutError)
        # FIXME: twisted should provide a toggle for this. submit a patch
        from twisted.internet.error import TimeoutError, UserError
        if self.continueTrying:
            self.connector = connector
            if not reason.check(UserError) or reason.check(TimeoutError):
                self.retry()

    def fetchNextNZBSegment(self):
        """ Begin or continue downloading on all of this factory's clients """
        if Hellanzb.downloadPaused:
            # 'continue' is responsible for re-triggerering all clients in this case
            return
        
        for p in self.clients:
            if p.isLoggedIn and not p.activated:
                reactor.callLater(0, p.fetchNextNZBSegment)

    def beginDownload(self):
        """ Start the download """
        now = time.time()
        self.sessionReadBytes = 0
        self.sessionSpeed = 0
        self.sessionStartTime = now
        self.fetchNextNZBSegment()

    def setConnectionCount(self, connectionCount):
        """ Set the number of total connections for this factory """
        self.connectionCount = connectionCount
        self.clientIds = range(self.connectionCount)

    def activateClient(self, client):
        """ Mark this client as being activated (in the download loop) """
        if client not in self.activeClients:
            self.activeClients.add(client)

    def deactivateClient(self, client, justThisDownloadPool = False):
        """ Deactive the specified client """
        self.activeClients.remove(client)
        
        # Reset stats if necessary
        if not len(self.activeClients):
            self.sessionReadBytes = 0
            self.sessionSpeed = 0
            self.sessionStartTime = None

        # If we got the justThisDownloadPool, that means this serverPool is done, but
        # there are segments left in the queue for other serverPools (we're not completely
        # done)
        if justThisDownloadPool:
            return

        # Check if we're completely done
        totalActiveClients = 0
        for nsf in Hellanzb.nsfs:
            totalActiveClients += len(nsf.activeClients)
            
        if totalActiveClients == 0:
            endDownload()

class NZBLeecher(NNTPClient, TimeoutMixin):
    """ Extends twisted NNTPClient to download NZB segments from the queue, until the queue
    contents are exhausted """
        
    # From Twisted 2.0, twisted.basic.LineReceiver, specifically for the imported
    # Twisted 2.0 dataReceived (now dataReceivedToLines)
    line_mode = 1
    __buffer = ''
    delimiter = '\r\n'
    paused = False

    # This value exists in twisted and doesn't do much (except call lineLimitExceeded
    # when a line that long is exceeded). Knowing twisted that function is probably a
    # hook for defering processing when it might take too long with too much received
    # data. hellanzb can definitely receive much longer lines than LineReceiver's
    # default value. i doubt higher limits degrade its performance much
    MAX_LENGTH = 262144
    
    # End twisted.basic.LineReceiver 
        
    # usenet EOF char minus the final '\r\n'
    RSTRIPPED_END = delimiter + '.'

    def __init__(self, username, password):
        """ """
        NNTPClient.__init__(self)
        self.username = username
        self.password = password

        # successful GROUP commands during this session
        self.activeGroups = []
        # unsuccessful GROUP commands during this session
        self.failedGroups = []
        # group we're currently in the process of getting
        self.gettingGroup = None

        # current article (<segment>) we're dealing with
        self.currentSegment = None

        self.isLoggedIn = False
        self.setReaderAfterLogin = False
            
        self.activeTimeout = None
        # Idle time -- after being idle this long send anti idle requests
        self.antiIdleTimeout = None

        # whether or not this NZBLeecher is the in the fetchNextNZBSegment download loop
        self.activated = False

        # Whether or not this client was created when hellanzb downloading was paused
        self.pauseReconnected = False

        # cache whether or not the response code has been received. only the BODY call
        # (dataReceivedToFile) utilizes this var
        self.gotResponseCode = False

        # hold the last chunk's final few bytes for when searching for the EOF char
        self.lastChunk = ''

    def authInfo(self):
        """ """
        self.sendLine('AUTHINFO USER ' + self.username)
        self._newState(None, self.authInfoFailed, self._authInfoUserResponse)

    def _authInfoUserResponse(self, (code, message)):
        """ """
        if code == 381:
            self.sendLine('AUTHINFO PASS ' + self.password)
            self._newState(None, self.authInfoFailed, self._authInfoPassResponse)
        else:
            self.authInfoFailed('%d %s' % (code, message))
        self._endState()

    def _authInfoPassResponse(self, (code, message)):
        """ """
        if code == 281:
            self.gotAuthInfoOk('%d %s' % (code, message))
        else:
            self.authInfoFailed('%d %s' % (code, message))
        self._endState()

    def gotAuthInfoOk(self, message):
        """ Override for notification when authInfo() action is successful """
        debug(str(self) + ' AUTHINFO succeeded: ' + message)
        self.isLoggedIn = True

        # Reset the auto-reconnect delay
        self.factory.resetDelay()

        if self.setReaderAfterLogin:
            self.setReader()
        else:
            if Hellanzb.downloadPaused:
                self.pauseReconnected = True
                return
            else:
                reactor.callLater(0, self.fetchNextNZBSegment)

    def authInfoFailed(self, err):
        "Override for notification when authInfoFailed() action fails"
        debug(str(self) + ' AUTHINFO failed: ' + str(err))
        # FIXME: This gives us too much scroll. Need to only do it selectively
        #error(self.factory.hostname + '[' + str(self.id).zfill(2) + '] Authorization failed: ' + str(err))

    def connectionMade(self):
        debug(str(self) + ' CONNECTION MADE')
        NNTPClient.connectionMade(self)
        self.setTimeout(self.activeTimeout)

        # 'mode reader' is sometimes necessary to enable 'reader' mode.
        # However, the order in which 'mode reader' and 'authinfo' need to
        # arrive differs between some NNTP servers. Try to send
        # 'mode reader', and if it fails with an authorization failed
        # error, try again after sending authinfo.
        self.setReader()

    def connectionLost(self, reason):
        debug(str(self) + ' CONNECTION LOST')
        self.setTimeout(None)
        # FIXME: could put failed segments into a failed queue. connections that are
        # flaged as being fill servers would try to attempt to d/l the failed files. you
        # couldn't write a 0 byte file to disk in that case -- not until all fill servers
        # had tried downloading
        
        # ReconnectingClientFactory will pretend it wants to reconnect after we CTRL-C --
        # we'll quiet it by canceling it
        if Hellanzb.SHUTDOWN:
            self.factory.stopTrying()

        NNTPClient.connectionLost(self) # calls self.factory.clientConnectionLost(self, reason)

        if self.currentSegment != None:
            if (self.currentSegment.priority, self.currentSegment) in Hellanzb.scroller.segments:
                Hellanzb.scroller.removeClient(self.currentSegment)

            if self.currentSegment.encodedData != None:
                # Close the file handle if it's still open
                try:
                    self.currentSegment.encodedData.close()
                finally:
                    pass

            # twisted doesn't reconnect our same client connections, we have to pitch
            # stuff back into the queue that hasn't finished before the connectionLost
            # occurred
            if self.currentSegment.nzbFile.nzb in Hellanzb.queue.currentNZBs():
                # Only requeue the segment if its archive hasn't been previously postponed
                debug(str(self) + ' requeueing segment: ' + self.currentSegment.getDestination())
                Hellanzb.queue.requeue(self.factory.serverPoolName, self.currentSegment)

                # There's a funny case where other clients received Empty from the queue,
                # then afterwards we lost the connection (say the connection timed
                # out). So fire off the other ones to immediately handle the just requeued
                # segment, unless they're already busy or we're paused or we were just
                # cancelled
                if not Hellanzb.downloadPaused and not self.currentSegment.nzbFile.nzb.canceled:
                    self.factory.fetchNextNZBSegment()

            else:
                debug(str(self) + ' DID NOT requeue existing segment: ' + self.currentSegment.getDestination())
            
            self.currentSegment = None
        
        # Continue being quiet about things if we're shutting down
        if not Hellanzb.SHUTDOWN:
            debug(str(self) + ' lost connection: ' + str(reason))

        self.activeGroups = []
        self.failedGroups = []
        self.gettingGroup = None
        self.factory.clients.remove(self)
        if self in self.factory.activeClients:
            self.factory.activeClients.remove(self)
        Hellanzb.scroller.size -= 1
        self.isLoggedIn = False
        self.setReaderAfterLogin = False
        self.factory.clientIds.insert(0, self.id)
        self.gotResponseCode = False
        self.lastChunk = ''

    def setReader(self):
        """ Tell the server we're a news reading client (MODE READER) """
        self.sendLine('MODE READER')
        self._newState(None, self.setReaderFailed, self.setReaderModeResponse)

    def setReaderModeResponse(self, (code, message)):
        if code in (200, 201):
            self.setReaderSuccess()
        else:
            self.setReaderFailed((code, message))
        self._endState()
        
    def setReaderSuccess(self):
        """ """
        debug(str(self) + ' MODE READER successful')
        if self.setReaderAfterLogin or (self.username == None and self.password == None):
            # Set isLoggedIn here, for the case that no authorization was required
            # (username & pass == None). This would have already been set to True by
            # authInfoSuccess otherwise
            self.isLoggedIn = True
            
            if Hellanzb.downloadPaused:
                self.pauseReconnected = True
                return
            else:
                reactor.callLater(0, self.fetchNextNZBSegment)
        else:
            self.authInfo()
        
    def setReaderFailed(self, err):
        """ If the MODE READER failed prior to login, this server probably only accepts it after
        login """
        if self.username == None and self.password == None:
            warn('Could not MODE READER on no auth server (%s:%i), returned: %s' % \
                 (self.factory.host, self.factory.port, str(err)))
            reactor.callLater(0, self.fetchNextNZBSegment)
        elif not self.isLoggedIn:
            self.setReaderAfterLogin = True
            self.authInfo()
        else:
            debug(str(self) + 'MODE READER failed, err: ' + str(err))

    def activate(self):
        """ Mark this client as being active -- that is, it is in the fetchNextNZBSegment download
        loop """
        if not self.activated:
            debug(str(self) + ' ACTIVATING')
            self.activated = True

            # we're now timing out the connection, set the appropriate timeout
            self.setTimeout(self.activeTimeout)

            self.factory.activateClient(self)

    def deactivate(self, justThisDownloadPool = False):
        """ Deactivate this client """
        if self.activated:
            debug(str(self) + ' DEACTIVATING')
            self.activated = False

            # we're now anti idling the connection, set the appropriate timeout
            self.setTimeout(self.antiIdleTimeout)

            self.factory.deactivateClient(self, justThisDownloadPool)
        
    def fetchNextNZBSegment(self):
        """ Pop nzb article from the queue, and attempt to retrieve it if it hasn't already been
        retrieved"""
        if self.currentSegment is None:

            try:
                priority, self.currentSegment = Hellanzb.queue.getSmart(self.factory.serverPoolName)
                self.currentSegment.encodedData = open(Hellanzb.DOWNLOAD_TEMP_DIR + os.sep + \
                                                       self.currentSegment.getTempFileName() + '_ENC',
                                                       'w')
                debug(str(self) + ' PULLED FROM QUEUE: ' + self.currentSegment.getDestination())

                # got a segment - set ourselves as active unless we're already set as so
                self.activate()

                # Determine the filename to show in the UI
                if self.currentSegment.nzbFile.showFilename == None:
                    if self.currentSegment.nzbFile.filename == None:
                        self.currentSegment.nzbFile.showFilenameIsTemp = True
                        
                    self.currentSegment.nzbFile.showFilename = self.currentSegment.nzbFile.getFilename()

            except EmptyForThisPool:
                debug(str(self) + ' EMPTY QUEUE (for just this pool)')
                # done for this download pool
                self.deactivate(justThisDownloadPool = True)
                return
            
            except Empty:
                debug(str(self) + ' EMPTY QUEUE')
                # all done
                self.deactivate()
                return

        # Change group
        for group in self.currentSegment.nzbFile.groups:

            # NOTE: we could get away with activating only one of the groups instead of
            # all
            if group not in self.activeGroups and group not in self.failedGroups:
                debug(str(self) + ' getting GROUP: ' + group)
                self.fetchGroup(group)
                return

            # We only need to get the groups once during the lifetime of this
            # NZBLeecher. Once we've ensured all groups have been attempted to be
            # retrieved (the above block of code), check that we haven't failed finding
            # all groups (if so, punt) here instead of getGroupFailed
            elif self.allGroupsFailed(self.currentSegment.nzbFile.groups):
                try:
                    Hellanzb.queue.requeueMissing(self.factory.serverPoolName, self.currentSegment)
                    debug(str(self) + ' All groups failed, requeueing to another pool!')
                    self.currentSegment = None
                    reactor.callLater(0, self.fetchNextNZBSegment)
                
                except PoolsExhausted:
                    error('Unable to retrieve *any* groups for file (subject: ' + \
                          self.currentSegment.nzbFile.subject + ')')
                    msg = 'Groups:'
                    for group in self.currentSegment.nzbFile.groups:
                        msg += ' ' + group
                    error(msg)
                    error('Cancelling NZB download: ' + self.currentSegment.nzbFile.nzb.archiveName)

                    cancelCurrent()
                    
                return
            
        # Don't call later here -- we could be disconnected and lose our currentSegment
        # before it even happens!
        #reactor.callLater(0, self.fetchBody, str(self.currentSegment.messageId))
        self.fetchBody(str(self.currentSegment.messageId))

    def fetchGroup(self, group):
        self.gettingGroup = group
        NNTPClient.fetchGroup(self, group)
        
    def fetchBody(self, index):
        debug(str(self) + ' getting BODY: <' + self.currentSegment.messageId + '> ' + \
              self.currentSegment.getDestination())
        start = time.time()
        if self.currentSegment.nzbFile.downloadStartTime == None:
            self.currentSegment.nzbFile.downloadStartTime = start
        
        Hellanzb.scroller.addClient(self.currentSegment)

        NNTPClient.fetchBody(self, '<' + index + '>')

    def gotBody(self, body):
        """ Queue the article body for decoding and continue fetching the next article """
        debug(str(self) + ' got BODY: ' + ' <' + self.currentSegment.messageId + '> ' + \
              self.currentSegment.getDestination())

        self.processBodyAndContinue(body)

    def getBodyFailed(self, err):
        """ Handle a failure of the BODY command. Ensure the failed segment gets a 0 byte file
        written to the filesystem when this occurs """
        debug(str(self) + ' get BODY FAILED, errno: ' + str(err) + ' for messageId: <' + \
              self.currentSegment.messageId + '> ' + self.currentSegment.getDestination() + \
              ' expected size: ' + str(self.currentSegment.bytes))
        self.gotResponseCode = False # for dataReceivedToFile
        self.lastChunk = ''
        
        code = extractCode(err)
        if code is not None:
            code, msg = code
            if code in (423, 430):
                try:
                    Hellanzb.queue.requeueMissing(self.factory.serverPoolName, self.currentSegment)
                    debug(str(self) + ' ' + self.currentSegment.nzbFile.showFilename + \
                          ' segment: ' + str(self.currentSegment.number) + \
                          ' Article is missing! Attempting to requeue on a different pool!')
                    Hellanzb.scroller.removeClient(self.currentSegment)
                    self.currentSegment = None
                    reactor.callLater(0, self.fetchNextNZBSegment)
                    return
                
                except PoolsExhausted:
                    info(self.currentSegment.nzbFile.showFilename + ' segment: ' + \
                         str(self.currentSegment.number) + ' Article is missing!')
            elif code == 400 and \
                    (msg.lower().find('idle timeout') > -1 or \
                     msg.lower().find('session timeout') > -1):
                # Handle:
                # 2005-05-05 14:41:18,232 DEBUG NZBLeecher[7] get BODY FAILED, error: 400
                # fe01-unl.iad01.newshosting.com: Idle timeout. for messageId:
                # <part59of201.2T6kmGJqWQXOuewjuk&I@powerpost2000AA.local>
                # 2005-05-13 08:25:23,260 DEBUG NZBLeecher[24] get BODY FAILED, error: 400
                # fe02-unl.iad01.newshosting.com: Session timeout. for messageId:
                # <part19of201.Rp0zp0zFz7LkFy2sk2cN@powerpost2000AA.local>
                 
                # fine, be that way
                debug(str(self) + ' received Session/Idle TIMEOUT from server, disconnecting')
                self.transport.loseConnection()
                return
                
        self.processBodyAndContinue('')

    def processBodyAndContinue(self, articleData):
        """ Defer decoding of the specified articleData of the currentSegment, reset our state and
        continue fetching the next queued segment """
        Hellanzb.scroller.removeClient(self.currentSegment)

        self.currentSegment.articleData = articleData
        self.deferSegmentDecode(self.currentSegment)

        self.currentSegment = None

        Hellanzb.totalSegmentsDownloaded += 1
        reactor.callLater(0, self.fetchNextNZBSegment)
        
    def deferSegmentDecode(self, segment):
        """ Decode the specified segment in a separate thread """
        reactor.callInThread(decode, segment)
        
    def gotGroup(self, group):
        group = group[3]
        self.activeGroups.append(group)
        self.gettingGroup = None
        debug(str(self) + ' got GROUP: ' + group)

        reactor.callLater(0, self.fetchNextNZBSegment)

    def getGroupFailed(self, err):
        group = self.gettingGroup
        self.failedGroups.append(group)
        self.gettingGroup = None
        #warn('GROUP command failed for group: ' + group)
        debug(str(self) + ' GROUP command failed for group: ' + group + ' result: ' + str(err))

        # fetchNextNZBSegment will determine if this failed GROUP command was fatal (this
        # was the only group available for this NZB file, so cancelCurrent()) or not a big
        # deal (other groups were successfully retrieved for this segment and we can
        # safely continue to fetchBody())
        self.fetchNextNZBSegment()

    def allGroupsFailed(self, groups):
        """ Determine if the all the specified groups were previously failed to have been
        retrieved by this NZBLeecher """
        failed = 0
        for group in groups:
            if group in self.failedGroups:
                failed += 1
    
        if failed == len(groups):
            return True
    
        return False
                
    def _stateBody(self, line):
        """ The normal _stateBody converts the list of lines downloaded to a string, we want to
        keep these lines in a list throughout life of the processing (should be more
        efficient) """
        if line != '.':
            self._newLine(line, 0)
        else:
            #self.gotBody('\n'.join(self._endState()))
            self.gotBody(self._endState())

    def _stateHelp(self, line):
        if line != '.':
            self._newLine(line, 0)
        else:
            self.gotHelp('\n'.join(self._endState()))

    def fetchHelp(self):
        debug(str(self) + ' fetching HELP')
        self.sendLine('HELP')
        self._newState(self._stateHelp, self.getHelpFailed)

    def gotHelp(self, idle):
        debug(str(self) + ' got HELP')

    def getHelpFailed(self, err):
        "Override for getHelpFailed"
        debug(str(self) + ' got HELP failed: ' + str(err))

    def lineLengthExceeded(self, line):
        error('Error!!: LineReceiver.MAX_LENGTH exceeded. size: ' + str(len(line)))
        debug(str(self) + ' EXCEEDED line length, len: ' + str(len(line)) + ' line: ' + line)

    def updateByteCount(self, lineLen):
        Hellanzb.totalReadBytes += lineLen
        Hellanzb.totalBytesDownloaded += lineLen
        self.factory.sessionReadBytes += lineLen
        if self.currentSegment != None:
            self.currentSegment.nzbFile.totalReadBytes += lineLen

    def updateStats(self, now):
        if self.currentSegment == None or self.currentSegment.nzbFile.downloadStartTime == None:
            return

        oldPercentage = self.currentSegment.nzbFile.downloadPercentage
        self.currentSegment.nzbFile.downloadPercentage = min(100,
                                                             int(float(self.currentSegment.nzbFile.totalReadBytes + \
                                                                       self.currentSegment.nzbFile.totalSkippedBytes) /
                                                                 max(1, self.currentSegment.nzbFile.totalBytes) * 100))

        if self.currentSegment.nzbFile.downloadPercentage > oldPercentage:
            elapsed = max(0.1, now - self.currentSegment.nzbFile.downloadStartTime)
            elapsedSession = max(0.1, now - self.factory.sessionStartTime)

            self.currentSegment.nzbFile.speed = self.currentSegment.nzbFile.totalReadBytes / elapsed / 1024.0
            ##self.factory.sessionSpeed = self.factory.sessionReadBytes / elapsedSession / 1024.0
            elapsed = now - self.factory.sessionStartTime
            if elapsed > 5:
                self.factory.sessionSpeed = self.factory.sessionReadBytes / max(0.1, elapsed) / 1024.0
                self.factory.sessionReadBytes = 0
                self.factory.sessionStartTime = now
            
            Hellanzb.scroller.updateLog()

    def antiIdleConnection(self):
        """ anti idle the connection """
        self.fetchHelp()

    def lineReceived(self, line):
        """ cut & paste from NNTPClient -- also allows 100 codes for HELP responses """
        if not len(self._state):
            self._statePassive(line)
        elif self._getResponseCode() is None:
            code = extractCode(line)
            if code is None or (not (200 <= code[0] < 400) and code[0] != 100):    # An error!
                try:
                    self._error[0](line)
                except TypeError, te:
                    debug(str(self) + ' lineReceived GOT TYPE ERROR!: ' + str(te) + ' state name: ' + \
                          self._state[0].__name__ + ' code: ' + str(code) + ' line: ' + line)
                self._endState()
            else:
                self._setResponseCode(code)
                if self._responseHandlers[0]:
                    self._responseHandlers[0](code)
        else:
            self._state[0](line)

    def dataReceived(self, data):
        """ *From Twisted-2.0*
        Supposed to be at least 3x as fast.
        
        Protocol.dataReceived.
        Translates bytes into lines, and calls lineReceived (or
        rawDataReceived, depending on mode.)
        """
        # Update statistics
        self.updateByteCount(len(data))
        self.updateStats(Hellanzb.preReadTime)

        # got data -- reset the anti idle timeout
        self.resetTimeout()

        if len(self._state) and self._state[0] == self._stateBody:
            # Write the data to disk as it's received
            return self.dataReceivedToFile(data)

        else:
            # return an array of the received data's lines to the callback function
            return self.dataReceivedToLines(data)

    def dataReceivedToLines(self, data):
        """ Convert the raw dataReceived into lines subsequently parsed by lineReceived. This is
        slower/more CPU intensive than the optimized dataReceivedToFile. This function
        parses the received data into lines (delimited by new lines) -- the typical
        twisted-2.0 LineReceiver way of doing things. Unlike dataReceivedToFile, it
        doesn't require a file object to write to """
        #  *From Twisted-2.0*
        # Supposed to be at least 3x as fast.
        # Protocol.dataReceived.
        # Translates bytes into lines, and calls lineReceived (or
        # rawDataReceived, depending on mode.)
        self.__buffer = self.__buffer+data
        lastoffset=0
        while not self.paused:
            offset=self.__buffer.find(self.delimiter, lastoffset)
            if offset == -1:
                self.__buffer=self.__buffer[lastoffset:]
                if len(self.__buffer) > self.MAX_LENGTH:
                    line=self.__buffer
                    self.__buffer=''
                    return self.lineLengthExceeded(line)
                break
            
            line=self.__buffer[lastoffset:offset]
            lastoffset=offset+len(self.delimiter)
            
            if len(line) > self.MAX_LENGTH:
                line=self.__buffer[lastoffset:]
                self.__buffer=''
                return self.lineLengthExceeded(line)
            why = self.lineReceived(line)
            if why or self.transport and self.transport.disconnecting:
                self.__buffer = self.__buffer[lastoffset:]
                return why
        else:
            self.__buffer=self.__buffer[lastoffset:]

    def dataReceivedToFile(self, data):
        """ Dump the raw recieved data to the current segment's encoded-data-temp file. This
        function is faster than parsing the received data into individual lines
        (dataReceivedToLines) -- it simply dumps the data to file, and looks for the EOF
        string for usenet messages: "\r\n.\r\n".

        It manually rstrip()s every chunk of data received, then matches both the
        rstripped data and rstripped-off data with their associated usenet EOF pieces (to
        safely detect the EOF across potentially two data chunks)

        It is smarter about parsing the usenet response code (lineReceived does this for
        dataReceivedToLines and is lazier about it)
        
        Ultimately, significantly less work than dataReceivedToLines """
        if not self.gotResponseCode:
            # find the nntp response in the header of the message (the BODY command)
            lstripped = data.lstrip()
            off = lstripped.find(self.delimiter)
            line = lstripped[:off]

            code = extractCode(line)
            if code is None or (not (200 <= code[0] < 400) and code[0] != 100): # An error!
                try:
                    self.currentSegment.encodedData.close()
                    self._error[0](line)
                # FIXME: why is this exception thrown? it was previously breaking
                # connections -- this is now caught to avoid the completely breaking of
                # the connection
                except TypeError, te:
                    debug(str(self) + ' lineReceived GOT TYPE ERROR!: ' + str(te) + ' state name: ' + \
                          self._state[0].__name__ + ' code: ' + str(code) + ' line: ' + line)
                self._endState()
                return
            else:
                self._setResponseCode(code)
                self.gotResponseCode = True
                data = lstripped[off:]

        # write data to disk
        self.currentSegment.encodedData.write(data)

        # check for the EOF string in the last certain bytes of the received data
        # (possibly across two different received chunks)
        test = self.lastChunk + data

        # NOTE: we manually rstrip here because it's the fastest failsafe way of finding
        # the EOF string. These downloaded chunks will not have trailing whitespace
        # probably max 95% of the time, and when they do they're likely to have few
        # trailing whitespace characters (so the while loop will iterate once, or maybe
        # just a few times). The alternative is rfind()ing the entire EOF string -- rfind
        # is implemented in C but would end up searching the entire string that 95% of the
        # time
        
        # rstrip the test data. determine if that stripped off data only begins with
        # '\r\n' and the stripped data ends with '\r\n.'
        length = len(test)
        index = length - 1
        while index >= 0:
            if test[index].isspace():
                index -= 1
                continue

            # we just passed the end
            index += 1
            break

        if index != length:
            # rstripped some whitespace. since there is trailing whitespace, check for the
            # EOF string
            stripped = test[:index]
            firstTwoWhitespace = test[index:index + 2]
        
            if firstTwoWhitespace == self.delimiter and \
                    stripped[-len(self.RSTRIPPED_END):] == self.RSTRIPPED_END:
                # found EOF, done
                self.currentSegment.encodedData.close()
                self.gotResponseCode = False
                self.lastChunk = ''
                self.gotBody(self._endState())
                
        else:
            # didn't strip anything, or didn't find the EOF.  save the last small chunk
            # for later comparison
            self.lastChunk = data[-(len(self.delimiter) - 1):]

    def timeoutConnection(self):
        """ Called when the connection times out -- i.e. when we've been idle longer than the
        self.timeOut value. will time out (disconnect) the connection if actively
        downloading, otherwise the timeOut value acts as a the anti idle time out """
        if self.activated:
            debug(str(self) + ' TIMING OUT connection')
            self.transport.loseConnection()
        else:
            debug(str(self) + ' ANTI IDLING connection')
            self.antiIdleConnection()
            
            # TimeoutMixin assumes we're done (timed out) after timeoutConnection. Since we're
            # still connected, manually reset the timeout
            self.setTimeout(self.antiIdleTimeout)

    def __str__(self):
        """ Return the name of this NZBLeecher instance """
        return self.factory.serverPoolName + '[' + str(self.id) + ']'
    
"""
/*
 * Copyright (c) 2005 Philip Jenvey <pjenvey@groovie.org>
 *                    Ben Bangert <bbangert@groovie.org>
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 * 3. The name of the author or contributors may not be used to endorse or
 *    promote products derived from this software without specific prior
 *    written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
 * FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 * DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
 * OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
 * HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 * LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
 * OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
 * SUCH DAMAGE.
 *
 * $Id$
 */
"""
