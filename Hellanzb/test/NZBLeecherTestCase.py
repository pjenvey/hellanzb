from Hellanzb.test import HellanzbTestCase
from Hellanzb.NZBLeecher import *

class NZBLeecherTestCase(HellanzbTestCase):

    def testNZBLeecher(self):
        initNZBLeecher()
        info('Init')
        #from Hellanzb.NZBLeecher.NZBModel import NZBQueue
        if len(sys.argv) > 1:
            info('Loading: ' + sys.argv[1])
            Hellanzb.queue.parseNZB(sys.argv[1])
            startNZBLeecher()
