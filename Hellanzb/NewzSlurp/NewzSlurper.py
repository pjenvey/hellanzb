"""
"""
import sys, time
from twisted.internet import reactor
from twisted.news.news import UsenetClientFactory
from twisted.protocols.nntp import NNTPClient
from twisted.python import log
from random import randint
from Hellanzb.Logging import *

__id__ = '$Id$'

class NewzSlurperFactory(UsenetClientFactory):

    def __init__(self):
        """ """
        self.lastChecks = {}

    def buildProtocol(self, addr):
        """ """
        last = self.lastChecks.setdefault(addr, time.mktime(time.gmtime()) - (60 * 60 * 24 * 7))
        #p = nntp.UsenetClientProtocol(self.groups, last, self.storage)
        p = NewzSlurper()
        p.factory = self
        return p

class NewzSlurper(NNTPClient):
    
    def __init__(self,auth,stat):
        """ """
        NNTPClient.__init__(self)
        self.auth = auth
        self.stat = stat
        self.id = reduce(lambda x,y:str(x)+str(y), [randint(10,99) for x in range(14)])
        self.stat['pending'][self.id] = True
        self.lineCount = 0 # FIXME:

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
            self.gotauthInfoOk(self._endState())
        else:
            self.authInfoFailed(self._endState())

    def gotauthInfoOk(self, message):
        "Override for notification when authInfo() action is successful"
        print 'sweet bitch we logged in'
        del self.stat['pending'][self.id]

    def _stateIdle(self, line):
        if line != '.':
            self._newLine(filter(None, line.strip().split()), 0)
        else:
            self.gotIdle(self._endState())

    def getIdleFailed(self, error):
        "Override for getIdleFailed"
        
    def fetchIdle(self):
        self.sendLine('HELP')
        self._newState(self._stateIdle, self.getIdleFailed)

    def authInfoFailed(self, error):
        "Override for notification when authInfoFailed() action fails"
        print 'we didn\'t log in wtfs??: ' + str(error)

    def connectionMade(self):
        NNTPClient.connectionMade(self)
        self.authInfo()

    def gotHead(self, head):
        print 'huh huh i got head'
        print 'head: ' + head

    def getHeadFailed(self, error):
        print 'didn\'t get any head =['
        print 'error: ' + error

    def gotBody(self, body):
        print 'got body'
        # FIXME: decode body. or do it during the lineReceieved()?

    def gotBodyFailed(self, error):
        print 'didn\'t get body'
        print 'error: ' + error

    def lineReceived(self, line):
        self.lineCount += 1
        if self.lineCount % 100 == 0:
            print '.',
        sys.stdout.flush()
        NNTPClient.lineReceived(self, line)

    def gotIdle(self, idle):
        print 'idling'
        self.fetchIdle()
        


if __name__ == '__main__':
    # initialize logging
    log.startLogging(sys.stdout)

    # create factory protocol and application
    nsf = NewzSlurperFactory()

    # connect factory to this host and port
    reactor.connectTCP("unlimited.newshosting.com", 9000, nsf)

    # run
    reactor.run()
