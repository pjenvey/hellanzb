# -*- coding: iso-8859-1 -*-
"""
UnicodeFilenameTestCase - Tests the ability to write unicode filenames to disk and have
them later recognized in the directory listing

(c) Copyright 2006 Philip Jenvey
[See end of file]
"""
import os, shutil, tempfile
from unicodedata import normalize
from Hellanzb.test import HellanzbTestCase, EVIL_STRINGS
from Hellanzb.Log import *
from Hellanzb.Util import isDupeName, toUnicode, ufilename, uopen
from Hellanzb.NZBLeecher import initNZBLeecher
from Hellanzb.NZBLeecher.ArticleDecoder import assembleNZBFile, decodeArticleData
from Hellanzb.NZBLeecher.NZBModel import NZB

__id__ = '$Id: UnicodeFilenameTestCase.py 665 2006-02-16 23:27:52Z pjenvey $'

NZB_S = """<?xml version="1.0" encoding="iso-8859-1" ?>
<!DOCTYPE nzb PUBLIC "-//newzBin//DTD NZB 1.0//EN" "http://www.newzbin.com/DTD/nzb/nzb-1.0.dtd">
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">

%s

</nzb>
"""
FILE_S = """        <file subject="&#34;%s&#34; (1/1) yEnc - 001 of 107" date="1140771628" poster="&#34;test&#34; &lt;test-user@alt.binaries.test&gt;">
                <groups>
                        <group>alt.binaries.test</group>
                </groups>

                <segments>
                        <segment bytes="75778" number="1">43feb2a$$544bf67a60@news.test.com</segment>
                        <segment bytes="75778" number="2">43feb2a$$544bf67a60@news.test.com</segment>
                </segments>
        </file>
"""

class UnicodeFilenameTestCase(HellanzbTestCase):
    #verbose = True

    def setUp(self):
        HellanzbTestCase.setUp(self)
        self.tempDir = tempfile.mkdtemp('hellanzb-UnicodeFilenameTestCase')
        Hellanzb.WORKING_DIR = self.tempDir

    def tearDown(self):
        HellanzbTestCase.tearDown(self)
        shutil.rmtree(self.tempDir)

    def cleanUp(self, eschew = None):
        if eschew is None:
            eschew = []
        for file in os.listdir(toUnicode(self.tempDir)):
            if file not in eschew:
                os.remove(self.tempDir + os.sep + file)

    def testBasicSubjectMatching(self):
        """ Test basic subject matching -- uopen, and matching the filename """
        for test in EVIL_STRINGS:
            self.assertBasicSubjectMatch(test)

    def assertBasicSubjectMatch(self, filename):
        # Create the file
        fullPath = self.tempDir + os.sep + filename
        testFile = uopen(fullPath, 'wb')
        testFile.write('test')
        testFile.close()

        listing = os.listdir(unicode(self.tempDir))
        if self.verbose:
            info('basic: created dir listing: %s' % str(listing))

        self.assertEquals(1, len(listing))
        onDiskFilename = listing[0]

        # Ensure the exact same filename we just wrote to disk is returned by
        # os.listdir. OS X (will any other OS do this?), or I suppose HFS, will recompose
        # decomposed unicode characters (See:
        # http://lists.gnu.org/archive/html/rdiff-backup-users/2005-10/msg00125.html). So
        # we must normalize them
        self.assertEquals(normalize('NFC', toUnicode(filename)),
                          normalize('NFC', toUnicode(onDiskFilename)))

        self.assertEquals(True, os.path.isfile(ufilename(self.tempDir + os.sep + filename)))

        self.cleanUp()
        
    def testInvolvedSubjectMatch(self):
        """ Basically the same as testSubjectMatch, but ensures hellanzb NZBSegmentParser is
        accomplishing the subject matching on its own """
        for test in EVIL_STRINGS:
            self.assertInvolvedSubjectMatch(test)

    def testDupeSubjectMatch(self):
        if self.verbose:
            info('testDupeSubjectMatch..')
            
        for test in EVIL_STRINGS:
            self.assertInvolvedSubjectMatch(test, testDupe = True)

    def decode(self, nzbSegment):
        yencodedTest = """=ybegin line=256 size=5 crc32=3bb935c6 name=%s
žž4
=yend size=5 crc32=3bb935c6""" % self.filename
        nzbSegment.articleData = yencodedTest.splitlines()
        encoding = decodeArticleData(nzbSegment)

        # Ensure it was ydecoded
        self.assertEquals(1, encoding)
        if self.verbose:
            info('involved: decoded: file: %i segment: %i (%s)' % \
                 (nzbSegment.nzbFile.number, nzbSegment.number,
                  nzbSegment.nzbFile.filename))

    def assertInvolvedSubjectMatch(self, filename, testDupe = False):
        self.filename = filename
        
        # Decode the next segment in the queue
        d = lambda: self.decode(Hellanzb.queue.getSmart('test')[1])
                                
        files = FILE_S % filename
        if testDupe:
            nzbs = NZB_S % (files + files)
        else:
            nzbs = NZB_S % files

        # Create an NZB file with a couple segments
        nzbFilename = self.tempDir + os.sep + 'test.nzb'
        t = open(nzbFilename, 'wb')
        t.write(nzbs)
        t.close()

        n = NZB(nzbFilename)
        n.destDir = self.tempDir

        # Initialize the queue
        initNZBLeecher()

        # Parse the NZB, ensure the two segments
        Hellanzb.queue.parseNZB(n, verbose = False)
        if testDupe:
            self.assertEquals(4, len(Hellanzb.queue))
        else:
            self.assertEquals(2, len(Hellanzb.queue))

        # Decode the first segment to disk
        d()

        if self.verbose:
            info('involved: created dir listing: %s ' % str(os.listdir(self.tempDir)))

        # Re-init (clean) the queue, reparse
        n.finalize(justClean = True)
        initNZBLeecher()
        Hellanzb.queue.parseNZB(n, verbose = False)

        # Ensure the parser has skipped a (the first) segment
        if testDupe:
            self.assertEquals(3, len(Hellanzb.queue))
        else:
            self.assertEquals(1, len(Hellanzb.queue))

        if testDupe:
            p, nzbSegment = Hellanzb.queue.getSmart('test')

            nzbFileOne = Hellanzb.queue.getSmart('test')[1].nzbFile
            self.assertEquals(1, nzbFileOne.number)

            # Decoding two segment 1s should result in the still being processed
            # nzbFileOne being renamed to a dupe name
            self.decode(nzbSegment)
            self.assertEquals(True, isDupeName(nzbFileOne.filename))
            if self.verbose:
                info('involved: found dupeName: ' + nzbFileOne.filename)

            self.cleanUp(['test.nzb'])
            
            n.finalize(justClean = True)
            initNZBLeecher()
            Hellanzb.queue.parseNZB(n, verbose = False)
            
            p, firstSegment = Hellanzb.queue.getSmart('test') # skip file two segment one
            p, nextSegment = Hellanzb.queue.getSmart('test') # skip file two segment one
            
            # Decode file one segment one
            if firstSegment.nzbFile.number == 1:
                fileOne = firstSegment.nzbFile
                self.decode(firstSegment)
                fileTwoSegmentOne = nextSegment
            else:
                fileOne = nextSegment.nzbFile
                self.decode(nextSegment)
                fileTwoSegmentOne = firstSegment
            self.assertEquals(1, fileOne.number)
            
            # Decode file one segment two and assemble file one
            p, nzbSegment = Hellanzb.queue.getSmart('test')
            self.decode(nzbSegment)
            self.assertEquals(1, nzbSegment.nzbFile.number)
            assembleNZBFile(fileOne)
            
            self.decode(fileTwoSegmentOne) # decode file two segment one
            self.assertEquals(False, isDupeName(fileOne.filename))

            d() # decode file two segment two
            # assembling file two should result in one dupe in the dir. NOTE: the
            # nzbFile.filename isn't renamed because this nzbFile is no longer in use
            # (fully assembled)
            assembleNZBFile(fileTwoSegmentOne.nzbFile)
            dupes = [file for file in os.listdir(self.tempDir) if isDupeName(file)]
            self.assertEquals(1, len(dupes))
            return

        # Decode the second segment to disk
        p, nzbSegment = Hellanzb.queue.getSmart('test')
        self.decode(nzbSegment)

        # Assemble the file
        assembleNZBFile(nzbSegment.nzbFile)

        # Re-init (clean) the queue AGAIN, reparse, now ensure the assembled file's
        # filename was matched (skipped)
        n.finalize(justClean = True)
        initNZBLeecher()
        Hellanzb.queue.parseNZB(n, verbose = False)
        self.assertEquals(0, len(Hellanzb.queue))

        self.cleanUp()
        
"""
Copyright (c) 2006 Philip Jenvey <pjenvey@groovie.org>
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

$Id: UnicodeFilenameTestCase.py 665 2006-02-16 23:27:52Z pjenvey $
"""
