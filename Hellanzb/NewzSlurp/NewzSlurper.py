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
    # FIXME:
    Hellanzb.queue = NZBQueue()

    # create factory protocol and application
    Hellanzb.nsf = NewzSlurperFactory()

    Hellanzb.nzbfileDone = Condition()

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

    def buildProtocol(self, addr):
        last = self.lastChecks.setdefault(addr, time.mktime(time.gmtime()) - (60 * 60 * 24 * 7))
        p = NewzSlurper(self.username, self.password)
        p.factory = self
        return p

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
        self.filename = None

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

    def fetchNextNZBSegment(self, arg1=None, arg2=None):
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
                self.filename = os.path.basename(self.currentSegment.nzbFile.getDestination())
            except Empty:
                from Hellanzb.Util import getStack
                debug(self.getName() + ' DONE downloading')
                #debug(self.getName() + ' DONE downloading' + getStack())
                ##time.sleep(10)
                #return
                #debug('b')
                # Can other connections use this same deferred? just add themselves as
                # callbacks.
                #if self.factory.deferredEmptyQueue == None:
                #    self.factory.deferredEmptyQueue = flow.Deferred(Threaded(doh(self)))
                ##d = flow.Deferred(Threaded(doh(self)))
                #debug('a')
                ##d.addCallback(self.fetchNextNZBSegment)
                if self.factory.deferredEmptyQueue == None:
                    debug('NEW defQUEUE!')
                    self.factory.deferredEmptyQueue = wtf()
                    #self.factory.deferredEmptyQueue = flow.Deferred(Threaded(doh2(self)))
                else:
                    self.factory.deferredEmptyQueue.deferredFinishedLock.acquire()
                    if self.factory.deferredEmptyQueue.deferredFinished == True:
                        debug('NEW defQUEUE!')
                        self.factory.deferredEmptyQueue.deferredFinishedLock.release()
                        self.factory.deferredEmptyQueue = wtf()
                    else:
                        debug('NOT FINISHED!')
                        self.factory.deferredEmptyQueue.deferredFinishedLock.release()
                    pass
                        
                ###self.factory.deferredEmptyQueue.addCallback(self, self.fetchNextNZBSegment)
                self.factory.deferredEmptyQueue.addCallback(self, callback)
                
                #self.factory.deferredEmptyQueue.addCallback(self.fetchNextNZBSegment, callbackArgs=(self))
                debug('gonna add callback' + self.getName())
                #self.factory.deferredEmptyQueue.addCallback(self.fetchNextNZBSegment)
                debug('ADDED CALLBACK!')
                #return self.factory.deferredEmptyQueue.d
                return self.factory.deferredEmptyQueue
                #return d
                #return
                #return                

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

        self.myState = None
        self.currentSegment.articleData = body
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
        
    def gotBodyFailed(self, err):
        # FIXME:
        pass

    def lineReceived(self, line):
        # Update stats for current segment if we're issuing a BODY command
        #if self._state[0] == self._stateBody:
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
            speed = self.currentSegment.nzbFile.totalReadBytes / elapsed / 1024.0
            scroll('\r* Downloading %s - %2d%% @ %.1fKB/s' % (truncate(self.filename),
                                                             self.currentSegment.nzbFile.downloadPercentage,
                                                             speed))


class FunkyAssMultiTwistedConnectionSingletonDeferred:
    def __init__(self):
        self.protocolFifo = []
        self.protocolFifoLock = Lock()
        self.d = flow.Deferred(Threaded(doh(self)))

        self.deferredFinished = False
        self.deferredFinishedLock = Lock()

    def addCallback(self, protocol, protocolFunction):
        debug('trying to add callback for p: ' + protocol.getName())
        self.d.addCallback(protocolFunction)
        self.protocolFifoLock.acquire()
        self.protocolFifo.append(protocol)
        self.protocolFifoLock.release()

    def pop(self):
        p = None
        self.protocolFifoLock.acquire()
        if len(self.protocolFifo) > 0:
            p = self.protocolFifo[0]
            self.protocolFifo = self.protocolFifo[1:]
            debug('POPPING: ' + p.getName())
        self.protocolFifoLock.release()
        return p
            
wtf = FunkyAssMultiTwistedConnectionSingletonDeferred
def doh(wtf):
    time.sleep(1)
    try:
        #nextSegment = Hellanzb.queue.get(block = True, timeout = 60 * 5)
        debug('waiting')
        nextSegment = Hellanzb.queue.get(block = True, timeout = 5)
        debug('waited')
        while not nextSegment.needsDownload():
            nextSegment = Hellanzb.queue.get_nowait()

        wtf.deferredFinishedLock.acquire()
        debug('DEF FINISHED!')
        wtf.deferredFinished = True
        wtf.deferredFinishedLock.release()
        while 1:
            debug('got new, popping')
            p = wtf.pop()
            if p == None:
                debug('got new, done popping')
                raise StopIteration()
            p.currentSegment = nextSegment
            debug('GETTING DEST..')
            p.filename = os.path.basename(p.currentSegment.nzbFile.getDestination())
            debug('got new, process/yielding')
        #object.currentSegment = nextSegment
        #object.filename = os.path.basename(object.currentSegment.nzbFile.getDestination())
        #yield wtf.pop()
            yield p
    except Empty:
        debug('EMPTY NZBQUEUE')
        wtf.deferredFinishedLock.acquire()
        debug('DEF FINISHED!')
        wtf.deferredFinished = True
        wtf.deferredFinishedLock.release()
        while 1:
            debug('FOUND NOTHING, (RESET)')
            p = wtf.pop()
            if p == None:
                raise StopIteration()
            # FIXME: Send anti idle here (or in callback)
            # reactor.callLater(0, p.fetchAntiIdle)
        #yield object
        #yield wtf.pop()
            yield p
    #time.sleep(3)

# We end up adding a callback (which can trigger running callbacks) in the middle of the
# defer running a callback -- endless loop
def doh2(object):
    try:
        #nextSegment = Hellanzb.queue.get(block = True, timeout = 60 * 5)
        nextSegment = Hellanzb.queue.get(block = True, timeout = 5)
        while not nextSegment.needsDownload():
            nextSegment = Hellanzb.queue.get_nowait()
        object.currentSegment = nextSegment
        object.filename = os.path.basename(object.currentSegment.nzbFile.getDestination())
        debug('YIELDING object w/ next: ' + object.getName())
        #yield object
        yield ''
    except Empty:
        # Send anti idle here
        debug('YIELDING object w/out next: ' + object.getName())
        #yield object
        yield '2'
    #time.sleep(3)

def callback(callBackList):
    debug('cback' + str(callBackList))
    for i in callBackList:
        debug('calling back ho: ' + i.getName())
        reactor.callLater(0, i.fetchNextNZBSegment)
