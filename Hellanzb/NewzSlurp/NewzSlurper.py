"""
"""
# <DEBUGGING>
import sys
sys.path.append('/home/pjenvey/src/hellanzb-asynchella')
# </DEBUGGING>

import sys, time
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
PASSWORD = 'FUCKING_GOD_DAMMIT_TO_HELL'

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

    def buildProtocol(self, addr):
        """ """
        last = self.lastChecks.setdefault(addr, time.mktime(time.gmtime()) - (60 * 60 * 24 * 7))
        #p = nntp.UsenetClientProtocol(self.groups, last, self.storage)
        auth = {'username':USERNAME, 'password':PASSWORD}
        p = NewzSlurper(auth, {})
        p.factory = self
        return p

class NewzSlurper(NNTPClient):

    nextId = 0 # Id Pool
    
    def __init__(self, auth, stat):
        """ """
        NNTPClient.__init__(self)
        self.auth = auth
        self.stat = stat
        self.group = None
        self.id = self.getNextId()
        #self.stat['pending'][self.id] = True
        self.lineCount = 0 # FIXME:

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
            except Empty:
                debug('DONE!')
                time.sleep(10)
                return

        for i in xrange(len(self.currentSegment.nzbFile.groups)):
            # FIXME: group here is a type unicode class. fetchGroup requires str
            # objects. These should be str()'d during the nzbFile instantiation
            group = str(self.currentSegment.nzbFile.groups[i])
            debug('NewzSlurper[' + str(self.id) + ']' + ' fetching group:' + group)
            debug('group 4 segment: ' + self.currentSegment.getTempFileName() + ' subject: ' + self.currentSegment.nzbFile.subject)

            # FIXME: should only activate one of the groups
            if group not in self.activeGroups:
                self.fetchGroup(group)
                return
            
        # queue.pendingGroups, queue.activeGroups, def fetchPendingGroups(): # function
        # calls a locked queue function that returns it new groups
        debug('NewzSlurper[' + str(self.id) + ']' + ' fetching article: ' + \
              #self.currentSegment.getDestination() + ' (' + self.currentSegment.messageId + ')')
              self.currentSegment.getDestination() + ' (' + self.currentSegment.nzbFile.subject + ')')
        debug(str(self.id) + 'going to fetch article: ' + str(self.currentSegment.messageId))
        self.fetchArticle(str(self.currentSegment.messageId))
        
    def fetchArticle(self, index):
        """ """
        NNTPClient.fetchArticle(self, '<' + index + '>')

    def gotArticle(self, article):
        """ Decode the article """
        debug('NewzSlurper[' + str(self.id) + ']' + ' got article: ' + self.currentSegment.getDestination() + \
             ' (' + self.currentSegment.messageId + ')' + ' size: ' + str(len(article)) + ' expected size: ' + \
             str(self.currentSegment.bytes))

        #debug('aclass: ' + str(article.__class__))
        #debug('gotArticle: ' + article)
        debug('article class: ' + str(article.__class__))
        self.currentSegment.articleData = article
        self.deferSegmentDecode(self.currentSegment)
        self.currentSegment = None

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
        self.lineCount += 1
        if self.lineCount % 100 == 0:
            print '.',
        sys.stdout.flush()
        NNTPClient.lineReceived(self, line)

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
    
