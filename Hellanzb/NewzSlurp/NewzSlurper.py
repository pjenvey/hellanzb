"""
"""
# <DEBUGGING>
import sys
sys.path.append('/home/pjenvey/src/hellanzb-asynchella')
# </DEBUGGING>

import os, sys, time
from threading import Condition
from twisted.internet import reactor
from twisted.news.news import UsenetClientFactory
from twisted.protocols.nntp import NNTPClient
from twisted.python import log
from random import randint
from Hellanzb.Logging import *
from Hellanzb.NewzSlurp.ArticleDecoder import decode
from Queue import Empty

__id__ = '$Id$'

USERNAME = 'pjenvey'
PASSWORD = 'IF_A_SPERM_GETS_WASTED_GOD_GETS_REAL_IRATE'

# FIXME:
# problem: when resuming, we dont have our real name yet (just the temp name). you need
# the real name before you can determine what is on the filesystem/whats left to d/l

# SOLUTION:
# the needsDownload() could do this, if it fails to find the filename or segment filename
# on the FS, and we only have a temporary name, for every file in the directory, if the
# filename matches a substr in our subject, we found it. segment we can look for the
# correct .segment prefix.
# This check should be done in NewzSlurper to be correct. but could cause small
# delays. could we put this in the NZBQueue.parseNZB instead?

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
    for i in range(6):
    #for i in range(1):
        # connect factory to this host and port
        reactor.connectTCP("unlimited.newshosting.com", 9000, Hellanzb.nsf)
        #reactor.connectTCP("unlimited.newshosting.com", 8000, Hellanzb.nsf)

    # run
    #reactor.suggestThreadPoolSize(3)
    reactor.suggestThreadPoolSize(1)
    from thread import start_new_thread
    #reactor.run(installSignalHandlers = False)
    start_new_thread(reactor.run, (), { 'installSignalHandlers': False })
    
def shutdownNewzSlurp():
    """ """
    # FIXME:?
    pass

class NewzSlurperFactory(UsenetClientFactory):

    def __init__(self):
        """ """
        # FIXME: what is this
        self.lastChecks = {}
        #self.totalStartTime = None
        self.totalReadBytes = 0
        self.totalDownloadedFiles = 0

    def buildProtocol(self, addr):
        """ """
        last = self.lastChecks.setdefault(addr, time.mktime(time.gmtime()) - (60 * 60 * 24 * 7))
        #p = nntp.UsenetClientProtocol(self.groups, last, self.storage)
        auth = {'username':USERNAME, 'password':PASSWORD}
        p = NewzSlurper(auth, {}, self)
        p.factory = self
        return p

class NewzSlurper(NNTPClient):

    nextId = 0 # Id Pool
    
    def __init__(self, auth, stat, factory):
        """ """
        NNTPClient.__init__(self)
        self.auth = auth
        self.stat = stat
        self.factory = factory
        self.group = None
        self.id = self.getNextId()
        #self.stat['pending'][self.id] = True
        
        #self.lineCount = 0 # FIXME:
        self.downloadStartTime = None
        self.readBytes = 0
        #self.readPercentage = 0
        self.filename = None

        self.activatedGroup = False
        self.activeGroups = []
        self.currentSegment = None

    def authInfo(self):
        """ """
        self.sendLine('AUTHINFO USER ' + self.auth['username'])
        self._newState(None, self.authInfoFailed, self._authInfoUserResponse)

    def _authInfoUserResponse(self, (code, message)):
        """ """
        if code == 381:
            self.sendLine('AUTHINFO PASS ' + self.auth['password'])
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
        print 'AUTHINFO succeeded:' + message

        self.fetchNextNZBSegment()
        
        #self.fetchBody
        # Grab pending messages
        #self._newState(None, self.authInfoFailed, self._authInfoPassResponse)

        ## uh??
        ####self._newState(self.gotIdle,None)
        #del self.stat['pending'][self.id]
#        self.fetchIdle()

    def fetchNextNZBSegment(self):
        """ Pop nzb article from the queue, and attempt to retrieve it if it hasn't already been
        retrieved"""
        #nzbSegment = Hellanzb.queue.get_nowait()
        if self.currentSegment is None:
            try:
                # FIXME: act accordingly when the queue is empty
                nextSegment = Hellanzb.queue.get_nowait()
                while not nextSegment.needsDownload():
                    #debug('SKIPPING segment: ' + nextSegment.getTempFileName())
                    debug('SKIPPING segment: ' + nextSegment.getTempFileName() + ' subject: ' + nextSegment.nzbFile.subject)
                    nextSegment = Hellanzb.queue.get_nowait()
                self.currentSegment = nextSegment
                self.filename = os.path.basename(self.currentSegment.nzbFile.getDestination())
            except Empty:
                debug('DONE!')
                time.sleep(10)
                return

        for i in xrange(len(self.currentSegment.nzbFile.groups)):
            # FIXME: group here is a type unicode class. fetchGroup requires str
            # objects. These should be str()'d during the nzbFile instantiation
            group = str(self.currentSegment.nzbFile.groups[i])
            debug('NewzSlurper[' + str(self.id) + ']' + ' fetching group:' + group)
            #debug('group 4 segment: ' + self.currentSegment.getTempFileName() + ' subject: ' + self.currentSegment.nzbFile.subject)

            # FIXME: should only activate one of the groups
            if group not in self.activeGroups:
                self.fetchGroup(group)
                return
            
        # queue.pendingGroups, queue.activeGroups, def fetchPendingGroups(): # function
        # calls a locked queue function that returns it new groups
        debug('NewzSlurper[' + str(self.id) + ']' + ' fetching article: ' + \
              #self.currentSegment.getDestination() + ' (' + self.currentSegment.messageId + ')')
              self.currentSegment.getDestination() + ' (' + self.currentSegment.nzbFile.subject + ')')
        debug('NewzSlurper[' + str(self.id) + '] going to fetch article: ' + \
              str(self.currentSegment.messageId))
        self.fetchArticle(str(self.currentSegment.messageId))
        
    def fetchArticle(self, index):
        """ """
        start = time.time()
        #if self.factory.totalStartTime == None:
        #    self.factory.totalStartTime = start
        if self.currentSegment != None and self.currentSegment.nzbFile.downloadStartTime == None:
            self.currentSegment.nzbFile.downloadStartTime = start
        self.downloadStartTime = start
        NNTPClient.fetchArticle(self, '<' + index + '>')

    def gotArticle(self, article):
        """ Decode the article """
        debug('NewzSlurper[' + str(self.id) + ']' + ' got article: ' + self.currentSegment.getDestination() + \
             ' (' + self.currentSegment.messageId + ')' + ' size: ' + str(len(article)) + ' expected size: ' + \
             str(self.currentSegment.bytes))

        self.currentSegment.articleData = article
        self.deferSegmentDecode(self.currentSegment)
        self.currentSegment = None

        #self.lineCount = 0
        self.downloadStartTime = None
        self.readBytes = 0
        #self.readPercentage = 0

        # FIXME: endstate,newstate?
        #from time import sleep
        #sleep(1)
        self.fetchNextNZBSegment()

    def deferSegmentDecode(self, segment):
        """ """
        reactor.callInThread(decode, segment)

    def gotGroup(self, group):
        """ """
        debug('gotGroup!')
        # FIXME: wtf does fetchGroup tuple group?
        group = group[len(group) - 1]
        debug(str(self.id) + 'got group: ' + group)
        self.activeGroups.append(group)
        self.activatedGroup = True
        # FIXME: where do i remove the group?

        self.fetchNextNZBSegment()

    def _stateArticle(self, line):
        """ The normal _stateArticle converts the list of lines downloaded to a string, we want to
        keep these lines in a list throughout life of the processing (should be more
        efficient) """
        if line != '.':
            self._newLine(line, 0)
        else:
            #self.gotArticle('\n'.join(self._endState()))
            self.gotArticle(self._endState())

    def _stateIdle(self):
        print 'the group is: %s' % stat['group']

        if self.group != stat['group']:
            self._endState()
            self.fetchGroup(stat['group'])

    def getIdleFailed(self, err):
        "Override for getIdleFailed"
        print 'uhhh, something bad happened....'
        
    def fetchIdle(self):
        self._newState(self._stateIdle, self.getIdleFailed)

    def authInfoFailed(self, err):
        "Override for notification when authInfoFailed() action fails"
        error('AUTHINFO failed: ' + str(err))

    def connectionMade(self):
        NNTPClient.connectionMade(self)
        self.setStream()
        self.authInfo()

    def gotHead(self, head):
        print 'huh huh i got head'
        print 'head: ' + head

    def getHeadFailed(self, err):
        print 'didn\'t get any head =['
        print 'err: ' + err

    def gotBody(self, body):
        print 'got body'
        # FIXME: decode body. or do it during the lineReceieved()?

    def gotBodyFailed(self, err):
        print 'didn\'t get body'
        print 'err: ' + err

    def lineReceived(self, line):
        #self.lineCount += 1

        lineLen = len(line)
        self.readBytes += lineLen
        self.factory.totalReadBytes += lineLen
        if self.currentSegment != None:
            self.currentSegment.nzbFile.totalReadBytes += lineLen

        self.updatePercentage()
        
        #if self.lineCount % 100 == 0:
        #    print '.',
        #sys.stdout.flush()
        NNTPClient.lineReceived(self, line)

    def updatePercentage(self):
        if self.currentSegment == None:
            return

        if self.filename != 'hellanzb-tmp-GhettoGaggers.com_-_Alika.file0003':
            return
        
        #oldPercentage = self.readPercentage
        oldPercentage = self.currentSegment.nzbFile.downloadPercentage
        #self.currentSegment.nzbFile.downloadPercentage = min(100, int(float(self.readBytes) /
        #max(1, self.currentSegment.bytes) * 100))
        self.currentSegment.nzbFile.downloadPercentage = min(100,
                                                             int(float(self.currentSegment.nzbFile.totalReadBytes) /
                                                                 max(1, self.currentSegment.nzbFile.totalBytes) * 100))

        #if self.readPercentage > oldPercentage:
        if self.currentSegment.nzbFile.downloadPercentage > oldPercentage:
            #elapsed = max(0.1, time.time() - self.downloadStartTime)
            elapsed = max(0.1, time.time() - self.currentSegment.nzbFile.downloadStartTime)
            speed = self.currentSegment.nzbFile.totalReadBytes / elapsed / 1024.0
            #print '\r* Decoding %s - %2d%% @ %.1fKB/s' % (truncate(filename), percent, speed),
            #print '\r* Downloading %s - %2d%% @ %.1fKB/s' % (truncate(self.filename),
            #                                                 self.currentSegment.nzbFile.downloadPercentage,
            #                                                 speed),
            #debug('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! ' + str(oldPercentage) + ' : ' + str(self.readPercentage))
            #scroll('\r* f: ' + truncate(self.filename) + ' r: ' + str(self.currentSegment.nzbFile.downloadPercentage) + ' s: ' + str(speed))
            #sys.stderr.write('\r* f: ' + truncate(self.filename) + ' r: ' + str(self.currentSegment.nzbFile.downloadPercentage) + ' s: ' + str(speed))
            #sys.stdout.flush()

            #scroll('\r* f: ' + truncate(self.filename) + ' r: ' + str(self.currentSegment.nzbFile.downloadPercentage) + ' s: ' + str(speed))
            #debug('\r* f: ' + truncate(self.filename) + ' r: ' + str(self.currentSegment.nzbFile.downloadPercentage) + ' s: ' + str(speed))

            scroll('\r* Downloading %s - %2d%% @ %.1fKB/s' % (truncate(self.filename),
                                                             self.currentSegment.nzbFile.downloadPercentage,
                                                             speed))


    def gotIdle(self, idle):
        print 'idling'
        self.fetchIdle()

    def getNextId(self):
        id = NewzSlurper.nextId
        NewzSlurper.nextId += 1
        return id

if __name__ == '__main__':
    initNewzSlurp()
    #from Hellanzb.NewzSlurp.NZBUtil import NZBQueue
    if len(sys.argv) > 1:
        info('Loading: ' + sys.argv[1])
        Hellanzb.queue.parseNZB(sys.argv[1])
        startNewzSlurp()
    
