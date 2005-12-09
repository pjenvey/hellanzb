#!/usr/bin/env python
"""

test - Run all or a specific test

"""
import unittest, Hellanzb.test
from Hellanzb.Core import *
        
def suite():
    s = unittest.TestSuite()
    for package in dir(Hellanzb.test):
        print 'e:' + package
        for test in dir(package):
            print 'hri:' + test
            if isinstance(test, Hellanzb.test.HellanzbTestCase):
                print 'hi:' + test
                s.addTest(test)
    return s

if __name__ == '__main__':
    #unittest.TextTestRunner().run(suite())
    try:
        init()
        #from Hellanzb.test.PriorityQueueTestCase import *
        #from Hellanzb.test.NZBLeecherTestCase import *
        from Hellanzb.test.DupeNameTestCase import *
        s = unittest.TestSuite()
        #s = suite()
        s.addTest(unittest.makeSuite(DupeNameTestCase, 'test'))
        #s.addTest(unittest.makeSuite(NZBLeecherTestCase, 'test'))
        #result = []
        #s.run(result)
        unittest.TextTestRunner().run(s)
    finally:
        shutdown()
