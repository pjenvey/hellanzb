"""
"""

import os, sys, time
from thread import start_new_thread
from threading import Condition
from twisted.internet import reactor
from twisted.news.news import UsenetClientFactory
from twisted.protocols.nntp import NNTPClient
from twisted.python import log
from Hellanzb.Logging import *
from Hellanzb.NewzSlurp.ArticleDecoder import decode
from Queue import Empty

from twisted.flow import flow
from twisted.flow.threads import Threaded

__id__ = '$Id$'

def initNewzSlurp():
    """ Init """
    # Direct the twisted output to the debug level
    fileStream = LogOutputStream(debug)
    log.startLogging(fileStream)

    from Hellanzb.NewzSlurp.NZBUtil import NZBQueue
    # Create the one and only download queue
    Hellanzb.queue = NZBQueue()

    # Create the one and only twisted factory
    Hellanzb.nsf = NewzSlurperFactory()

    # notified when an NZB file has finished donwloading
    Hellanzb.nzbfileDone = Condition()
    
    startNewzSlurp()

def startNewzSlurp():
    """ gogogo """
    connectionCount = 0
    for serverId, serverInfo in Hellanzb.SERVERS.iteritems():
        hosts = serverInfo['hosts']
        connections = int(serverInfo['connections'])
        info('(' + serverId + ') Connecting... ', appendLF = False)

        for host in hosts:
            host, port = host.split(':')
            for connection in range(connections):
                # FIXME: Is this sane?
                Hellanzb.nsf.username = serverInfo['username']
                Hellanzb.nsf.password = serverInfo['password']
                reactor.connectTCP(host, int(port), Hellanzb.nsf)
                connectionCount += 1

    if connectionCount == 1:
        info('opened ' + str(connectionCount) + ' connection.')
    else:
        info('opened ' + str(connectionCount) + ' connections.')
        
    # run
    #reactor.suggestThreadPoolSize(2)
    reactor.suggestThreadPoolSize(1)

    start_new_thread(reactor.run, (), { 'installSignalHandlers': False })
    #reactor.run(installSignalHandlers = False )

    #reactor.callLater(4, checkShutdownTwisted)

def checkShutdownTwisted():
    try:
        checkShutdown()
    except SystemExit:
        shutdownNewzSlurp()
    reactor.callLater(4, checkShutdownTwisted)
    
def shutdownNewzSlurp():
    """ """
    reactor.stop()

class NewzSlurperFactory(UsenetClientFactory):

    def __init__(self):
        # FIXME: we need to have different connections use different username/passwords. i
        # don't think we want multiple factories
        self.username = None
        self.password = None
        
        #self.totalStartTime = None
        self.totalReadBytes = 0
        self.totalDownloadedFiles = 0

        # FIXME: what is this
        self.lastChecks = {}

        self.deferredEmptyQueue = None

        # FIXME: idle the connection by: returning nothing, having a callLater handle an
        # idle call. whenever there's activity, we cancel the idle call and reschedule for
        # later
        self.clients = []

        # could maintain a map of protocol to log message. we only print when we have new
        # log messages from every connection
        self.scroller = NewzSlurpStatLog()

    def buildProtocol(self, addr):
        last = self.lastChecks.setdefault(addr, time.mktime(time.gmtime()) - (60 * 60 * 24 * 7))
        p = NewzSlurper(self.username, self.password)
        p.factory = self
        # FIXME: Is it safe to maintain the clients in this list?
        self.clients.append(p)
        self.scroller.size += 1
        return p

    def fetchNextNZBSegment(self):
        for p in self.clients:
            #p.fetchNextNZBSegment
            #debug('GO-' + p.getName())
            p.fetchNextNZBSegment()
            # HMM: Why can't the reactor do this
            #reactor.callLater(0, p.fetchNextNZBSegment)

class NewzSlurper(NNTPClient):

    nextId = 0 # Id Pool
    
    def __init__(self, username, password):
        """ """
        NNTPClient.__init__(self)
        self.username = username
        self.password = password
        self.id = self.getNextId()
        
        self.downloadStartTime = None
        self.readBytes = 0
        #self.filename = None

        self.activeGroups = []
        self.currentSegment = None

        self.myState = None

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
            self.gotauthInfoOk('%d %s' % (code, message))
        else:
            self.authInfoFailed('%d %s' % (code, message))
        self._endState()

    def gotauthInfoOk(self, message):
        "Override for notification when authInfo() action is successful"
        debug(self.getName() + ' AUTHINFO succeeded:' + message)

        self.fetchNextNZBSegment()

    def fetchNextNZBSegment(self):
        """ Pop nzb article from the queue, and attempt to retrieve it if it hasn't already been
        retrieved"""
        # FIXME: all segments are on the filesystem, but not assembled. needsDownload from
        # the queue returns true, so the file's segments all end up being iterated through
        # here. what will happen is we will skip them all accordingly, but we will never
        # assemble them/succesfully tryFinishNZB
        if self.currentSegment is None:
            try:
                nextSegment = Hellanzb.queue.get_nowait()
                while not nextSegment.needsDownload():
                    # FIXME: could do a segment.fileDone(). would add segment to
                    # nzbFile.finishedSegments list (if it isn't already
                    # there). needsDownload() could call this if it finds a match on the
                    # filesystem. easy way to maintain what/when is done all the time (i
                    # think)
                    debug(self.getName() + ' SKIPPING segment: ' + nextSegment.getTempFileName() + \
                          ' subject: ' + nextSegment.nzbFile.subject)
                    nextSegment = Hellanzb.queue.get_nowait()

                self.currentSegment = nextSegment
                if self.currentSegment.nzbFile.showFilename == None:
                    self.currentSegment.nzbFile.showFilename = os.path.basename(self.currentSegment.nzbFile.getDestination())
            except Empty:
                return

        # Change group
        for i in xrange(len(self.currentSegment.nzbFile.groups)):
            group = str(self.currentSegment.nzbFile.groups[i])

            # NOTE: we could get away with activating only one of the groups instead of
            # all
            if group not in self.activeGroups:
                debug(self.getName() + ' getting GROUP:' + group)
                self.fetchGroup(group)
                return

        debug(self.getName() + ' getting BODY: <' + self.currentSegment.messageId + '> ' + \
              self.currentSegment.getDestination())
        self.fetchBody(str(self.currentSegment.messageId))
        
    def fetchBody(self, index):
        """ """
        self.myState = 'body'
        start = time.time()
        #if self.factory.totalStartTime == None:
        #    self.factory.totalStartTime = start
        if self.currentSegment != None and self.currentSegment.nzbFile.downloadStartTime == None:
            self.currentSegment.nzbFile.downloadStartTime = start
        self.downloadStartTime = start
        
        self.factory.scroller.segments.append(self.currentSegment)
        NNTPClient.fetchBody(self, '<' + index + '>')

    def getName(self):
        """ Return the name of this NewzSlurper instance """
        return self.__class__.__name__ + '[' + str(self.id) + ']'

    def getNextId(self):
        id = NewzSlurper.nextId
        NewzSlurper.nextId += 1
        return id

    def gotBody(self, body):
        """ Queue the article body for decoding and continue fetching the next article """
        debug(self.getName() + ' got BODY: ' + ' <' + self.currentSegment.messageId + '> ' + \
              self.currentSegment.getDestination() + ' lines: ' + str(len(body)) + ' expected size: ' + \
              str(self.currentSegment.bytes))

        hi = """
        self.myState = None

        self.currentSegment.articleData = body
        self.deferSegmentDecode(self.currentSegment)

        self.currentSegment = None
        self.downloadStartTime = None
        self.readBytes = 0

        self.fetchNextNZBSegment()
        """
        self.processBodyAndContinue(body)
        
    def gotBodyFailed(self, err):
        """ Handle a failure of the BODY command. Ensure the failed segment gets a 0 byte file
        written to the filesystem when this occurs """
        debug(self.getName() + ' got BODY FAILED, error: ' + str(err) + ' for messageId: <' + \
              self.currentSegment.messageId + '> ' + self.currentSegment.getDestination() + \
              ' expected size: ' + str(self.currentSegment.bytes))
        
        self.processBodyAndContinue('')

    def processBodyAndContinue(self, articleData):
        """ Defer decoding of the specified articleData of the currentSegment, reset our state and
        continue fetching the next queued segment """
        self.myState = None

        self.factory.scroller.segments.remove(self.currentSegment)

        self.currentSegment.articleData = articleData
        self.deferSegmentDecode(self.currentSegment)

        self.currentSegment = None
        self.downloadStartTime = None
        self.readBytes = 0

        self.fetchNextNZBSegment()
        
    def deferSegmentDecode(self, segment):
        """ Decode the specified segment in a separate thread """
        reactor.callInThread(decode, segment)

    def gotGroup(self, group):
        """ """
        group = group[len(group) - 1]
        self.activeGroups.append(group)
        debug(str(self.id) + 'got GROUP: ' + group)
        # FIXME: where do i remove the group?

        self.fetchNextNZBSegment()

    def _stateBody(self, line):
        """ The normal _stateBody converts the list of lines downloaded to a string, we want to
        keep these lines in a list throughout life of the processing (should be more
        efficient) """
        if line != '.':
            self._newLine(line, 0)
        else:
            #self.gotBody('\n'.join(self._endState()))
            self.gotBody(self._endState())

    def _stateAntiIdle(self, line):
        debug('stateAntiIdle')
        if line != '.':
            self._newLine(line, 0)
        else:
            self.gotAntiIdle('\n'.join(self._endState()))

    def fetchAntiIdle(self):
        self.sendLine('HELP')
        self._newState(self._stateAntiIdle, self.getAntiIdleFailed)

    def gotAntiIdle(self, idle):
        debug('got idle')
        self.fetchNextNZBSegment()

    def getAntiIdleFailed(self, err):
        "Override for getAntiIdleFailed"
        debug('getAntiIdleFailed')
        
    def authInfoFailed(self, err):
        "Override for notification when authInfoFailed() action fails"
        error('AUTHINFO failed: ' + str(err))

    def connectionMade(self):
        NNTPClient.connectionMade(self)
        self.setStream()
        self.authInfo()

    def connectionLost(self, reason):
        NNTPClient.connectionLost(self) # calls self.factory.clientConnectionLost(self, reason)
        error(self.getName() + ' lost connection: ' + str(reason))

        self.activeGroups = []
        self.factory.clients.remove(self)
        self.scroller.size -= 1

    def lineReceived(self, line):
        # Update stats for current segment if we're issuing a BODY command
        if self.myState == 'body':
            now = time.time()
            self.updateByteCount(len(line))
            self.updateStats(now)
        
        NNTPClient.lineReceived(self, line)

    def updateByteCount(self, lineLen):
        self.readBytes += lineLen
        self.factory.totalReadBytes += lineLen
        if self.currentSegment != None:
            self.currentSegment.nzbFile.totalReadBytes += lineLen

    def updateStats(self, now):
        if self.currentSegment == None:
            return
        
        oldPercentage = self.currentSegment.nzbFile.downloadPercentage
        self.currentSegment.nzbFile.downloadPercentage = min(100,
                                                             int(float(self.currentSegment.nzbFile.totalReadBytes) /
                                                                 max(1, self.currentSegment.nzbFile.totalBytes) * 100))

        if self.currentSegment.nzbFile.downloadPercentage > oldPercentage:
            elapsed = max(0.1, now - self.currentSegment.nzbFile.downloadStartTime)
            #speed = self.currentSegment.nzbFile.totalReadBytes / elapsed / 1024.0
            self.currentSegment.nzbFile.speed = self.currentSegment.nzbFile.totalReadBytes / elapsed / 1024.0
            #scroll('\r* Downloading %s - %2d%% @ %.1fKB/s' % (truncate(self.filename),
            #                                                 self.currentSegment.nzbFile.downloadPercentage,
            #                                                 speed))
        self.factory.scroller.updateLog()

class NewzSlurpStatLog:
    def __init__(self):
        self.size = 0
        self.segments = []
        self.currentLog = None

        self.wait = 0
        self.delay = 70
        
    def updateLog(self):
        """ Log ticker """
        # Delay logging so we don't over-log
        self.wait += 1
        if self.wait < self.delay:
            return
        else:
            self.wait = 0

        logNow = False
        currentLog = self.currentLog
        if self.currentLog != None:
            # Kill previous lines
            self.currentLog = '\r\033[' + str(self.size) + 'A'
        else:
            # unless we have just began logging. explicitly log the first message
            logNow = True
            self.currentLog = ''

        # HACKY:
        # sort by filename, then blink out connections download segments for the same
        # file. only show the file download totals
        sortedSegments = self.segments[:]
        sortedSegments.sort(lambda x, y : cmp(x.nzbFile.showFilename, y.nzbFile.showFilename))
        
        lastSegment = None
        totalSpeed = 0
        i = 0
        for segment in sortedSegments:
            i += 1
            if lastSegment != None and lastSegment.nzbFile == segment.nzbFile:
                self.currentLog += '\033[34m[\033[39m%d\033[34m]\033[39m Downloading %s\033[K' % \
                    (i, truncate(segment.nzbFile.showFilename, length = 100, reverse = True))
            else:
                self.currentLog += '\033[34m[\033[39m%d\033[34m]\033[39m Downloading %s - %2d%% @ %.1fKB/s\033[K' % \
                    (i, truncate(segment.nzbFile.showFilename, length = 100, reverse = True),
                     segment.nzbFile.downloadPercentage, segment.nzbFile.speed)
                totalSpeed += segment.nzbFile.speed
                
            self.currentLog += '\n\r'

            lastSegment = segment
                
        for fill in range(i + 1, self.size + 1):
            self.currentLog += '\033[34m[\033[39m%d\033[34m]\033[39m\033[K' % (fill)
            self.currentLog += '\n\r'

        self.currentLog += '\033[34m[\033[39mTotal\033[34m]\033[39m %.1fKB/s, %d MB queued \033[K' % \
            (totalSpeed, Hellanzb.queue.totalQueuedBytes / 1024 / 1024)

        if logNow or self.currentLog != currentLog:
            scroll(self.currentLog)
            
        
