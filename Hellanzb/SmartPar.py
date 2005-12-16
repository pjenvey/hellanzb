"""

SmartPar - Functions for identifying potential par files from their subject lines (these
are downloaded first), verifying that these segments are in fact pars by their actual
filename (as in their uuenc/yenc headers), and only downloading them when needed.

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import re, Hellanzb
from xml.sax import make_parser, SAXParseException
from xml.sax.handler import ContentHandler, feature_external_ges, feature_namespaces
from Hellanzb.Log import *
from Hellanzb.PostProcessorUtil import isPar, isPar1, isPar2
from Hellanzb.Util import FatalError
from Hellanzb.NZBLeecher.ArticleDecoder import setRealFileName, stripArticleData, ySplit

__id__ = '$Id$'

class ParExtractor(ContentHandler):
    """ SAX Parser that extracts only known extra par files from an NZB file, writing only
    those pars to a new NZB file """
    # FIXME: finish, write attrs, write a attr to the NZB tag saying 'hellanzb_extra_pars_only=True'
    # use XMLGenerator? http://www.xml.com/pub/a/2003/03/12/py-xml.html
    def __init__(self, destNZBFile, knownParSubjects):
        self.destNZBFile, self.knownParSubjects = destNZBFile, knownParSubjects
        self.outFile = open(destNZBFile, 'w')

        self.pad = ' '*8
        self.indent = -1
        self.skip = False
        
    def parse(nzbFile, destNZBFile, knownParSubjects):
        """ Parse the NZB -- extract the pars into a new file """
        # Create a parser
        parser = make_parser()
        
        # No XML namespaces here
        parser.setFeature(feature_namespaces, 0)
        parser.setFeature(feature_external_ges, 0)
        pe = ParExtractor(destNZBFile, knownParSubjects)
        
        # Tell the parser to use it
        parser.setContentHandler(pe)

        # Parse the input
        try:
            parser.parse(nzbFile)
        except SAXParseException, saxpe:
            raise FatalError('Unable to parse Invalid NZB file: ' + os.path.basename(nzbFile))            
    parse = staticmethod(parse)

    def startElement(self, name, attrs):
        indent += 1
        
        if name == 'file':
            subject = self.parseUnicode(attrs.get('subject'))
            
            if subject in self.knownParSubjects:
                self.skip = True

        if not self.skip:
            self.outFile.write(self.pad * self.indent + '<' + name + '>')
        
    def characters(self, content):
        if not self.skip:
            self.outFile.write(content)
            
    def endElement(self, name):
        if not self.skip:
            self.outFile.write(self.pad * self.indent + '</' + name + '>')
        else:
            self.skip = False
            
        indent -= 1


def dequeueIfExtraPar(segment):
    # FIXME: must download in order: number 1 segment. check the headers. if this is a par
    # file, and the nzb has failed previous crc checks (only if ydecode) and we probably
    # havent dled enough repair already or we are explicitly forced to get all pars at nzb
    # level -- assure we dl other segments. otherwise print 'skipping', remove all nzbfile
    # segments from the queue list and re heapq.heapify the queue list
    if segment.number != 1:
        raise FatalError('handleParSuspect on number > 1')

    segment.loadArticleDataFromDisk(removeFromDisk = False)
    stripArticleData(segment.articleData)

    # FIXME
    #if segment.nzbFile.filename != None:

    index = -1
    for line in segment.articleData:
        index += 1

        # Don't go to far
        if index > 20:
            break
    
        if line.startswith('=ybegin'):
            ybegin = ySplit(line)
            setRealFileName(segment.nzbFile, ybegin['name'],
                            settingSegmentNumber = segment.number)
            break
        
        elif line.startswith('begin '):
            filename = line.rstrip().split(' ', 2)[2]
            setRealFileName(segment.nzbFile, filename,
                            settingSegmentNumber = segment.number)
            break

    if segment.nzbFile.filename == None:
        # FIXME: show filename information
        raise FatalError('handleParSegment: Could not get real fileName %d!' % segment.number)

    # FIXME: also - resume code needs to skip, when we find an isPar segment #1 on disk
    PAR2_VOL_RE = re.compile(r'(.*)\.vol(\d*)\+(\d*)\.par2', re.I)
    if isPar(segment.nzbFile.filename):
        segment.nzbFile.isParFile = True
    
        if isPar2(segment.nzbFile.filename) and not PAR2_VOL_RE.match(segment.nzbFile.filename):
            # not a .vol????.par2. Download it
            return
        elif isPar1(segment.nzbFile.filename) and segment.nzbFile.filename.lower().endswith('.p00'):
            # first par1 should be .p00
            return

        segment.nzbFile.isExtraParFile = True

        # Extra par2 -- remove it from the queue
        desc = 'par2'
        if isPar1(segment.nzbFile.filename):
            desc = 'par1'
            
        size = segment.nzbFile.totalBytes / 1024 / 1024
        info('Skipping %s: %s (%d MB)' % (desc, segment.nzbFile.filename, size))
        Hellanzb.queue.dequeueSegments(segment.nzbFile.nzbSegments)
        segment.nzbFile.isSkippedPar = True


"""
/*
 * Copyright (c) 2005 Philip Jenvey <pjenvey@groovie.org>
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 * 3. The name of the author or contributors may not be used to endorse or
 *    promote products derived from this software without specific prior
 *    written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
 * FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 * DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
 * OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
 * HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 * LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
 * OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
 * SUCH DAMAGE.
 *
 * $Id$
 */
"""
