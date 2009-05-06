"""

NZBParser - Parses NZB XML into NZBModels

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import os, re, Hellanzb
try:
    set
except NameError:
    from sets import Set as set
from sets import Set
from xml.sax import make_parser, SAXParseException
from xml.sax.handler import feature_external_ges, feature_namespaces, ContentHandler
from Hellanzb.Log import *
from Hellanzb.Util import DUPE_SUFFIX
from Hellanzb.NZBLeecher.DupeHandler import handleDupeOnDisk
from Hellanzb.NZBLeecher.NZBLeecherUtil import validWorkingFile
from Hellanzb.NZBLeecher.NZBModel import NZBFile, NZBSegment

__id__ = '$Id$'

DUPE_SEGMENT_RE = re.compile('.*%s\d{1,4}\.segment\d{4}$' % DUPE_SUFFIX)
FAILED_ALT_SERVER_SEGMENT_RE = re.compile('.*-hellafailed_.*$')
class NZBParser(ContentHandler):
    """ Parse an NZB 1.0 file into an NZBSegmentQueue
    http://www.newzbin.com/DTD/nzb/nzb-1.0.dtd """
    def __init__(self, nzb, needWorkFiles, needWorkSegments):
        # nzb file to parse
        self.nzb = nzb

        # to be populated with the files that either need to be downloaded or simply
        # assembled, and their segments
        self.needWorkFiles = needWorkFiles
        self.needWorkSegments = needWorkSegments

        # parsing variables
        self.file = None
        self.bytes = None
        self.number = None
        self.chars = None
        self.fileNeedsDownload = None
        
        self.fileCount = 0
        self.segmentCount = 0
        self.fileSegmentNumber = 1

        # All encountered segment numbers for the current NZBFile
        self.segmentNumbers = set()
        
        # Current listing of existing files in the WORKING_DIR
        self.workingDirListing = []
        
        # Map of duplicate filenames -- @see DupeHandler.handleDupeOnDisk
        self.workingDirDupeMap = {}

        # heapq priority
        from Hellanzb.NZBLeecher.NZBSegmentQueue import NZBSegmentQueue
        self.nzbContentPriority = NZBSegmentQueue.NZB_CONTENT_P
        
        files = os.listdir(Hellanzb.WORKING_DIR)
        files.sort()
        for file in files:

            # Anonymous duplicate file segments lying around are too painful to keep track
            # of. As are segments that previously failed on different servers
            if DUPE_SEGMENT_RE.match(file) or FAILED_ALT_SERVER_SEGMENT_RE.match(file):
                os.remove(os.path.join(Hellanzb.WORKING_DIR, file))
                continue

            # Add an entry to the self.workingDirDupeMap if this file looks like a
            # duplicate, and also skip adding it to self.workingDirListing (dupes are
            # handled specially so we don't care for them there)
            if handleDupeOnDisk(file, self.workingDirDupeMap):
                continue
            
            if not validWorkingFile(os.path.join(Hellanzb.WORKING_DIR, file),
                                    self.nzb.overwriteZeroByteFiles):
                continue

            self.workingDirListing.append(file)
            
    def startElement(self, name, attrs):
        if name == 'file':
            subject = self.parseUnicode(attrs.get('subject'))
            poster = self.parseUnicode(attrs.get('poster'))

            self.file = NZBFile(subject, attrs.get('date'), poster, self.nzb)
            self.segmentNumbers.clear()

            self.fileNeedsDownload = \
                self.file.needsDownload(workingDirListing = self.workingDirListing,
                                        workingDirDupeMap = self.workingDirDupeMap)

            # Special handling for par recovery downloads
            extraMsg = ''
            if Hellanzb.SMART_PAR and self.fileNeedsDownload and self.nzb.isParRecovery:
                if not self.nzb.isSkippedParSubject(subject):
                    # Only download previously marked pars
                    self.fileNeedsDownload = False
                    extraMsg = ' (not on disk but wasn\'t previously marked as an skippedParFile)'
                    self.file.nzb.firstSegmentsDownloaded += 1
                elif toUnicode(self.nzb.parPrefix) not in toUnicode(subject):
                    # Previously marked par -- only download it if it pertains to the
                    # particular par. We keep it set to needsDownload here so it gets to
                    # parseNZB -- parseNZB won't actually queue it
                    self.file.isSkippedPar = True
                    
            if not self.fileNeedsDownload:
                debug('SKIPPING FILE%s: %s subject: %s' % (extraMsg, self.file.getTempFileName(),
                                                           self.file.subject))

            self.fileCount += 1
            self.file.number = self.fileCount
            self.fileSegmentNumber = 1
                
        elif name == 'group':
            self.chars = []
                        
        elif name == 'segment':
            try:
                self.bytes = int(attrs.get('bytes'))
            except ValueError:
                self.bytes = 0
            try:
                self.number = int(attrs.get('number'))
            except ValueError:
                self.number = self.fileSegmentNumber
                        
            self.fileSegmentNumber += 1
            self.chars = []
        
    def characters(self, content):
        if self.chars is not None:
            self.chars.append(content)
        
    def endElement(self, name):
        if name == 'file':
            if self.fileNeedsDownload:
                self.needWorkFiles.append(self.file)
            else:
                # done adding all child segments to this NZBFile. make note that none of
                # them need to be downloaded
                self.file.nzb.totalSkippedBytes += self.file.totalBytes
                self.file.todoNzbSegments.clear()
            
            self.file = None
            self.fileNeedsDownload = None
                
        elif name == 'group':
            newsgroup = self.parseUnicode(''.join(self.chars))
            self.file.groups.append(newsgroup)
                        
            self.chars = None
                
        elif name == 'segment':
            if self.number in self.segmentNumbers:
                # This segment number was already registered
                return
            self.segmentNumbers.add(self.number)

            self.segmentCount += 1

            messageId = self.parseUnicode(''.join(self.chars))
            nzbs = NZBSegment(self.bytes, self.number, messageId, self.file)
            if self.number == 1:
                self.file.firstSegment = nzbs

            if self.fileNeedsDownload:
                # HACK: Maintain the order in which we encountered the segments by adding
                # segmentCount to the priority. lame afterthought -- after realizing
                # heapqs aren't ordered. nzbContentPriority must now be large enough so
                # that it won't ever clash with EXTRA_PAR2_P + i
                nzbs.priority = self.nzbContentPriority
                if nzbs.number != 1:
                    nzbs.priority += self.segmentCount
                self.needWorkSegments.append(nzbs)

            self.chars = None
            self.number = None
            self.bytes = None    

    def parseUnicode(self, unicodeOrStr):
        if isinstance(unicodeOrStr, unicode):
            unicodeOrStr = unicodeOrStr.encode('latin-1')
        return unicodeOrStr.strip()

class NZBTotalBytesParser(ContentHandler):
    """ Parse only the byte count from an NZB file """
    # FIXME: this should also be used to verify the XML validity of the NZB before
    # queueing
    def __init__(self):
        self.bytes = 0
        
    def startElement(self, name, attrs):
        if name == 'segment' and attrs.has_key('bytes'):
            try:
                self.bytes += int(attrs['bytes'])
            except ValueError:
                pass

    def getBytes(nzb):
        """ Return the number of bytes the specified NZB represents """
        s = time.time()
        # Create a parser
        parser = make_parser()

        # No XML namespaces here
        parser.setFeature(feature_namespaces, 0)
        parser.setFeature(feature_external_ges, 0)

        # Tell the parser to use it
        p = NZBTotalBytesParser()
        parser.setContentHandler(p)

        # Parse the input
        try:
            parser.parse(nzb.nzbFileName)
        except SAXParseException, saxpe:
            debug('Unable to parse invalid NZB file: %s: %s: exception: %s' % \
                  (os.path.basename(nzb.nzbFileName), saxpe.getMessage(),
                   saxpe.getException()))
            return
        from Hellanzb.Daemon import writeStateXML
        writeStateXML()

        debug('NZBTotalBytesParser(%s) took: %f, bytes: %i' % (nzb.nzbFileName,
                                                               time.time() - s, p.bytes))
        nzb.totalBytes = p.bytes
        nzb.calculatingBytes = False
    getBytes = staticmethod(getBytes)
    
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
