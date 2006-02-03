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
from Hellanzb.PostProcessorUtil import getParRecoveryName, isPar, isPar1, isPar2
from Hellanzb.Util import FatalError
from Hellanzb.NZBLeecher.ArticleDecoder import setRealFileName, stripArticleData, ySplit

__id__ = '$Id$'

#def dequeueIfExtraPar(segment, segmentList = None):
def dequeueIfExtraPar(segment):
    # FIXME: must download in order: number 1 segment. check the headers. if this is a par
    # file, and the nzb has failed previous crc checks (only if ydecode) and we probably
    # havent dled enough repair already or we are explicitly forced to get all pars at nzb
    # level -- assure we dl other segments. otherwise print 'skipping', remove all nzbfile
    # segments from the queue list and re heapq.heapify the queue list
    if segment.number != 1:
        raise FatalError('dequeueIfExtraPar on number > 1')

    # FIXME: make find('hellanzb-tmp') a function in Util
    if segment.nzbFile.filename is None or \
            segment.nzbFile.filename.find('hellanzb-tmp-') == 0:
        segment.loadArticleDataFromDisk(removeFromDisk = False)
        stripArticleData(segment.articleData)

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
        # FIXME: show filename information. check for hellanzb-tmp here too? hellanzb-tmp
        # is used for segmentsNeedDownload
        raise FatalError('handleParSegment: Could not get real fileName %d!' % segment.number)

    """
    # FIXME: also - resume code needs to skip, when we find an isPar segment #1 on disk
    PAR2_VOL_RE = re.compile(r'(.*)\.vol(\d*)\+(\d*)\.par2', re.I)
    if isPar(segment.nzbFile.filename):
        segment.nzbFile.isParFile = True
    
        if isPar2(segment.nzbFile.filename) and \
                not PAR2_VOL_RE.match(segment.nzbFile.filename):
            # Not a .vol????.par2. This is the main par2, download it
            return
        elif isPar1(segment.nzbFile.filename) and \
                segment.nzbFile.filename.lower().endswith('.p00'):
            # First par1 should be .p00
            return

        segment.nzbFile.isExtraParFile = True
        """
    identifyPar(segment.nzbFile)
    if segment.nzbFile.isParFile:
        desc = 'par2'
        if isPar1(segment.nzbFile.filename):
            desc = 'par1'
            
        size = segment.nzbFile.totalBytes / 1024 / 1024
        if segment.nzbFile.isExtraParFile:
            # Extra par2 -- remove it from the queue
            info('Skipping %s: %s (%iMB, %i %s)' % (desc, segment.nzbFile.filename, size,
                                                    getParSize(segment.nzbFile.filename),
                                                    getParRecoveryName(segment.nzbFile.parType)))
            Hellanzb.queue.dequeueSegments(segment.nzbFile.nzbSegments)
            #if segmentList is not None:
            #    [segmentList.remove(dequeuedSegment) for dequeuedSegment in \
            #     segment.nzbFile.nzbSegments]
            segment.nzbFile.isSkippedPar = True
    elif segment.nzbFile.isParFile:
        info('Queued %s: %s (%iMB, %i %s)' % (desc, segment.nzbFile.filename, size,
                                              getParSize(segment.nzbFile.filename),
                                              getParRecoveryName(segment.nzbFile.parType)))

PAR2_VOL_RE = re.compile(r'(.*)\.vol(\d*)\+(\d*)\.par2', re.I)
def identifyPar(nzbFile):
    """ Identify the nzbFile object as isParFile and isExtraParFile """
    if isPar(nzbFile.filename):
        nzbFile.isParFile = True
    
        if isPar2(nzbFile.filename) and \
                not PAR2_VOL_RE.match(nzbFile.filename):
            # Not a .vol????.par2. This is the main par2, download it
            return
        elif isPar1(nzbFile.filename) and \
                nzbFile.filename.lower().endswith('.p00'):
            # First par1 should be .p00
            return

        if nzbFile.nzb.isParRecovery and nzbFile.nzb.parPrefix in nzbFile.subject and \
                nzbFile.nzb.neededBlocks > 0:
            info('filename: ' + nzbFile.filename + ' parPrefix: ' + nzbFile.nzb.parPrefix)
            nzbFile.nzb.neededBlocks -= getParSize(nzbFile.filename)
        else:
        #if not nzbFile.nzb.isParRecovery or nzbFile.nzb.parPrefix not in nzbFile.subject or \
            #nzbFile.nzb.neededBlocks == 0:
            info('filename: ' + nzbFile.filename + 'isExtraParFile: True')
            nzbFile.isExtraParFile = True

GET_PAR2_SIZE_RE = re.compile(r'(?i).*\.vol\d{1,8}\+(\d{1,8}).par2$')
def getParSize(filename):
    """ Determine the par 'size' (type of size depends on the parType) of the par file with
    the specified filename """
    if isPar1(filename):
        return 1
    elif isPar2(filename):
        size = GET_PAR2_SIZE_RE.sub(r'\1', filename)
        if filename != size:
            return int(size)
    return 0

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
