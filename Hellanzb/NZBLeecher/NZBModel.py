"""

NZBModel - Representations of the NZB file format in memory

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import os, re, Hellanzb
try:
    set
except NameError:
    from sets import Set as set
from shutil import move
from threading import Lock, RLock
from Hellanzb.Log import *
from Hellanzb.NZBQueue import writeStateXML
from Hellanzb.Util import IDPool, UnicodeList, archiveName, getFileExtension, getMsgId, \
    hellaRename, isHellaTemp, nuke, toUnicode
from Hellanzb.NZBLeecher.ArticleDecoder import parseArticleData, setRealFileName, tryAssemble
from Hellanzb.NZBLeecher.DupeHandler import handleDupeNZBFileNeedsDownload
from Hellanzb.NZBLeecher.NZBLeecherUtil import validWorkingFile
from Hellanzb.PostProcessorUtil import Archive, getParEnum, getParName
from Hellanzb.SmartPar import identifyPar, logSkippedPars, smartDequeue, smartRequeue

__id__ = '$Id$'

class NZB(Archive):
    """ Representation of an nzb file -- the root <nzb> tag """
    
    def __init__(self, nzbFileName, id = None, rarPassword = None, archiveDir = None,
                 category = ''):
        Archive.__init__(self, archiveDir, id, None, rarPassword)
            
        ## NZB file general information
        self.nzbFileName = nzbFileName
        self.archiveName = archiveName(self.nzbFileName) # pretty name
        self.msgid = None
        filename = os.path.basename(nzbFileName)
        self.msgid = getMsgId(filename)
        if self.msgid:
            self.msgid = int(self.msgid)
        self.nzbFiles = []
        self.skippedParFiles = []
        self.category = category

        ## Where the nzb files will be downloaded
        self.destDir = Hellanzb.WORKING_DIR

        ## A cancelled NZB is marked for death. ArticleDecoder will dispose of any
        ## recently downloaded data that might have been downloading during the time the
        ## cancel call was made (after the fact cleanup)
        self.canceled = False
        self.canceledLock = Lock()

        ## Acquired during assembly of an NZBFile
        self.assembleLock = Lock()

        ## Total bytes this NZB represents
        self.totalBytes = 0

        ## Whether the total byte count of this NZB is still being calculated
        self.calculatingBytes = True
        
        ## How many bytes were skipped for downloading
        self.totalSkippedBytes = 0
        ## How many bytes have been downloaded for this NZB
        self.totalReadBytes = 0
        ## Time this NZB began downloading
        self.downloadStartTime = None
        ## Amount of time taken to download the NZB
        self.downloadTime = None

        ## Whether or not we should redownload NZBFile and NZBSegment files on disk that
        ## are 0 bytes in size
        self.overwriteZeroByteFiles = True

        # All segment0001s are downloaded first. Every time we successfully decode a
        # segment0001, we add to this number
        self.firstSegmentsDownloaded = 0

        ## Whether or not this NZB is downloading in par recovery mode
        self.isParRecovery = False
        ## Whether or not this is an NZB that contains all par files
        self.allParsMode = False
        ## Skipped par file's subjects are kept here, in a list, during post
        ## processing. This list is arranged by the file's size
        self.skippedParSubjects = None
        ## The number of par blocks (or par files for par1 mode), queued to download
        ## recovery blocks, the par version, and the par prefix for the current par
        ## recovery download
        self.neededBlocks = 0
        self.queuedBlocks = 0
        self.parType = None
        self.parPrefix = None
        
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

    def postpone(self):
        """ Postpone an active NZB """
        assert self in Hellanzb.queue.currentNZBs(), \
            'Attempting to postpone an NZB not actively being downloaded: %s' % self.archiveName
        postponed = os.path.join(Hellanzb.POSTPONED_DIR, self.archiveName)
        hellaRename(postponed)
        os.mkdir(postponed)

        self.assembleLock.acquire()
        try:
            self.destDir = postponed

            move(self.nzbFileName, os.path.join(Hellanzb.QUEUE_DIR,
                                                os.path.basename(self.nzbFileName)))
            self.nzbFileName = os.path.join(Hellanzb.QUEUE_DIR,
                                            os.path.basename(self.nzbFileName))
            Hellanzb.nzbQueue.insert(0, self)
            writeStateXML()

            # Move the postponed files to the new postponed dir
            for file in os.listdir(Hellanzb.WORKING_DIR):
                move(os.path.join(Hellanzb.WORKING_DIR, file), os.path.join(postponed, file))
        finally:
            self.assembleLock.release()
            
    def isAllPars(self):
        """ Determine whether or not all nzbFiles in this archive are par files. An NZB only
        containing par files needs to be specially handled (all its nzbFiles should be
        downloaded, instead of skipped) -- otherwise, no downloading would occur. This
        situation isn't applicable to isParRecovery downloads

        All nzbFiles in this NZB should have their real filename for the results of this
        function to be accurate

        newzbin.com will always add the .nfo file to an NZB if it exists (even if you
        didn't select it for download) -- this function attempts to take that into account
        """
        if self.isParRecovery:
            return False

        skippedLen = len(self.skippedParFiles)
        nzbFilesLen = len(self.nzbFiles)
        
        if skippedLen == nzbFilesLen:
            return True

        if (skippedLen > 0 and skippedLen == nzbFilesLen - 1) or \
                (skippedLen > 1 and skippedLen == nzbFilesLen - 2):
            # We only queued 1 or 2 files for download. If both are either a main par file
            # or a .nfo file, this is an all par archive
            queuedFiles = [nzbFile for nzbFile in self.nzbFiles if nzbFile not \
                           in self.skippedParFiles]
            for queuedFile in queuedFiles[:]:
                if queuedFile.filename.lower().endswith('.nfo') or queuedFile.isPar:
                    queuedFiles.remove(queuedFile)
                    
            return not len(queuedFiles)

        return False

    def cleanStats(self):
        """ Reset downlaod statistics """
        self.allParsMode = False
        self.totalBytes = 0
        self.totalSkippedBytes = 0
        self.totalReadBytes = 0
        self.firstSegmentsDownloaded = 0
        ##self.neededBlocks = 0 # ?
        self.queuedBlocks = 0
        for nzbFile in self.nzbFiles:
            nzbFile.totalSkippedBytes = 0
            nzbFile.totalReadBytes = 0
            nzbFile.downloadPercentage = 0
            nzbFile.speed = 0
            nzbFile.downloadStartTime = None

    def finalize(self, justClean = False):
        """ Delete any potential cyclic references existing in this NZB, then garbage
        collect. justClean will only clean/delete specific things, to prep the NZB for
        another download """
        # nzbFiles aren't needed for another download
        for nzbFile in self.nzbFiles:
            # The following two sets used to be del'd. This was changed in r961
            # for the associated ticket; but the fix is really a bandaid. If
            # the root cause is mitigated, go back to del
            if justClean:
                nzbFile.todoNzbSegments.clear()
                nzbFile.dequeuedSegments.clear()
            else:
                del nzbFile.todoNzbSegments
                del nzbFile.dequeuedSegments
                del nzbFile.nzb
                del nzbFile

        if justClean:
            self.nzbFiles = []
            self.skippedParFiles = []
            self.postProcessor = None
            self.cleanStats()
        else:
            del self.nzbFiles
            del self.skippedParFiles
            del self.postProcessor

    def getSkippedParSubjects(self):
        """ Return a list of skipped par file's subjects, sorted by the size of the par """
        unsorted = []
        for nzbFile in self.nzbFiles:
            if nzbFile.isSkippedPar:
                unsorted.append((nzbFile.totalBytes, nzbFile.subject))
        # Ensure the list of pars is sorted by the par's number of bytes (so we pick off
        # the smallest ones first when doing a par recovery download)
        unsorted.sort()
        sorted = UnicodeList()
        for bytes, subject in unsorted:
            sorted.append(subject)
        return sorted

    def isSkippedParSubject(self, subject):
        """ Determine whether the specified subject is that of a known skipped par file """
        if self.skippedParSubjects is None:
            return False
        return toUnicode(subject) in self.skippedParSubjects

    def getName(self):
        return os.path.basename(self.archiveName)

    def getPercentDownloaded(self):
        """ Return the percentage of this NZB that has already been downloaded """
        if self.totalBytes == 0:
            return 0
        else:
            # FIXME: there are two ways of getting this value, either from the NZB
            # statistics or from the queue statistics. There should really only be one way..?
            return int((float(self.totalReadBytes + self.totalSkippedBytes) / \
                                   float(self.totalBytes)) * 100)

    def getETA(self):
        """ Return the amount of time needed to finish downloadling this NZB at the current rate
        """
        currentRate = Hellanzb.getCurrentRate()
        if self.totalBytes == 0 or currentRate == 0:
            return 0
        else:
            return int(((self.totalBytes - self.totalReadBytes - self.totalSkippedBytes) \
                       / 1024) / currentRate)

    def getStateAttribs(self):
        """ Return attributes to be written out to the """
        attribs = Archive.getStateAttribs(self)

        # NZBs in isParRecovery mode need the par recovery state written
        if self.isParRecovery:
            attribs['isParRecovery'] = 'True'
            for attrib in ('neededBlocks', 'parPrefix'):
                val = getattr(self, attrib)
                if isinstance(val, int):
                    val = str(val)
                attribs[attrib] = toUnicode(val)
            attribs['parType'] = getParName(self.parType)

        if self.downloadTime:
            attribs['downloadTime'] = str(self.downloadTime)
        if not self.calculatingBytes and self.totalBytes > 0:
            attribs['totalBytes'] = str(self.totalBytes)
        if self.category:
            attribs['category'] = self.category

        return attribs

    def toStateXML(self, xmlWriter):
        """ Write a brief version of this object to an elementtree.SimpleXMLWriter.XMLWriter """
        attribs = self.getStateAttribs()
        if self in Hellanzb.queue.currentNZBs():
            type = 'downloading'
        elif self.postProcessor is not None and \
                self.postProcessor in Hellanzb.postProcessors:
            type = 'processing'
            attribs['nzbFileName'] = os.path.basename(self.nzbFileName)
        elif self in Hellanzb.nzbQueue:
            type = 'queued'
        else:
            return
        
        xmlWriter.start(type, attribs)
        if type != 'downloading' or self.isParRecovery:
            # Write 'skippedPar' tags describing the known skipped par files that haven't
            # been downloaded
            if self.skippedParSubjects is not None:
                for nzbFileName in self.skippedParSubjects:
                    xmlWriter.element('skippedPar', nzbFileName)
            else:
                for skippedParFileSubject in self.getSkippedParSubjects():
                    xmlWriter.element('skippedPar', skippedParFileSubject)
        xmlWriter.end(type)

    def fromStateXML(type, target):
        """ Factory method, returns a new NZB object for the specified target, and recovers
        the NZB state from the RecoveredState object if the target exists there for
        the specified type (such as 'processing', 'downloading') """
        if type == 'processing':
            recoveredDict = Hellanzb.recoveredState.getRecoveredDict(type, target)
            archiveDir = os.path.join(Hellanzb.PROCESSING_DIR, target)
            if recoveredDict and recoveredDict.get('nzbFileName') is not None:
                target = recoveredDict.get('nzbFileName')
            else:
                # If this is a processing recovery request, and we didn't recover any
                # state information, we'll consider this a basic Archive object (it has no
                # accompanying .NZB file to keep track of)
                return Archive.fromStateXML(archiveDir, recoveredDict)
        else:
            recoveredDict = Hellanzb.recoveredState.getRecoveredDict(type,
                                                                     archiveName(target))

        # Pass the id in with the constructor (instead of setting it after the fact) --
        # otherwise the constructor would unnecessarily incremenet the IDPool
        nzbId = None
        if recoveredDict:
            nzbId = recoveredDict['id']

        nzb = NZB(target, nzbId)
        
        if type == 'processing':
            nzb.archiveDir = archiveDir
        
        if recoveredDict:
            for key, value in recoveredDict.iteritems():
                if key == 'id' or key == 'order':
                    continue
                if key == 'neededBlocks':
                    value = int(value)
                if key == 'totalBytes':
                    nzb.calculatingBytes = False
                    value = int(value)
                if key == 'downloadTime':
                    value = float(value)
                if key == 'parType':
                    value = getParEnum(value)
                setattr(nzb, key, value)

        return nzb
    fromStateXML = staticmethod(fromStateXML)

    def smartRequeue(self):
        """ Shortcut to the SmartPar function of the same name """
        smartRequeue(self)
        
    def logSkippedPars(self):
        """ Shortcut to the SmartPar function of the same name """
        logSkippedPars(self)
        
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
        self.nzb.nzbFiles.append(self)
        
        self.groups = []
        self.nzbSegments = []

        ## TO download segments --
        # we'll remove from this set everytime a segment is found completed (on the FS)
        # during NZB parsing, or later written to the FS
        self.todoNzbSegments = set()

        ## Segments that have been dequeued on the fly (during download). These are kept
        ## track of in the rare case that an nzb file is dequeued when all segments have
        ## actually been downloaded
        self.dequeuedSegments = set()

        ## NZBFile statistics
        self.number = len(self.nzb.nzbFiles)
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
        
        # Whether or not the filename was forcefully changed from the original by the
        # DupeHandler
        self.forcedChangedFilename = False
        
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

        # Toggled to True when this nzbFile's assembly was interrupted during an
        # OutOfDiskSpace exception
        self.interruptedAssembly = False
        
        ## Whether or not this is a par file, an extra par file
        ## (e.g. archiveA.vol02+01.par2), and has been skipped by the downloader
        self.isPar = False
        self.isExtraPar = False
        self.isSkippedPar = False

    def getDestination(self):
        """ Return the full pathname of where this NZBFile should be written to on disk """
        return os.path.join(self.nzb.destDir, self.getFilename())

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
            self.nzb.firstSegmentsDownloaded += 1
            return False

        elif self.filename is None:
            # First, check if this is one of the dupe files on disk
            isDupe, dupeNeedsDl = handleDupeNZBFileNeedsDownload(self, workingDirDupeMap)
            if isDupe:
                # NOTE: We should know this is a par, but probably don't care if it is.
                # If there is a par file fully assembled on disk, we don't care about
                # skipping it
                if self.filename is not None:
                    identifyPar(self)
                if not dupeNeedsDl:
                    self.nzb.firstSegmentsDownloaded += 1
                return dupeNeedsDl

            # We only know about the temp filename. In that case, fall back to matching
            # filenames in our subject line
            for file in workingDirListing:
                # Whole file match
                if self.subject.find(file) > -1:
                    # No need for setRealFileName(self, file)'s extra work here
                    self.filename = file
                    
                    # Prevent matching of this file multiple times
                    workingDirListing.remove(file)

                    if Hellanzb.SMART_PAR:
                        identifyPar(self)
                        if self.isPar:
                            debug('needsDownload: Found par on disk: %s isExtraPar: %s' % \
                                  (file, str(self.isExtraPar)))
                        
                    self.nzb.firstSegmentsDownloaded += 1
                    return False
    
        return True

    def getTempFileName(self):
        """ Generate a temporary filename for this file, for when we don't have it's actual file
        name on hand """
        return 'hellanzb-tmp-' + self.nzb.archiveName + '.file' + str(self.number).zfill(4)

    def isAllSegmentsDecoded(self):
        """ Determine whether all these file's segments have been decoded (nzbFile is ready to be
        assembled) """
        if self.isSkippedPar:
            return not len(self.dequeuedSegments) and not len(self.todoNzbSegments)
        return not len(self.todoNzbSegments)
    
    def tryAssemble(self):
        """ Call the ArticleDecoder function of the same name """
        tryAssemble(self)

    #def __repr__(self):
    #    msg = 'nzbFile: ' + os.path.basename(self.getDestination())
    #    if self.filename is not None:
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

        # The NZBSegmentQueue this segment was last pulled from
        self.fromQueue = None

        # The NZBLeecherFactory this segment was last downloaded from
        self.fromServer = None

    def getDestination(self):
        """ Where this decoded segment will reside on the fs """
        return self.nzbFile.getDestination() + '.segment' + str(self.number).zfill(4)
    
    def getTempFileName(self):
        """ """
        return self.nzbFile.getTempFileName() + '.segment' + str(self.number).zfill(4)

    def getFilenameFromArticleData(self):
        """ Determine the segment's filename via the articleData """
        parseArticleData(self, justExtractFilename = True)
        
        if self.nzbFile.filename is None and self.nzbFile.tempFilename is None:
            raise FatalError('Could not getFilenameFromArticleData, file:' + str(self.nzbFile) +
                             ' segment: ' + str(self))

    def loadArticleDataFromDisk(self):
        """ Load the previously downloaded article BODY from disk, as a list to the .articleData
        variable. Removes the on disk version upon loading """
        # downloaded encodedData was written to disk by NZBLeecher
        encodedData = open(os.path.join(Hellanzb.DOWNLOAD_TEMP_DIR, self.getTempFileName() + '_ENC'))
        # remove crlfs. FIXME: might be quicker to do this during a later loop
        self.articleData = [line[:-2] for line in encodedData]
        encodedData.close()

        # Delete the copy on disk ASAP
        nuke(os.path.join(Hellanzb.DOWNLOAD_TEMP_DIR, self.getTempFileName() + '_ENC'))

    def isFirstSegment(self):
        """ Determine whether or not this is the first segment """
        return self is self.nzbFile.firstSegment

    def smartDequeue(self, readOnlyQueue = False):
        """ Shortcut to the SmartPar function of the same name """
        smartDequeue(self, readOnlyQueue)

    #def __repr__(self):
    #    return 'segment: ' + os.path.basename(self.getDestination()) + ' number: ' + \
    #           str(self.number) + ' subject: ' + self.nzbFile.subject

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
    
    needDlFiles = set() # for speed while iterating
    needDlSegments = []
    onDiskSegments = []

    # Cache all WORKING_DIR segment filenames in a map of lists
    for file in os.listdir(Hellanzb.WORKING_DIR):
        if not validWorkingFile(os.path.join(Hellanzb.WORKING_DIR, file),
                                overwriteZeroByteSegments):
            continue
        
        ext = getFileExtension(file)
        if ext is not None and segmentEndRe.match(ext):
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
                break

        if not foundFileName:
            needDlSegments.append(segment)
            needDlFiles.add(segment.nzbFile)
        else:
            if segment.isFirstSegment() and not isHellaTemp(foundFileName) and \
                    segment.nzbFile.filename is None:
                # HACK: filename is None. so we only have the temporary name in
                # memory. since we didnt see the temporary name on the filesystem, but we
                # found a subject match, that means we have the real name on the
                # filesystem. In the case where this happens we've figured out the real
                # filename (hopefully!). Set it if it hasn't already been set
                setRealFileName(segment.nzbFile, foundFileName,
                            settingSegmentNumber = segment.number)

                if Hellanzb.SMART_PAR:
                    # smartDequeue won't actually 'dequeue' any of this segment's
                    # nzbFile's segments (because there are no segments in the queue at
                    # this point). It will identifyPar the segment AND more importantly it
                    # will mark nzbFiles as isSkippedPar (taken into account later during
                    # parseNZB) and print a 'Skipping par' message for those isSkippedPar
                    # nzbFiles
                    segment.smartDequeue(readOnlyQueue = True)
                
            onDiskSegments.append(segment)
            
            # Originally the main reason to call segmentDone here is to update the queue's
            # onDiskSegments (so isBeingDownloaded can safely detect things on disk during
            # Dupe renaming). However it's correct to call this here, it's as if hellanzb
            # just finished downloading and decoding the segment. The only incorrect part
            # about the call is the queue's totalQueuedBytes is decremented. That total is
            # reset to zero just before it is recalculated at the end of parseNZB, however
            Hellanzb.queue.segmentDone(segment)

            # This segment was matched. Remove it from the list to avoid matching it again
            # later (dupes)
            segmentFileNames.remove(foundFileName)

        #else:
        #    debug('SKIPPING SEGMENT: ' + segment.getTempFileName() + ' subject: ' + \
        #          segment.nzbFile.subject)

    return needDlFiles, needDlSegments, onDiskSegments

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
