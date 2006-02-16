# -*- coding: iso-8859-1 -*-
"""
StateXMLTestCase - Tests to assure NZB/Archive objects are successfully recovered from the
hellanzb state xml

(c) Copyright 2006 Philip Jenvey
[See end of file]
"""
import os, shutil, tempfile, time, unittest, Hellanzb, Hellanzb.NZBQueue
from Hellanzb.test import HellanzbTestCase
from Hellanzb.Log import *
from Hellanzb.NZBLeecher.NZBModel import NZB, NZBFile
from Hellanzb.NZBQueue import recoverStateFromDisk
from Hellanzb.NZBLeecher.NZBSegmentQueue import NZBSegmentQueue
from Hellanzb.PostProcessorUtil import PAR2
from Hellanzb.Util import toUnicode

__id__ = '$Id$'

EVIL_STRINGS = ('SÃÂ£o_Paulo', 'Zappa_–_', '_Les_Rivières_Pourpres',
                '_SkandalÃ¶s_-_Ficken_Auf_Der_Strasse')
                
class StateXMLTestCase(HellanzbTestCase):
    verbose = False

    def setUp(self):
        HellanzbTestCase.setUp(self)
        self.tempDir = tempfile.mkdtemp('hellanzb-StateXMLTestCase')
        self.setUpEnv()

    def setUpEnv(self):
        self.stateXMLFileName = self.tempDir + os.sep + 'testState.xml'
        self.stateXMLFile = open(self.stateXMLFileName, 'w+')
        Hellanzb.queue = NZBSegmentQueue()
        Hellanzb.postProcessors = []
        Hellanzb.queued_nzbs = []

    def tearDown(self):
        HellanzbTestCase.tearDown(self)
        shutil.rmtree(self.tempDir)

    def testArchiveNameRecovery(self):
        """ Ensure state XML recovery via archive names """
        for test in EVIL_STRINGS:
            self.setUpEnv()
            self.assertRecoveredArchiveName(test)

    def assertRecoveredArchiveName(self, name):
        n = NZB(name)
        n.rarPassword = rarPassword = 'recoverme'
        archiveName = n.archiveName
        Hellanzb.queue.nzbAdd(n)

        self.writeState()
        del n
        self.recoverState()

        n2 = NZB.fromStateXML('downloading', name)
        self.assertEquals(rarPassword, n2.rarPassword)
        self.assertEquals(name, n2.nzbFileName)
        self.assertEquals(archiveName, n2.archiveName)

    def testSkippedParUnicodeRecovery(self):
        """ Ensure skipped par subjects can be matched after state XML recovery """
        # 'SÃÂ£o_Paulo' looks like this in XML:
        # S&#195;&#194;&#163;o_Paulo ('SÃÂ£o_Paulo')
        # after parsed from XML into recovered:
        # ...[u'S\xc3\xc2\xa3o_Paulo']
        # u'SÃÂ£o_Paulo' in XML:
        # SÃÂ£o_Paulo
        # after parsed from XML:
        # [u'S\xc3\xc2\xa3o_Paulo']
        for test in EVIL_STRINGS:
            self.setUpEnv()
            self.assertRecoveredSkippedPar(test)

    def assertRecoveredSkippedPar(self, subject):
        n = NZB('test.nzb')
        n.isParRecovery = True
        n.parPrefix = 'test'
        n.parType = PAR2
        Hellanzb.queue.nzbAdd(n)
        
        file = NZBFile(subject, 'today', 'test@test.com', n)
        file.isSkippedPar = True
        
        self.writeState()
        del n
        self.recoverState()

        n2 = NZB.fromStateXML('downloading', 'test')
        #print str(Hellanzb.recoveredState)
        #print str(n2.skippedParSubjects)
        self.assertEquals(True, n2.isSkippedParSubject(subject))

    def writeState(self):
        logStateXML(self.stateXMLFile.write, False)
        
        if self.verbose:
            self.stateXMLFile.seek(0)
            for line in self.stateXMLFile.readlines():
                print line
                
        self.stateXMLFile.close()

    def recoverState(self):
        recoverStateFromDisk(self.stateXMLFileName)
        
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

$Id$
"""
