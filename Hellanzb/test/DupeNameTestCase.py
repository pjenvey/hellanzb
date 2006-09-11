"""
DupeNameTestCase - Tests for the dupeName/getNextDupeName functions

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import os, shutil, tempfile, time, unittest, Hellanzb
from Hellanzb.test import HellanzbTestCase
from Hellanzb.Log import *
from Hellanzb.Util import cleanDupeName, dupeName, nextDupeName, touch

__id__ = '$Id$'

class DupeNameTestCase(HellanzbTestCase):

    def setUp(self):
        HellanzbTestCase.setUp(self)
        self.tempDir = tempfile.mkdtemp('hellanzb-DupeNameTestCase')

    def tearDown(self):
        HellanzbTestCase.tearDown(self)
        shutil.rmtree(self.tempDir)

    def testCleanDupeName(self):
        """ Test the cleanDupeName functionality. """ + cleanDupeName.__doc__
        testFile = os.path.join(self.tempDir, 'file')
        testFile0 = os.path.join(self.tempDir, 'file_hellanzb_dupe0')
        self.assertEqual(cleanDupeName(testFile), (testFile, -1))
        self.assertEqual(cleanDupeName(testFile0), (testFile, 0))

    def testDupeName(self):
        """ Test the dupeName functionality. """ + dupeName.__doc__
        testFile = os.path.join(self.tempDir, 'file')
        testFile0 = os.path.join(self.tempDir, 'file_hellanzb_dupe0')
        testFile1 = os.path.join(self.tempDir, 'file_hellanzb_dupe1')
        testFile2 = os.path.join(self.tempDir, 'file_hellanzb_dupe2')
        
        self.assertEqual(dupeName(testFile), testFile)
        self.assertEqual(dupeName(testFile, eschewNames = (testFile)), testFile0)

        touch(testFile)
        touch(testFile0)

        self.assertEqual(dupeName(testFile), testFile1)
        self.assertEqual(dupeName(testFile, eschewNames = (testFile1)), testFile2)

        # checkOnDisk = False, minIteration = 0 should do nothing
        self.assertEqual(dupeName(testFile, checkOnDisk = False, minIteration = 0),
                         testFile)

    def testNextDupeName(self):
        """ Test the nextDupeName functionality. """ + nextDupeName.__doc__
        testFile = os.path.join(self.tempDir, 'file')
        testFile0 = os.path.join(self.tempDir, 'file_hellanzb_dupe0')
        testFile1 = os.path.join(self.tempDir, 'file_hellanzb_dupe1')
        testFile2 = os.path.join(self.tempDir, 'file_hellanzb_dupe2')
        
        self.assertEqual(nextDupeName(testFile), testFile0)
        self.assertEqual(nextDupeName(testFile, eschewNames = (testFile0)), testFile1)

        touch(testFile)
        touch(testFile0)

        self.assertEqual(nextDupeName(testFile), testFile1)
        self.assertEqual(nextDupeName(testFile, checkOnDisk = False), testFile0)
        self.assertEqual(nextDupeName(testFile, checkOnDisk = False,
                                      eschewNames = (testFile0)), testFile1)

        # checkOnDisk = False, minIteration = 0 should do nothing
        self.assertEqual(nextDupeName(testFile, checkOnDisk = False, minIteration = 0),
                         testFile)
        
"""
Copyright (c) 2005 Philip Jenvey <pjenvey@groovie.org>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:
1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.
3. The name of the author or contributors may not be used to endorse or
   promote products derived from this software without specific prior
   written permission.

THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
SUCH DAMAGE.

$Id$
"""
