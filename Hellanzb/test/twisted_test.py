#!/usr/bin/env python
import sys
from twisted.internet import reactor
from twisted.news.news import UsenetClientFactory
from twisted.protocols.nntp import NNTPClient, extractCode
from twisted_test_util import NZBParser, parseNZB
USERNAME = 'CHANGE'
PASSWORD = 'ME'

groups = None
queue = None

def main():
    global groups, queue
    
    # parse something into queue
    groups, queue = parseNZB(sys.argv[1])
    print 'got: ' + str(queue)
    
    nsf = NZBLeecherFactory(USERNAME, PASSWORD)
    for i in range(10):
        reactor.connectTCP('unlimited.newshosting.com', 9000, nsf)

    reactor.run()

class NZBLeecherFactory(UsenetClientFactory):

    def __init__(self, username, password):
        self.username = username
        self.password = password

        # FIXME: don't think these are actually used
        #self.totalStartTime = None
        self.totalReadBytes = 0
        self.totalDownloadedFiles = 0

        # statistics for the current session (sessions end when we stop downloading on all
        # ports). used for the more accurate total speeds shown in the UI
        self.sessionReadBytes = 0
        self.sessionSpeed = 0
        self.sessionStartTime = None
        
        # FIXME: idle the connection by: returning nothing, having a callLater handle an
        # idle call. whenever there's activity, we cancel the idle call and reschedule for
        # later
        self.clients = []

        from sets import Set
        self.activeClients = Set()

        # FIXME: factories need to know when we're idle (done downloading). then it can
        # turn the auto reconnect maxDelay up back to the default value (3600)
        #self.maxDelay = 5
        # turning this off for now -- but it might be useful for when usenet servers start
        # shitting themselves

    def buildProtocol(self, addr):
        p = NZBLeecher(self.username, self.password)
        p.factory = self
        
        # FIXME: Is it safe to maintain the clients in this list? no other twisted
        # examples do this. no twisted base factory classes seem to maintain this list
        self.clients.append(p)

        return p

    def fetchNextNZBSegment(self):
        for p in self.clients:
            reactor.callLater(0, p.fetchNextNZBSegment)

class NZBLeecher(NNTPClient):
    """ Extends twisted NNTPClient to download NZB segments from the queue, until the queue
    contents are exhausted """

    nextId = 0 # Id Pool
    
    def __init__(self, username, password):
        """ """
        NNTPClient.__init__(self)
        self.username = username
        self.password = password
        self.id = self.getNextId()

        # successful GROUP commands during this session
        self.activeGroups = []

        self.activatedGroups = False

        # current article (<segment>) we're dealing with
        self.currentSegment = None

        # staistics/for the ui
        self.downloadStartTime = None
        self.readBytes = 0

        self.myState = None

        self.isLoggedIn = False
        self.setReaderAfterLogin = False
            
        # How long we must be idle for in seconds until we send an anti idle request
        self.timeOut = 7 * 60

        # I'm not sure why this needs to be raised from the default value -- but we can
        # definitely get longer lines than LineReceiver expects
        self.MAX_LENGTH = 262144

        # Lameness -- these are from LineReceiver. Needed for the imported Twisted 2.0
        # dataReceieved
        self.line_mode = 1
        self.__buffer = ''
        self.delimiter = '\r\n'
        self.paused = False

        self.lastoffset = 0

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
        """ Override for notification when authInfo() action is successful """
        self.isLoggedIn = True

        if self.setReaderAfterLogin:
            self.setReader()
        else:
            reactor.callLater(0, self.fetchNextNZBSegment)
            #self.fetchNextNZBSegment()

    def authInfoFailed(self, err):
        "Override for notification when authInfoFailed() action fails"
        pass

    def connectionMade(self):
        NNTPClient.connectionMade(self)

        # 'mode reader' is sometimes necessary to enable 'reader' mode.
        # However, the order in which 'mode reader' and 'authinfo' need to
        # arrive differs between some NNTP servers. Try to send
        # 'mode reader', and if it fails with an authorization failed
        # error, try again after sending authinfo.
        self.setReader()

    def connectionLost(self, reason):
        NNTPClient.connectionLost(self) # calls self.factory.clientConnectionLost(self, reason)
        
        self.activeGroups = []
        self.factory.clients.remove(self)
        #Hellanzb.scroller.size -= 1
        self.isLoggedIn = False
        self.setReaderAfterLogin = False

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
        if self.setReaderAfterLogin:
            reactor.callLater(0, self.fetchNextNZBSegment)
        else:
            self.authInfo()
        
    def setReaderFailed(self, err):
        """ If the MODE READER failed prior to login, this server probably only accepts it after
        login """
        if not self.isLoggedIn:
            self.setReaderAfterLogin = True
            self.authInfo()
        
    def fetchNextNZBSegment(self):
        """ Pop nzb article from the queue, and attempt to retrieve it if it hasn't already been
        retrieved"""
        if self.currentSegment is None:
            try:
                self.currentSegment = queue.pop(0)

            except IndexError:
                return

        # Change group
        if not self.activeGroups:
            print self.getName() + ' activating groups.. '
            for group in groups:
        #for i in xrange(len(self.currentSegment.nzbFile.groups)):
        #    group = str(self.currentSegment.nzbFile.groups[i])

            # NOTE: we could get away with activating only one of the groups instead of
            # all
                if group not in self.activeGroups:
                    self.fetchGroup(group)
                    return

        reactor.callLater(0, self.fetchBody, str(self.currentSegment))
        
    def fetchBody(self, index):
        """ """
        #self.currentSegment.nzbFile.downloadStartTime = start
        #self.downloadStartTime = start
        
        #Hellanzb.scroller.segments.append(self.currentSegment)

        reactor.callLater(0, NNTPClient.fetchBody, self, '<' + index + '>')
        #NNTPClient.fetchBody(self, '<' + index + '>')

    def getName(self):
        """ Return the name of this NZBLeecher instance """
        return self.__class__.__name__ + '[' + str(self.id) + ']'

    def getNextId(self):
        id = NZBLeecher.nextId
        NZBLeecher.nextId += 1
        return id

    def gotBody(self, body):
        """ Queue the article body for decoding and continue fetching the next article """
        #reactor.callLater(0, self.processBodyAndContinue, body)
        self.processBodyAndContinue(body)
        
    def gotBodyFailed(self, err):
        """ Handle a failure of the BODY command. Ensure the failed segment gets a 0 byte file
        written to the filesystem when this occurs """
        code = extractCode(err)
        if code is not None and code in ('423', '430'):
            # FIXME: show filename and segment number
            #Hellanzb.scroller.prefixScroll(self.currentSegment.showFilename + ' Article is missing!')
            #Hellanzb.scroller.updateLog(logNow = True)
            pass
        
        #reactor.callLater(0, self.processBodyAndContinue, '')
        self.processBodyAndContinue('')

    def processBodyAndContinue(self, articleData):
        """ Defer decoding of the specified articleData of the currentSegment, reset our state and
        continue fetching the next queued segment """
        self.myState = None

        #Hellanzb.scroller.segments.remove(self.currentSegment)

        #del articleData
        #self.currentSegment.articleData = articleData
        #self.deferSegmentDecode(self.currentSegment)

        self.currentSegment = None
        self.downloadStartTime = None
        self.readBytes = 0
 
        self.lastoffset = 0

        reactor.callLater(0, self.fetchNextNZBSegment)
        #self.fetchNextNZBSegment()
        
    def deferSegmentDecode(self, segment):
        """ Decode the specified segment in a separate thread """
        #reactor.callInThread(decode, segment)
        pass

    def gotGroup(self, group):
        """ """
        group = group[len(group) - 1]
        self.activeGroups.append(group)

        reactor.callLater(0, self.fetchNextNZBSegment)
        #self.fetchNextNZBSegment()

    def _stateBody(self, line):
        """ The normal _stateBody converts the list of lines downloaded to a string, we want to
        keep these lines in a list throughout life of the processing (should be more
        efficient) """
        if line != '.':
            #self._newLine(line, 0)
            self._inputBuffers[0].append(line)
        else:
            #self.gotBody('\n'.join(self._endState()))
            #self.gotBody(self._endState())
            reactor.callFromThread(self.gotBody, self._endState())

    def lineReceived(self, line):
        # Update stats for current segment if we're issuing a BODY command
        #if self.myState == 'BODY':
        #    now = time.time()
        #    self.updateByteCount(len(line))
            #self.updateStats(now)
            
        NNTPClient.lineReceived(self, line)

    def updateByteCount(self, lineLen):
        self.readBytes += lineLen
        self.factory.totalReadBytes += lineLen
        self.factory.sessionReadBytes += lineLen
        if self.currentSegment != None:
            self.currentSegment.nzbFile.totalReadBytes += lineLen

    def updateStats(self, now):
        if self.currentSegment == None:
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
            self.factory.sessionSpeed = self.factory.sessionReadBytes / elapsedSession / 1024.0
            
        #Hellanzb.scroller.updateLog()
    
if __name__ == '__main__':
    main()
