"""

NZBModel - Representations of the NZB file format in memory

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import os, re, Hellanzb
from sets import Set
from threading import Lock, RLock
from Hellanzb.Log import *
from Hellanzb.Util import archiveName, getFileExtension, nuke, IDPool
from Hellanzb.NZBLeecher.ArticleDecoder import parseArticleData, setRealFileName
from Hellanzb.NZBLeecher.DupeHandler import handleDupeNZBFileNeedsDownload
from Hellanzb.NZBLeecher.NZBLeecherUtil import validWorkingFile
from Hellanzb.PostProcessorUtil import Archive
from Hellanzb.SmartPar import dequeueIfExtraPar, identifyPar

__id__ = '$Id$'

segmentEndRe = re.compile(r'^segment\d{4}$')
def segmentsNeedDownload(segmentList, overwriteZeroByteSegments = False):
    """ Faster version of needsDownload for multiple segments that do not have their real file
    name (for use by the Queue).

    When an NZB is loaded and parsed, NZB<file>s not found on disk at the time of parsing
    are marked as needing to be downloaded. (An easy first pass of figuring out exactly
    what needs to be downloaded).

    This function is the second pass. It takes all of those NZBFiles that need to be
    downloaded's child NZBSegments and scans the disk, detecting which segments are
    already on disk and can be skipped
    """
    # Arrange all WORKING_DIR segment's filenames in a list. Key this list by segment
    # number in a map. Loop through the specified segmentList, doing a subject.find for
    # each segment filename with a matching segment number

    onDiskSegmentsByNumber = {}
    
    needDlFiles = Set() # for speed while iterating
    needDlSegments = []
    onDiskSegments = []

    # Cache all WORKING_DIR segment filenames in a map of lists
    for file in os.listdir(Hellanzb.WORKING_DIR):
        if not validWorkingFile(Hellanzb.WORKING_DIR + os.sep + file,
                                overwriteZeroByteSegments):
            continue
        
        ext = getFileExtension(file)
        if ext != None and segmentEndRe.match(ext):
            segmentNumber = int(ext[-4:])
            
            if onDiskSegmentsByNumber.has_key(segmentNumber):
                segmentFileNames = onDiskSegmentsByNumber[segmentNumber]
            else:
                segmentFileNames = []
                onDiskSegmentsByNumber[segmentNumber] = segmentFileNames

            # cut off .segmentXXXX
            fileNoExt = file[:-12]
            segmentFileNames.append(fileNoExt)

    # Determine if each segment needs to be downloaded
    for segment in segmentList:

        if not onDiskSegmentsByNumber.has_key(segment.number):
            # No matching segment numbers, obviously needs to be downloaded
            needDlSegments.append(segment)
            needDlFiles.add(segment.nzbFile)
            continue

        segmentFileNames = onDiskSegmentsByNumber[segment.number]
        
        foundFileName = None
        for segmentFileName in segmentFileNames:
            # We've matched to our on disk segment if we:
            # a) find that on disk segment's file name in our potential segment's subject
            # b) match that on disk segment's file name to our potential segment's temp
            # file name (w/ .segmentXXXX cutoff)
            if segment.nzbFile.subject.find(segmentFileName) > -1 or \
                    segment.getTempFileName()[:-12] == segmentFileName:
                foundFileName = segmentFileName
                # make note that this segment doesn't have to be downloaded
                try:
                    segment.nzbFile.todoNzbSegments.remove(segment)
                finally:
                    # dequeueIfExtraPar could have already removed this segment from
                    # todoNzbSegments
                    break

        if not foundFileName:
            needDlSegments.append(segment)
            needDlFiles.add(segment.nzbFile)
        else:
            if segment.number == 1 and foundFileName.find('hellanzb-tmp-') != 0 and \
                    segment.nzbFile.filename is None:
                # HACK: filename is None. so we only have the temporary name in
                # memory. since we didnt see the temporary name on the filesystem, but we
                # found a subject match, that means we have the real name on the
                # filesystem. In the case where this happens we've figured out the real
                # filename (hopefully!). Set it if it hasn't already been set
                setRealFileName(segment.nzbFile, foundFileName,
                            settingSegmentNumber = segment.number)

                # dequeue the entire nzbFile if we've found an extra par file. NOTE:
                # dequeueIfExtraPar will raise an Exception if the segment.number is >
                # 1. We only end up in this block of code if that is the case, anyway,
                # because it checks for segment.nzbFile.filename is None (and we go
                # through a sorted list of segments)
                #dequeueIfExtraPar(segment, segmentList)
                dequeueIfExtraPar(segment)
                
            onDiskSegments.append(segment)
            
            # We only call segmentDone here to update the queue's onDiskSegments. The call
            # shouldn't actually be decrementing the queue's totalQueuedBytes at this
            # point. We call this so isBeingDownloaded (called from handleDupeNZBSegment)
            # can identify orphaned segments on disk that technically aren't being
            # downloaded, but need to be identified as so, so their parent NZBFile can be
            # renamed
            Hellanzb.queue.segmentDone(segment)

            # This segment was matched. Remove it from the list to avoid matching it again
            # later (dupes)
            segmentFileNames.remove(foundFileName)

        #else:
        #    debug('SKIPPING SEGMENT: ' + segment.getTempFileName() + ' subject: ' + \
        #          segment.nzbFile.subject)

    return needDlFiles, needDlSegments, onDiskSegments

class NZB(Archive):
    """ Representation of an nzb file -- the root <nzb> tag """
    
    def __init__(self, nzbFileName, id = None, rarPassword = None, archiveDir = None):
        Archive.__init__(self, archiveDir, id, None, rarPassword)
            
        ## NZB file general information
        self.nzbFileName = nzbFileName
        self.archiveName = archiveName(self.nzbFileName) # pretty name
        self.nzbFileElements = []

        # Where the nzb files will be downloaded
        self.destDir = Hellanzb.WORKING_DIR

        ## A cancelled NZB is marked for death. ArticleDecoder will dispose of any
        ## recently downloaded data that might have been downloading during the time the
        ## cancel call was made (after the fact cleanup)
        self.canceled = False
        self.canceledLock = Lock()

        ## Total bytes this NZB represents
        self.totalBytes = 0
        
        ## How many bytes were skipped for downloading
        self.totalSkippedBytes = 0
        ## How many bytes have been downloaded for this NZB
        self.totalReadBytes = 0

        ## Whether or not we should redownload NZBFile and NZBSegment files on disk that are 0 bytes in
        ## size
        self.overwriteZeroByteFiles = True

        ## Extra par subject names are kept here, in a list, during post processing
        self.isParRecovery = False
        self.neededBlocks = 0
        self.parType = None
        self.parPrefix = None
        self.extraParNamesList = None
        
    def isCanceled(self):
        """ Whether or not this NZB was cancelled """
        # FIXME: this doesn't need locks
        self.canceledLock.acquire()
        c = self.canceled
        self.canceledLock.release()
        return c

    def cancel(self):
        """ Mark this NZB as having been cancelled """
        # FIXME: this doesn't need locks
        self.canceledLock.acquire()
        self.canceled = True
        self.canceledLock.release()

    def getName(self):
        #return os.path.basename(self.nzbFileName)
        return os.path.basename(self.archiveName)

    def toStateXML(self):
        pass
        
class NZBFile:
    """ <nzb><file/><nzb> """

    def __init__(self, subject, date = None, poster = None, nzb = None):
        ## XML attributes
        self.subject = subject
        self.date = date
        self.poster = poster

        ## XML tree-collections/references
        # Parent NZB
        self.nzb = nzb
        # FIXME: thread safety?
        self.nzb.nzbFileElements.append(self)
        
        self.groups = []
        self.nzbSegments = []

        ## TO download segments --
        # we'll remove from this set everytime a segment is found completed (on the FS)
        # during NZB parsing, or later written to the FS
        self.todoNzbSegments = Set()

        ## NZBFile statistics
        self.number = len(self.nzb.nzbFileElements)
        self.totalBytes = 0
        self.totalSkippedBytes = 0
        self.totalReadBytes = 0
        self.downloadPercentage = 0
        self.speed = 0
        self.downloadStartTime = None

        ## yEncode header keywords. Optional (not used for UUDecoded segments)
        # the expected file size, as reported from yencode headers
        self.ySize = None

        ## On Disk filenames
        # The real filename, determined from the actual articleData's yDecode/UUDecode
        # headers
        self.filename = None
        # The filename used temporarily until the real filename is determined
        self.tempFilename = None
        
        ## Optimizations
        # LAME: maintain a cached file name displayed in the scrolling UI, and whether or
        # not the cached name might be stale (might be stale = a temporary name). 
        self.showFilename = None
        self.showFilenameIsTemp = False
        
        # direct pointer to the first segment of this file, when we have a tempFilename we
        # look at this segment frequently until we find the real file name
        # FIXME: this most likely doesn't optimize for shit.
        self.firstSegment = None

        # LAME: re-entrant lock for maintaing temp filenames/renaming temp -> real file
        # names in separate threads. FIXME: This is a lot of RLock() construction, it
        # should be removed eventually
        self.tempFileNameLock = RLock() # this isn't used right
        # filename could be modified/accessed concurrently (getDestination called by the
        # downloader doesnt lock).
        # NOTE: maybe just change nzbFile.filename via the reactor (callFromThread), and
        # remove the lock entirely?

        self.forcedChangedFilename = False

        self.isParFile = False
        self.isExtraParFile = False
        self.isSkippedPar = False

    def getDestination(self):
        """ Return the full pathname of where this NZBFile should be written to on disk """
        return self.nzb.destDir + os.sep + self.getFilename()

    def getFilename(self):
        """ Return the filename of where this NZBFile will reside on the filesystem, within the
        WORKING_DIR (not a full path)

        The filename information is grabbed from the first segment's articleData
        (uuencode's fault -- yencode includes the filename in every segment's
        articleData). In the case where we need this file's filename filename, and that
        first segment doesn't have articleData (hasn't been downloaded yet), a temp
        filename will be returned

        Downloading segments out of order often occurs in hellanzb, thus the need for
        temporary file names """
        if self.filename is not None:
            # We've determined the real filename (or the last filename we're ever going to
            # get)
            return self.filename
        
        elif self.firstSegment is not None and self.firstSegment.articleData is not None:
            # No real filename yet, but we should be able to determine it from the first
            # segment's article data
            try:
                # getFilenameFromArticleData will either set our self.filename when
                # successful, or raise a FatalError
                self.firstSegment.getFilenameFromArticleData()
            except Exception, e:
                debug('getFilename: Unable to getFilenameFromArticleData: file number: %i: %s' % \
                      (self.number, str(e)))
                
            if self.filename is None:
                # We only check the first segment for a real filename (FIXME: looking at
                # any yDecode segment for the real filename would be nice). If we had
                # trouble finding it there -- force this file to use the temp filename
                # throughout its lifetime
                self.filename = self.getTempFileName()
                
            return self.filename

        elif self.tempFilename is not None:
            # We can't get the real filename yet -- use the already cached tempFilename
            # for now (NOTE: caching this is really unnecessary)
            return self.tempFilename

        # We can't get the real filename yet, cache the temp filename and use it for now
        self.tempFilename = self.getTempFileName()
        return self.tempFilename

    def needsDownload(self, workingDirListing, workingDirDupeMap):
        """ Whether or not this NZBFile needs to be downloaded (isn't on the file system). You may
        specify the optional workingDirListing so this function does not need to prune
        this directory listing every time it is called (i.e. prune directory
        names). workingDirListing should be a list of only filenames (basename, not
        including dirname) of files lying in Hellanzb.WORKING_DIR """
        if os.path.isfile(self.getDestination()):
            # This block only handles matching temporary file names
            return False

        elif self.filename == None:
            # First, check if this is one of the dupe files on disk
            isDupe, dupeNeedsDl = handleDupeNZBFileNeedsDownload(self, workingDirDupeMap)
            if isDupe:
                # FIXME: do we need to identifyPar here?
                return dupeNeedsDl

            # We only know about the temp filename. In that case, fall back to matching
            # filenames in our subject line
            for file in workingDirListing:
                # Whole file match
                if self.subject.find(file) > -1:
                    # No need for setRealFileName(self, file)'s extra work here
                    self.filename = file
                    
                    identifyPar(self)
                    if self.isParFile:
                        debug('needsDownload: Found par on disk: %s isExtraParFile: %s' % \
                              (file, str(self.isExtraParFile)))
                        
                    return False
    
        return True

    def getTempFileName(self):
        """ Generate a temporary filename for this file, for when we don't have it's actual file
        name on hand """
        return 'hellanzb-tmp-' + self.nzb.archiveName + '.file' + str(self.number).zfill(4)

    def isAllSegmentsDecoded(self):
        """ Determine whether all these file's segments have been decoded """
        return not len(self.todoNzbSegments)

    #def __repr__(self):
    #    msg = 'nzbFile: ' + os.path.basename(self.getDestination())
    #    if self.filename != None:
    #        msg += ' tempFileName: ' + self.getTempFileName()
    #    msg += ' number: ' + str(self.number) + ' subject: ' + \
    #           self.subject
    #    return msg

class NZBSegment:
    """ <file><segment/></file> """
    
    def __init__(self, bytes, number, messageId, nzbFile):
        ## XML attributes
        self.bytes = bytes
        self.number = number
        self.messageId = messageId

        ## XML tree-collections/references
        # Reference to the parent NZBFile this segment belongs to
        self.nzbFile = nzbFile

        # This segment belongs to the parent nzbFile
        self.nzbFile.nzbSegments.append(self)
        self.nzbFile.todoNzbSegments.add(self)
        self.nzbFile.totalBytes += self.bytes
        self.nzbFile.nzb.totalBytes += self.bytes

        ## To-be a file object. Downloaded article data will be written to this file
        ## immediately as it's received from the other end
        self.encodedData = None
        
        ## Downloaded article data stored as an array of lines whose CRLFs are stripped
        self.articleData = None

        ## yEncoder header keywords used for validation. Optional, obviously not used for
        ## UUDecoded segments
        self.yCrc = None # Not the original crc (upper()'d and lpadded with 0s)
        self.yBegin = None
        self.yEnd = None
        self.ySize = None

        ## A copy of the priority level of this segment, as set in the NZBQueue
        self.priority = None

        ## Any server pools that failed to download this file
        self.failedServerPools = []

        # This flag is set when we want to trash the NZB and prevent the leechers from
        # trying to requeue it
        self.dontRequeue = False

    def getDestination(self):
        """ Where this decoded segment will reside on the fs """
        return self.nzbFile.getDestination() + '.segment' + str(self.number).zfill(4)
    
    def getTempFileName(self):
        """ """
        return self.nzbFile.getTempFileName() + '.segment' + str(self.number).zfill(4)

    def getFilenameFromArticleData(self):
        """ Determine the segment's filename via the articleData """
        parseArticleData(self, justExtractFilename = True)
        
        if self.nzbFile.filename == None and self.nzbFile.tempFilename == None:
            raise FatalError('Could not getFilenameFromArticleData, file:' + str(self.nzbFile) +
                             ' segment: ' + str(self))

    def loadArticleDataFromDisk(self, removeFromDisk = True):
        """ Load the previously downloaded article BODY from disk, as a list to the .articleData
        variable """
        # downloaded encodedData was written to disk by NZBLeecher
        encodedData = open(Hellanzb.DOWNLOAD_TEMP_DIR + os.sep + self.getTempFileName() + '_ENC')
        # remove crlfs. FIXME: might be quicker to do this during a later loop
        self.articleData = [line[:-2] for line in encodedData.readlines()]
        encodedData.close()

        if removeFromDisk:
            # Delete the copy on disk ASAP
            nuke(Hellanzb.DOWNLOAD_TEMP_DIR + os.sep + self.getTempFileName() + '_ENC')

    #def __repr__(self):
    #    return 'segment: ' + os.path.basename(self.getDestination()) + ' number: ' + \
    #           str(self.number) + ' subject: ' + self.nzbFile.subject

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
