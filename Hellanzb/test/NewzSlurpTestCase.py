from Hellanzb.test import HellanzbTestCase
from Hellanzb.NewzSlurp.NewzSlurper import *

class NewzSlurpTestCase(HellanzbTestCase):

    def testNewzSlurp(self):
        initNewzSlurp()
        info('Init')
        #from Hellanzb.NewzSlurp.NZBModel import NZBQueue
        if len(sys.argv) > 1:
            info('Loading: ' + sys.argv[1])
            Hellanzb.queue.parseNZB(sys.argv[1])
            startNewzSlurp()
