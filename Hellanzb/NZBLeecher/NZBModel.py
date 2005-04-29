"""

NZBModel - Representations of the NZB file format in memory

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import Hellanzb, os, re, time
from sets import Set
from threading import Lock, RLock
from twisted.internet import reactor
from xml.sax import make_parser, SAXParseException
from xml.sax.handler import ContentHandler, feature_external_ges, feature_namespaces
from Hellanzb.Daemon import handleNZBDone
from Hellanzb.Log import *
from Hellanzb.NZBLeecher.ArticleDecoder import assembleNZBFile, parseArticleData, setRealFileName, tryFinishNZB
from Hellanzb.Util import archiveName, getFileExtension, PriorityQueue

__id__ = '$Id$'

segmentEndRe = re.compile(r'^segment\d{4}$')
# FIXME: i believe needsDownload just needs to work for files now
def needsDownload(object, threadRealNameWork = False):
    """ Whether or not this object needs to be downloaded (isn't on the file system). This
    function is generalized to support both NZBFile and NZBSegment objects. A NZBFile
    needs to be downloaded when it's file does not exist on the filesystem. An NZBSegment
    needs to be downloaded when either it's segment file, or it's parent NZBFile's file
    does not exist on the filesystem. This function does some magic to handle
    tempFileNames """
    start = time.time()
    # We need to ensure that we're not in the process of renaming from a temp file
    # name, so we have to lock.
    isSegment = isinstance(object, NZBSegment)
    if isSegment:
        filename = object.nzbFile.filename
        subject = object.nzbFile.subject
        tempFileNameLock = object.nzbFile.tempFileNameLock
    else:
        filename = object.filename
        subject = object.subject
        tempFileNameLock = object.tempFileNameLock

    tempFileNameLock.acquire()

    if os.path.isfile(object.getDestination()):
        tempFileNameLock.release()
        end = time.time() - start
        debug('needsDownload took: ' + str(end))
        return False

    elif filename == None:
        # We only know about the temp filename. In that case, fall back to matching
        # filenames in our subject line
        for file in os.listdir(Hellanzb.WORKING_DIR):
            ext = getFileExtension(file)

            # Segment Match
            if isSegment and ext != None and segmentEndRe.match(ext):

                # Quickest/easiest way to determine this file is not this segment's
                # file is by checking it's segment number
                segmentNumber = int(file[-4:])
                if segmentNumber != object.number:
                    continue

                # Strip the segment suffix, and if that filename is in our subject,
                # we've found a match
                prefix = file[0:-len('.segmentXXXX')]
                if object.nzbFile.subject.find(prefix) > -1:
                    # HACK: filename is None. so we only have the temporary name in
                    # memory. since we didnt see the temporary name on the filesystem, but
                    # we found a subject match, that means we have the real name on the
                    # filesystem. In the case where this happens, and we are segment #1,
                    # we've figured out the real filename (hopefully!)
                    if object.number == 1:
                        #debug('needsDownload: GOT real file name from PREFIX! ')
                        if threadRealNameWork:
                            reactor.callInThread(setRealFileName, object, prefix)
                        else:
                            setRealFileName(object, prefix)

                    tempFileNameLock.release()
                    end = time.time() - start
                    debug('needsDownload took: ' + str(end))
                    return False

            # Whole file match #FIXME: for segments this needs to be file minus the .segment suffix
            elif subject.find(file) > -1:
                tempFileNameLock.release()
                end = time.time() - start
                debug('needsDownload took: ' + str(end))
                return False

    tempFileNameLock.release()
    end = time.time() - start
    debug('needsDownload took: ' + str(end))
    return True

def segmentsNeedDownload(segmentList):
    """ Faster version of needsDownload for multiple segments that do not have their real file
    name (for use by the Queue) """
    # Arrange all WORKING_DIR segment's filenames in a list. Key this list by segment
    # number in a map. Loop through the specified segmentList, doing a subject.find for
    # each segment filename with a matching segment number

    segmentsByNumber = {}
    needsDownloading = []
    needsDownloadingFiles = Set()
    onDisk = []

    # Cache all WORKING_DIR segment filenames in a map of lists
    for file in os.listdir(Hellanzb.WORKING_DIR):
        ext = getFileExtension(file)
        if ext != None and segmentEndRe.match(ext):
            segmentNumber = int(ext[-4:])
            
            if segmentsByNumber.has_key(segmentNumber):
                segmentFileNames = segmentsByNumber[segmentNumber]
            else:
                segmentFileNames = []
                segmentsByNumber[segmentNumber] = segmentFileNames

            # cut off .segmentXXXX
            fileNoExt = file[:-12]
            segmentFileNames.append(fileNoExt)

    # Determine if each segment needs to be downloaded
    for segment in segmentList:

        if not segmentsByNumber.has_key(segment.number):
            # No matching segment numbers, obviously needs to be downloaded
            needsDownloading.append(segment)
            needsDownloadingFiles.add(segment.nzbFile)
            continue

        segmentFileNames = segmentsByNumber[segment.number]
        
        foundFileName = None
        for segmentFileName in segmentFileNames:
            # FIXME: should prbobably check if they match the tempfilename as well
            if segment.nzbFile.subject.find(segmentFileName) > -1:
                foundFileName = segmentFileName
                break

        if not foundFileName:
            needsDownloading.append(segment)
            needsDownloadingFiles.add(segment.nzbFile)
        else:
            # FIXME: when we start checking for tempfilename we have to check here as well
            # before setReal
            if segment.number == 1:
                # HACK: filename is None. so we only have the temporary name in
                # memory. since we didnt see the temporary name on the filesystem, but
                # we found a subject match, that means we have the real name on the
                # filesystem. In the case where this happens, and we are segment #1,
                # we've figured out the real filename (hopefully!)
                setRealFileName(segment, foundFileName)
                
            onDisk.append(segment)
        #else:
        #    debug('SKIPPING SEGMENT: ' + segment.getTempFileName() + ' subject: ' + \
        #          segment.nzbFile.subject)

    return needsDownloading, onDisk, needsDownloadingFiles

class NZB:
    """ Representation of an nzb file -- the root <nzb> tag """
    def __init__(self, nzbFileName):
        self.nzbFileName = nzbFileName
        self.archiveName = archiveName(self.nzbFileName)
        self.nzbFileElements = []
        
class NZBFile:
    """ <nzb><file/><nzb> """
    needsDownload = needsDownload

    def __init__(self, subject, date = None, poster = None, nzb = None):
        # from xml attributes
        self.subject = subject
        self.date = date
        self.poster = poster
        
        # Parent NZB
        self.nzb = nzb
        # FIXME: thread safety?
        self.nzb.nzbFileElements.append(self)
        
        self.groups = []
        self.nzbSegments = []

        self.number = len(self.nzb.nzbFileElements)
        self.totalBytes = 0
        self.totalSkippedBytes = 0

        # The real filename, determined from the actual decoded articleData
        self.filename = None
        # The filename used temporarily until the real filename is determined
        self.tempFilename = None

        # direct pointer to the first segment of this file, when we have a tempFilename we
        # look at this segment frequently until we find the real file name
        self.firstSegment = None

        # re-entrant lock for maintaing temp filenames/renaming temp -> real file names in
        # separate threads. FIXME: This is a lot of RLock() construction
        self.tempFileNameLock = RLock()

        # LAME: maintain a cached name we display in the UI, and whether or not the cached
        # name might be stale (might be stale = a temporary name)
        self.showFilename = None
        self.showFilenameIsTemp = False

        # FIXME: more UI junk
        self.downloadStartTime = None
        self.totalReadBytes = 0
        self.downloadPercentage = 0
        self.speed = 0

    def getDestination(self):
        """ Return the destination of where this file will lie on the filesystem. The filename
        information is grabbed from the first segment's articleData (uuencode's fault --
        yencode includes the filename in every segment's articleData). In the case where a
        segment needs to know it's filename, and that first segment doesn't have
        articleData (hasn't been downloaded yet), a temp filename will be
        returned. Downloading segments out of order can easily occur in app like hellanzb
        that downloads the segments in parallel """
        try:
            # FIXME: try = slow. just simply check if tempFilename exists after
            # getFilenamefromArticleData. does exactly the same thing w/ no try. should probably
            # looked at the 2nd revised version of this and make sure it's still as functional as
            # the original
            if self.filename != None:
                return Hellanzb.WORKING_DIR + os.sep + self.filename
            elif self.tempFilename != None and self.firstSegment.articleData == None:
                return Hellanzb.WORKING_DIR + os.sep + self.tempFilename
            else:
                # FIXME: i should only have to call this once after i get article
                # data. that is if it fails, it should set the real filename to the
                # incorrect tempfilename
                self.firstSegment.getFilenameFromArticleData()
                return Hellanzb.WORKING_DIR + os.sep + self.tempFilename
        except AttributeError:
            self.tempFilename = self.getTempFileName()
            return Hellanzb.WORKING_DIR + os.sep + self.tempFilename

    def getTempFileName(self):
        """ Generate a temporary filename for this file, for when we don't have it's actual file
        name on hand """
        return 'hellanzb-tmp-' + self.nzb.archiveName + '.file' + str(self.number).zfill(4)

    def isAllSegmentsDecoded(self):
        """ Determine whether all these file's segments have been decoded """
        start = time.time()

        decodedSegmentFiles = []
        for nzbSegment in self.nzbSegments:
            decodedSegmentFiles.append(os.path.basename(nzbSegment.getDestination()))

        dirName = os.path.dirname(self.getDestination())
        for file in os.listdir(dirName):
            if file in decodedSegmentFiles:
                decodedSegmentFiles.remove(file)

        # Just be stupid -- we're only finished until we've found all the known files
        # (segments)
        if len(decodedSegmentFiles) == 0:
            finish = time.time() - start
            #debug('isAllSegmentsDecoded (True) took: ' + str(finish) + ' ' + self.getDestination())
            return True

        finish = time.time() - start
        #debug('isAllSegmentsDecoded (False) took: ' + str(finish) + ' ' + self.getDestination())
        return False

    def __repr__(self):
        msg = 'nzbFile: ' + os.path.basename(self.getDestination())
        if self.filename != None:
            msg += ' tempFileName: ' + self.getTempFileName()
        msg += ' number: ' + str(self.number) + ' subject: ' + \
               self.subject
        return msg

class NZBSegment:
    """ <file><segment/></file> """
    needsDownload = needsDownload
    
    def __init__(self, bytes, number, messageId, nzbFile):
        # from xml attributes
        self.bytes = bytes
        self.number = number
        self.messageId = messageId

        # Reference to the parent NZBFile this segment belongs to
        self.nzbFile = nzbFile

        # This segment belongs to the parent nzbFile
        self.nzbFile.nzbSegments.append(self)
        self.nzbFile.totalBytes += self.bytes

        # The downloaded article data
        self.articleData = None

        # the CRC value specified by the downloaded yEncode data, if it exists
        self.crc = None

        # copy of the priority as set in the Queue
        self.priority = None

    def getDestination(self):
        """ Where this decoded segment will reside on the fs """
        return self.nzbFile.getDestination() + '.segment' + str(self.number).zfill(4)
    
    def getTempFileName(self):
        """ """
        return self.nzbFile.getTempFileName() + '.segment' + str(self.number).zfill(4)

    def getFilenameFromArticleData(self):
        """ Determine the segment's filename via the articleData """
        # The first segment marshalls setting of the parent nzbFile.tempFilename, which
        # all other segments will end up using when they call
        # getDestination(). tempFilename is only used when that first segment lacks
        # articleData and can't determine the real filename
        
        #if self.articleData == None and self.number == 1:
        #    self.nzbFile.tempFilename = self.nzbFile.getTempFileName()
        #    return

        # We have article data, get the filename from it
        parseArticleData(self, justExtractFilename = True)
        
        if self.nzbFile.filename == None and self.nzbFile.tempFilename == None:
            raise FatalError('Could not getFilenameFromArticleData, file:' + str(self.nzbFile) +
                             ' segment: ' + str(self))

    def __repr__(self):
        return 'segment: ' + os.path.basename(self.getDestination()) + ' number: ' + \
               str(self.number) + ' subject: ' + self.nzbFile.subject

class NZBQueue(PriorityQueue):
    """ priority fifo queue of segments to download. lower numbered segments are downloaded
    before higher ones """
    NZB_CONTENT_P = 100000 # normal nzb downloads
    EXTRA_PAR2_P = 0 # par2 after-the-fact downloads are more important

    def __init__(self, fileName = None):
        PriorityQueue.__init__(self)

        # Maintain a collection of the known nzbFiles belonging to the segments in this
        # queue. Set is much faster for _put & __contains__
        self.nzbFiles = Set()
        self.nzbFilesLock = Lock()
        
        self.totalQueuedBytes = 0

        if fileName is not None:
            self.parseNZB(fileName)

    def _put(self, item):
        """ """
        priority, item = item

        # Support adding NZBFiles to the queue. Just adds all the NZBFile's NZBSegments
        if isinstance(item, NZBFile):
            for nzbSegment in item.nzbSegments:
                PriorityQueue._put(self, nzbSegment)

        else:
            # Assume segment, add to list
            if item.nzbFile not in self.nzbFiles:
                self.nzbFiles.add(item.nzbFile)
            PriorityQueue._put(self, item)

    def calculateTotalQueuedBytes(self):
        """ Calculate how many bytes are queued to be downloaded in this queue """
        # NOTE: we don't maintain this calculation all the time, too much CPU work for
        # _put
        self.nzbFilesLock.acquire()
        files = self.nzbFiles.copy()
        self.nzbFilesLock.release()
        for nzbFile in files:
            self.totalQueuedBytes += nzbFile.totalBytes

    def fileDone(self, nzbFile):
        """ Notify the queue a file is done. This is called after assembling a file into it's
        final contents. Segments are really stored independantly of individual Files in
        the queue, hence this function """
        self.nzbFilesLock.acquire()
        if nzbFile in self.nzbFiles:
            self.nzbFiles.remove(nzbFile)
        self.nzbFilesLock.release()
        self.totalQueuedBytes -= nzbFile.totalBytes

    def parseNZB(self, fileName):
        """ Initialize the queue from the specified nzb file """
        # Create a parser
        parser = make_parser()
        
        # No XML namespaces here
        parser.setFeature(feature_namespaces, 0)
        parser.setFeature(feature_external_ges, 0)
        
        # Create the handler
        nzb = NZB(fileName)
        interimQueue = []
        interimQueueNzbFiles = Set()
        dh = NZBParser(interimQueue, interimQueueNzbFiles, nzb)
        
        # Tell the parser to use it
        parser.setContentHandler(dh)

        # Parse the input
        try:
            parser.parse(fileName)
        except SAXParseException, saxpe:
            raise FatalError('Unable to parse Invalid NZB file: ' + os.path.basename(fileName))
        
        completeArchive = False
        debug('interimQueue: ' + str(len(interimQueue)) + ' has: ' + str(interimQueue))
        debug('interimQueueNzbFiles: ' + str(len(interimQueueNzbFiles)) + ' has: ' + str(interimQueueNzbFiles))

        s = time.time()
        # The parser will add all the segments of all the NZBFiles that have not already
        # been downloaded. After the parsing, we'll check if each of those segments have
        # already been downloaded. it's faster to check all segments at one time
        needsDownloading, onDisk, needsDownloadingFiles = segmentsNeedDownload(interimQueue)
        e = time.time() - s
        debug('segmentsNeedDownload TOOK: ' + str(e))
        debug('needsDownloading: ' + str(len(needsDownloading)) + ' has: ' + str(needsDownloading))
        debug('onDisk: ' + str(len(onDisk)) + ' has: ' + str(onDisk))
        debug('needsDownloadingFiles: ' + str(len(needsDownloadingFiles)) + ' has: ' +  str(needsDownloadingFiles))

        # The interimQueue will tell us what nzbFiles are missing from the
        # FS. segmentsNeedDownload will further tell us what files need to be
        # downloaded. files missing from the FS (interimQueue) but not needing to be
        # downloaded (in needsDownloadingFiles) simply need to be assembled
        for nzbFile in interimQueueNzbFiles:
            if nzbFile not in needsDownloadingFiles:
                # Don't automatically 'finish' the NZB, we'll take care of that in this
                # function if necessary
                debug('assembling: ' + str(nzbFile.subject))
                assembleNZBFile(nzbFile, autoFinish = False)

        if not len(needsDownloading):
            # FIXME: this block of code is the end of tryFinishNZB. there should be a
            # separate function
            # nudge GC?
            nzbFileName = nzb.nzbFileName
            del nzb
            reactor.callLater(0, handleNZBDone, nzbFileName)
            # True == the archive is complete
            return True

        for nzbSegment in needsDownloading:
            debug('putting: ' + str(nzbSegment.priority) + ' segment subject: ' + nzbSegment.nzbFile.subject + \
                  ' number: ' + str(nzbSegment.number) + ' temp: ' + nzbSegment.getTempFileName())
            self.put((nzbSegment.priority, nzbSegment))

        # Tally what was skipped for correct percentages in the UI
        for nzbSegment in onDisk:
            nzbSegment.nzbFile.totalSkippedBytes += nzbSegment.bytes
        
        self.calculateTotalQueuedBytes()

        # Archive not complete
        return False
        
class NZBParser(ContentHandler):
    """ Parse an NZB 1.0 file into an NZBQueue
    http://www.newzbin.com/DTD/nzb/nzb-1.0.dtd """
    def __init__(self, queue, queueNzbFiles, nzb):
        # downloading queue to add NZB segments to
        self.queue = queue
        self.queueNzbFiles = queueNzbFiles

        # nzb file to parse
        self.nzb = nzb

        # parsing variables
        self.file = None
        self.bytes = None
        self.number = None
        self.chars = None
        self.fileNeedsDownload = None
        
        self.fileCount = 0
        self.segmentCount = 0

    def startElement(self, name, attrs):
        if name == 'file':
            subject = self.parseUnicode(attrs.get('subject'))
            poster = self.parseUnicode(attrs.get('poster'))

            self.file = NZBFile(subject, attrs.get('date'), poster, self.nzb)
            self.fileNeedsDownload = self.file.needsDownload()
            if not self.fileNeedsDownload:
                debug('SKIPPING FILE: ' + self.file.getTempFileName() + ' subject: ' + \
                      self.file.subject)

            self.fileCount += 1
            self.file.number = self.fileCount
                
        elif name == 'group':
            self.chars = []
                        
        elif name == 'segment':
            self.bytes = int(attrs.get('bytes'))
            self.number = int(attrs.get('number'))
                        
            self.chars = []
        
    def characters(self, content):
        if self.chars is not None:
            self.chars.append(content)
        
    def endElement(self, name):
        if name == 'file':
            if self.fileNeedsDownload:
                self.queueNzbFiles.add(self.file)
            
            self.file = None
            self.fileNeedsDownload = None
                
        elif name == 'group':
            newsgroup = ''.join(self.chars)
            self.file.groups.append(newsgroup)
                        
            self.chars = None
                
        elif name == 'segment':
            self.segmentCount += 1

            messageId = self.parseUnicode(''.join(self.chars))
            nzbs = NZBSegment(self.bytes, self.number, messageId, self.file)
            if self.segmentCount == 1:
                self.file.firstSegment = nzbs

            if self.fileNeedsDownload:
                # HACK: Maintain the order in which we encountered the segments by adding
                # segmentCount to the priority. lame afterthought -- after realizing
                # heapqs aren't ordered. NZB_CONTENT_P must now be large enough so that it
                # won't ever clash with EXTRA_PAR2_P + i
                nzbs.priority = NZBQueue.NZB_CONTENT_P + self.segmentCount
                self.queue.append(nzbs)

            self.chars = None
            self.number = None
            self.bytes = None    

    def parseUnicode(self, unicodeOrStr):
        if isinstance(unicodeOrStr, unicode):
            return unicodeOrStr.encode('latin-1')
        return unicodeOrStr
        
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
