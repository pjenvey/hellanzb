"""
HellanzbTestCase - All hellanzb tests should derive from this class

@author pjenvey
"""
import unittest
import Hellanzb.Core

__id__ = '$Id$'

class HellanzbTestCase(unittest.TestCase):
    def setUp(self):
        """ Initialize hellanzb core """
        Hellanzb.Core.init({})

    def tearDown(self):
        """ Take it down """
        Hellanzb.Core.shutdown()
