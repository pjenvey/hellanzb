import unittest, Hellanzb
from time import time
from Hellanzb.test import HellanzbTestCase
from Hellanzb.Logging import debug, info
from Hellanzb.Util import PriorityQueue
from Hellanzb.NZBLeecher.NZBModel import NZBQueue

class PriorityQueueTestCase(HellanzbTestCase):

    def dtestBenchmark(self):
        """ Benchmark putting garbage into a normal priority queue """

        smallItemCount = 1000
        largeItemCount = 40000

        pq = PriorityQueue()

        info('Small:')
        self.doPut(pq, smallItemCount)
        info('Large:')
        self.doPut(pq, largeItemCount)

        #info('NZBQueue')

    def dtestNZBQueue(self):
        """ Benchmark loading a typical NZB file into an NZBQueue via the parser, and also via a
        simple put() loop """
        start = time()
        temp = NZBQueue('Hellanzb/test/testdata/msgid_1008115_Bring__Um_Young_#2.nzb')
        
        list = temp.queue
        elapsed = time() - start
        info('Took: ' + str(elapsed) + ' to load nzb file')

        start = time()

        del temp
        nzbq = NZBQueue()
        for i in list:
            nzbq.put((NZBQueue.NZB_CONTENT_P, i))
        
        elapsed = time() - start
        info('Took: ' + str(elapsed) + ' to create NZBQueue')

    def testNZBSlurp(self):
        start = time()
        
        Hellanzb.queue = NZBQueue('Hellanzb/test/testdata/msgid_1008115_Bring__Um_Young_#2.nzb')
        
        elapsed = time() - start
        info('Took: ' + str(elapsed) + ' to load nzb file')

        #from thread import start_new_thread
        #start_new_thread(PriorityQueueTestCase.runReactor, (self,))
        rt = ReactorThread()
        rt.start()
        rt.join()

    # does this need any Randomness?
    def doPut(self, pq, count):
        """ Load a queue with junk """
        percentPar2ExtraP = 10
        
        parCount = count * (1 / percentPar2ExtraP)
        
        start = time()
        for i in xrange(count - parCount):
            pq.put((NZBQueue.NZB_CONTENT_P, i))

        for i in xrange(count):
            pq.put((NZBQueue.EXTRA_PAR2_P, i))
            
        putElapsed = time() - start

        start = time()
        for i in xrange(count):
            pq.get()
        popElapsed = time() - start

        print 'Took: ' + str(putElapsed) + ' to put ' + str(count) + ' items.'
        print 'Took: ' + str(popElapsed) + ' to pop'

import threading        
class ReactorThread(threading.Thread):
    def run(self):
        from twisted.internet import reactor
        from twisted.python import log
        import sys
        # FIXME: fix this namespace
        from Hellanzb.NZBLeecher import NZBLeecherFactory

        #from twisted.internet import cReactor
        #cReactor.install()
        
        # initialize logging
        log.startLogging(sys.stdout)
    
        # create factory protocol and application
        nsf = NZBLeecherFactory()
    
        #from Hellanzb.NZBLeecher.NZBModel import NZBQueue
        #Hellanzb.queue = NZBQueue(sys.argv[1])
    
        # connect factory to this host and port
        reactor.connectTCP("unlimited.newshosting.com", 9000, nsf)
        #reactor.connectTCP("unlimited.newshosting.com", 9000, nsf)
        #reactor.connectTCP("unlimited.newshosting.com", 9000, nsf)
        #reactor.connectTCP("unlimited.newshosting.com", 9000, nsf)
    
        # run
        #reactor.run()
        print 'running'
        reactor.run(installSignalHandlers = False)
# ---------------------------------------------------------------------------

if __name__ == '__main__3':
    nzbq = NZBQueue()
    print 'k'
    nzbq.parseNZB(sys.argv[1])
    while 1:
        try:
            #print nzbq.get(True)[1].__repr__()
            print nzbq.get()
        except:
            print 'doh'
            break
            
#if __name__ == '__main__':
if __name__ == '__main__2':
        import sys
        #(newsgroups, posts) = ParseNZB(sys.argv[1], [1, 2])
        (newsgroups, posts) = ParseNZB(sys.argv[1])
        for n in newsgroups:
                print "n: " + n
        print 'l: ' + str(len(posts))
        total = 0
        from Hellanzb.Util import PriorityQueue
        pq = PriorityQueue()
        NZB_CONTENT_P = 25
        from time import time
        start = time()
        for p in posts:
                print "p: " + p
                print "contents: " + posts[p].__repr__()
                total += posts[p].numparts
                for part in posts[p].parts:
                        pq.put((NZB_CONTENT_P, posts[p].parts[part]))

        elapsed = time() - start
        print 'elapsed: ' + str(elapsed)
        print 'total: ' + str(total)

        #while 1:
        #        print 'p:' + str(pq.get(True)[1])


notes = """
hellanzb NZBLeecher only downloading 4 connections (no decoding)
72385 pjenvey   28   0 29344K 27580K CPU0   1   0:05 11.66%  8.79% python
72385 pjenvey    2   0 29276K 27684K poll   0   0:08 10.38%  9.81% python

nzbget 6 connections
72388 pjenvey    2   0 19184K 16792K poll   1   0:09 23.60% 20.41% nzbget
72388 pjenvey    2   0 19184K 16792K poll   1   0:17 23.69% 23.05% nzbget


"""

testingDay2 = """
4 connections (as above) no decoding
 4873 pjenvey    2   0 26148K 22512K poll   0   0:05 10.53%  9.18% python

4 connections w/ decoding (no thread setting)
 4874 pjenvey   57   0 42936K 41088K CPU1   1   1:11 96.18% 94.14% python

4 connections w/ decoding & suggestThreadPoolSize(3)
(seemed as massive)

"""
