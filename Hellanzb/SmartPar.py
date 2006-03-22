"""

SmartPar - Functions for identifying potential par files from their their real filename
(as defined in their uuenc/yenc headers), and only downloading them when needed

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import re, Hellanzb
from twisted.internet import reactor
from Hellanzb.Log import *
from Hellanzb.PostProcessorUtil import getParName, getParRecoveryName, isPar, isPar1, \
    isPar2, PAR1, PAR2
from Hellanzb.Util import cleanDupeName, inMainThread, isHellaTemp, prettySize, FatalError

__id__ = '$Id$'

def smartDequeue(segment, readOnlyQueue = False):
    """ This function is called after downloading the first segment of every nzbFile

    It determines whether or not the segment's parent nzbFile is part of a par archive. If
    it is and is also an 'extra' par file ('extra' pars are pars other than the first
    par. The first par nzbFile should contain only verification data and little or no
    recovery data), this function will determine whether or not the rest of the nzbFile
    segments need to be downloaded (dequeueing them from the NZBSegmentQueue when
    necessary, unless the readOnlyQueue is True) """
    if not segment.isFirstSegment():
        raise FatalError('smartDequeue on number > 1')

    if segment.nzbFile.filename is None:
        # We can't do anything 'smart' without the filename
        return

    identifyPar(segment.nzbFile)

    # NOTE: pars that aren't extra pars will need to use this block of code when we start
    # looking for requeue cases (branches/smartpar-requeue). And don't allow them to fall
    # through to the isSkippedPar block
    #if not segment.nzbFile.isPar:
    if not segment.nzbFile.isPar or not segment.nzbFile.isExtraPar:
        return

    nzb = segment.nzbFile.nzb
    isQueuedRecoveryPar = False
    if nzb.isParRecovery and nzb.parPrefix in segment.nzbFile.subject and \
            nzb.neededBlocks > 0:
        isQueuedRecoveryPar = True
        # readOnlyQueue can be True here.
        nzb.neededBlocks -= getParSize(segment.nzbFile.filename)

    if not isQueuedRecoveryPar and len(segment.nzbFile.nzbSegments) == 1:
        # Nothing to actually dequeue (we just downloaded the only segment). If we're in
        # parRecovery mode, fall through so we print the 'queued' message as if we
        # magically intended this 'queueing' to happen
        return
    
    size = segment.nzbFile.totalBytes / 1024 / 1024
    parTypeName = getParName(segment.nzbFile.parType)
        
    if not isQueuedRecoveryPar:
        # Extra par2 -- dequeue the rest of its segments
        dequeueSegments = segment.nzbFile.todoNzbSegments.copy()
        dequeueSegments.remove(segment)

        dequeuedCount = 0
        if not readOnlyQueue:
            dequeued = Hellanzb.queue.dequeueSegments(dequeueSegments)
            dequeuedCount = len(dequeued)
            
            for dequeuedSegment in dequeued:
                segment.nzbFile.nzb.totalSkippedBytes += dequeuedSegment.bytes
            
            if dequeuedCount == 0:
                details = '(nothing in the NZBSegmentQueue to dequeue)'
                debug('smartDequeue: Would have skipped %s: %s' % \
                      (details, segment.nzbFile.filename))
        else:
            segment.nzbFile.nzb.totalSkippedBytes += segment.nzbFile.totalBytes

        # FIXME: It would be nice to take an account of how many actual bytes we just
        # skipped, for printing out at the end of the download

        # Always print the skipped message if called from segmentsNeedDownload
        # (readOnlyQueue). Don't bother printing it if we didn't actually dequeue anything
        if readOnlyQueue or not dequeuedCount == 0:
            info('Skipped %s: %s (%iMB)' % (parTypeName, segment.nzbFile.filename, size))
            
            # Only consider the nzbFile as skipped when there were actually segments
            # dequeued, or if readOnlyQueue mode
            segment.nzbFile.isSkippedPar = True
            segment.nzbFile.nzb.skippedParFiles.append(segment.nzbFile)
    else:
        info('Queued %s: %s (%iMB, %i %s)' % (parTypeName, segment.nzbFile.filename,
                                              size, getParSize(segment.nzbFile.filename),
                                              getParRecoveryName(segment.nzbFile.parType)))

def smartRequeue(nzb):
    """ Certain situations warrant requeueing of previously dequeued files:
    o an NZB archive is determined to be only par files
    
    o an NZB archive with pars does not contain a normally named main par verification
    file (causing hellanzb to skip ALL pars)
    """
    if not nzb.allParsMode and nzb.isAllPars():
        # We were going to skip all the pars, because the NZB contained only pars. Requeue
        # everything for download instead
        nzb.allParsMode = True
        requeueSkippedPars(nzb.skippedParFiles[:])
        info('%s: Par only archive: requeueing all pars for download' % \
             nzb.archiveName)
        
    elif not nzb.isParRecovery and len(nzb.skippedParFiles):
        foundVerificationPar = False
        for nzbFile in nzb.nzbFiles:
            if nzbFile.isPar and not nzbFile.isExtraPar and not nzbFile.isSkippedPar:
                # OR len(dequeued is 0 and len todo is 0?)
                foundVerificationPar = True
                
        if not foundVerificationPar:
            # There are pars but didn't download any of them. Requeue the smallest par
            # available
            parFiles = [(getParSize(parFile.filename), parFile) for parFile in \
                        nzb.skippedParFiles]
            parFiles.sort()
            firstPar = parFiles[0][1]
            info('%s: didn\'t find a main par file, requeueing extra par: %s' % \
                 (nzb.archiveName, firstPar.filename))
            requeueSkippedPars([firstPar])

def logSkippedParCount(nzb):
    """ Print a message describing the number of and size of all skipped par files """
    skippedParMB = 0
    actualSkippedParMB = 0
    for nzbFile in nzb.skippedParFiles:
        skippedParMB += nzbFile.totalBytes
        for nzbSegment in nzbFile.dequeuedSegments:
            actualSkippedParMB += nzbSegment.bytes
    if actualSkippedParMB > 0:
        info('Skipped pars: Approx. %i files, %s (actual: %s)' % \
             (len(nzb.skippedParFiles), prettySize(skippedParMB),
              prettySize(actualSkippedParMB)))

PAR2_VOL_RE = re.compile(r'(.*)\.vol(\d*)\+(\d*)\.par2', re.I)
def identifyPar(nzbFile):
    """ Determine if this nzbFile is a par by its filename. Marks the nzbFile object as
    isPar, and if so, also mark its parType and isExtraPar vars """
    filename = cleanDupeName(nzbFile.filename)[0]
    if isPar(filename):
        nzbFile.isPar = True
    
        if isPar2(filename):
            nzbFile.parType = PAR2
            if not PAR2_VOL_RE.match(filename):
                return
        elif isPar1(filename):
            nzbFile.parType = PAR1
            if filename.lower().endswith('.par'):
                return

        # This is a 'non-essential' par file
        nzbFile.isExtraPar = True

def requeueSkippedPars(skippedParFiles):
    """ Requeue previously skipped par NZBFiles """
    for nzbFile in skippedParFiles:
        nzbFile.isSkippedPar = False
        nzbFile.nzb.skippedParFiles.remove(nzbFile)
        
        # Requeue only segments that were actually dequeued
        for nzbSegment in nzbFile.dequeuedSegments:
            nzbFile.todoNzbSegments.add(nzbSegment)
            Hellanzb.queue.put((nzbSegment.priority, nzbSegment))
            Hellanzb.queue.totalQueuedBytes += nzbSegment.bytes
            nzbFile.nzb.totalSkippedBytes -= nzbSegment.bytes

            # In case we have idle NZBLeechers, turn them back on
            if inMainThread():
                Hellanzb.queue.nudgeIdleNZBLeechers(nzbSegment)
            else:
                reactor.callFromThread(Hellanzb.queue.nudgeIdleNZBLeechers, nzbSegment)

        nzbFile.dequeuedSegments.clear()

GET_PAR2_SIZE_RE = re.compile(r'(?i).*\.vol\d{1,8}\+(\d{1,8}).par2$')
def getParSize(filename):
    """ Determine the par 'size' (type of size depends on the parType) of the par file with
    the specified filename """
    if isPar1(filename):
        return 1
    elif isPar2(filename):
        size = GET_PAR2_SIZE_RE.sub(r'\1', filename)
        if filename != size:
            try:
                return int(size)
            except ValueError:
                pass
    return 0

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
