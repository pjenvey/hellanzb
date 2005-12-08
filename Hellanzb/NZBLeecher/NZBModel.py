"""

NZBModel - Representations of the NZB file format in memory

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import gc, os, re, stat, time, Hellanzb
from sets import Set
from threading import Lock, RLock
from twisted.internet import reactor
from xml.sax import make_parser, SAXParseException
from xml.sax.handler import ContentHandler, feature_external_ges, feature_namespaces
from Hellanzb.Core import shutdown
from Hellanzb.Daemon import handleNZBDone
from Hellanzb.Log import *
from Hellanzb.NZBLeecher.ArticleDecoder import assembleNZBFile, parseArticleData, \
    setRealFileName, tryFinishNZB
from Hellanzb.Util import archiveName, getFileExtension, nextDupeName, IDPool, \
    EmptyForThisPool, PoolsExhausted, PriorityQueue, OutOfDiskSpace, DUPE_SUFFIX, \
    DUPE_SUFFIX_RE
from Queue import Empty

__id__ = '$Id$'

def validWorkingFile(file, overwriteZeroByteFiles = False):
    """ Determine if the specified file path is a valid, existing file in the WORKING_DIR """
    if not os.path.isfile(file):
        return False

    # Overwrite 0 byte segment files if specified
    if 0 == os.stat(file)[stat.ST_SIZE] and overwriteZeroByteFiles:
        #debug('Will overwrite 0 byte segment file: ' + file)
        # FIXME: store these 0 byte files in a list, when we encounter a segment file
        # that matches one of these, we will tell the user we're overwriting the 0
        # byte file. FIXME: this should then also work for overwriting 0 byte on disk
        # NZBFiles
        return False
    
    return True

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
                segment.nzbFile.todoNzbSegments.remove(segment)
                break

        if not foundFileName:
            needDlSegments.append(segment)
            needDlFiles.add(segment.nzbFile)
        else:
            if segment.number == 1 and foundFileName.find('hellanzb-tmp-') != 0:
                # HACK: filename is None. so we only have the temporary name in
                # memory. since we didnt see the temporary name on the filesystem, but
                # we found a subject match, that means we have the real name on the
                # filesystem. In the case where this happens, and we are segment #1,
                # we've figured out the real filename (hopefully!)
                setRealFileName(segment.nzbFile, foundFileName,
                            settingSegmentNumber = segment.number)
                
            onDiskSegments.append(segment)

            # This segment was matched. Remove it from the list to avoid matching it again
            # later (dupes)
            segmentFileNames.remove(foundFileName)

        #else:
        #    debug('SKIPPING SEGMENT: ' + segment.getTempFileName() + ' subject: ' + \
        #          segment.nzbFile.subject)

    return needDlFiles, needDlSegments, onDiskSegments

class NZB:
    """ Representation of an nzb file -- the root <nzb> tag """
    
    def __init__(self, nzbFileName):
        ## NZB file general information
        self.nzbFileName = nzbFileName
        self.archiveName = archiveName(self.nzbFileName) # pretty name
        self.nzbFileElements = []
        
        self.id = IDPool.getNextId()

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

        # To be passed to the PostProcessor
        self.rarPassword = None
        
        ## Whether or not we should redownload NZBFile and NZBSegment files on disk that are 0 bytes in
        ## size
        self.overwriteZeroByteFiles = True
        
    def isCanceled(self):
        """ Whether or not this NZB was cancelled """
        self.canceledLock.acquire()
        c = self.canceled
        self.canceledLock.release()
        return c

    def cancel(self):
        """ Mark this NZB as having been cancelled """
        self.canceledLock.acquire()
        self.canceled = True
        self.canceledLock.release()
        
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

    def getDestination(self):
        """ Return the full pathname of where this NZBFile should be written to on disk """
        return self.nzb.destDir + os.sep + self.getFilename()

    def getFilename(self):
        """ Return the file name of where this NZBFile will lie on the filesystem (not including
        dirname). The filename information is grabbed from the first segment's articleData
        (uuencode's fault -- yencode includes the filename in every segment's
        articleData). In the case where a segment needs to know it's filename, and that
        first segment doesn't have articleData (hasn't been downloaded yet), a temp
        filename will be returned. Downloading segments out of order can easily occur in
        app like hellanzb that downloads the segments in parallel, thus the need for
        temporary file names """
        try:
            # FIXME: try = slow. just simply check if tempFilename exists after
            # getFilenamefromArticleData. does exactly the same thing w/ no try. should probably
            # looked at the 2nd revised version of this and make sure it's still as functional as
            # the original
            if self.filename != None:
                return self.filename
            elif self.tempFilename != None and self.firstSegment.articleData == None:
                return self.tempFilename
            else:
                # FIXME: i should only have to call this once after i get article
                # data. that is if it fails, it should set the real filename to the
                # incorrect tempfilename
                self.firstSegment.getFilenameFromArticleData()
                return self.tempFilename
        except AttributeError:
            self.tempFilename = self.getTempFileName()
            return self.tempFilename

    def handleDupeNeedsDownload(self, workingDirDupeMap):
        """ Determine whether or not this NZBFile is a known duplicate. If so, also determine if
        this NZBFile needs to be downloaded """
        isDupe = False
        # Search the dupes on disk for a match
        for file in workingDirDupeMap.iterkeys():
            if self.subject.find(file) > -1:
                isDupe = True

                debug('handleDupeNeedsDownload: handling dupe: %s' % file)
                for dupeEntry in workingDirDupeMap[file]:
                    # Ok, *sigh* we're a dupe. Find the first unidentified index in the
                    # dupeEntry (dupeEntry[1] is None)
                    i = -1
                    origin = None
                    if dupeEntry[1] is None:
                        i += 1
                        dupeEntry[1] = self

                        # Set our filename now, since we know it, for sanity sake
                        dupeFilename = nextDupeName(file, checkOnDisk = False,
                                                    minIteration = dupeEntry[0] + 1)
                        self.filename = dupeFilename
                        debug('handleDupeNeedsDownload: marking fileNum: %i as dupeFilename' \
                              ' %s (dupeMap index: %i)' % (self.number, dupeFilename, i))

                        # Now that we have the correct filename we can determine if this
                        # dupe needs to be downloaded
                        if os.path.isfile(Hellanzb.WORKING_DIR + os.sep + dupeFilename):
                            debug('handleDupeNeedsDownload: dupeName: %s needsDownload: False' \
                                  % dupeFilename)
                            return isDupe, False
                        
                        debug('handleDupeNeedsDownload: dupeName: %s needsDownload: True' \
                              % dupeFilename)
                        return isDupe, True

                    # Keep track of the origin -- we need to handle it specially (rename
                    # it to an actual dupeName ASAP) if there are more duplicates in the
                    # NZB than there are currently on disk
                    elif dupeEntry[0] == -1:
                        origin = dupeEntry[1]

                if origin is not None and origin.filename is None:
                    # That special case -- there are more duplicates in the NZB than there
                    # are currently on disk (we looped through all dupeEntries and could
                    # not find a match to this NZBFile on disk). Rename the origin
                    # immediately. This needs to be done because if the origin's has
                    # segments on disk (not yet the fully assembled file), these will
                    # cause massive trouble later with ArticleDecoder.handleDupeNZBSegment
                    renamedOrigin = nextDupeName(Hellanzb.WORKING_DIR + os.sep + file)
                    setRealFileName(origin, os.path.basename(renamedOrigin),
                                    forceChange = True)
                    debug('handleDupeNeedsDownload: renamed origin from: %s to: %s' \
                          % (file, renamedOrigin))

                # Didn't find a match on disk. Needs to be downloaded
                return isDupe, True
            
        return isDupe, None

    def needsDownload(self, workingDirListing, workingDirDupeMap):
        """ Whether or not this NZBFile needs to be downloaded (isn't on the file system). You may
        specify the optional workingDirListing so this function does not need to prune
        this directory listing every time it is called (i.e. prune directory
        names). workingDirListing should be a list of only filenames (basename, not
        including dirname) of files lying in Hellanzb.WORKING_DIR """
        start = time.time()

        if os.path.isfile(self.getDestination()):
            # This block only handles matching temporary file names
            end = time.time() - start
            debug('needsDownload took: ' + str(end))
            return False

        elif self.filename == None:

            # First, check if this is one of the dupe files on disk
            isDupe, dupeNeedsDl = self.handleDupeNeedsDownload(workingDirDupeMap)
            if isDupe:
                return dupeNeedsDl

            # We only know about the temp filename. In that case, fall back to matching
            # filenames in our subject line
            for file in workingDirListing:

                # Whole file match
                if self.subject.find(file) > -1:
                    end = time.time() - start
                    debug('needsDownload took: ' + str(end))
                    return False
    
        end = time.time() - start
        debug('needsDownload took: ' + str(end))
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

    #def __repr__(self):
    #    return 'segment: ' + os.path.basename(self.getDestination()) + ' number: ' + \
    #           str(self.number) + ' subject: ' + self.nzbFile.subject

class RetryQueue:
    """ Maintains various PriorityQueues for requeued segments. Each PriorityQueue maintained
    is keyed by a string describing what serverPools previously failed to download that
    queue's segments """
    def __init__(self):
        # all the known pool names
        self.serverPoolNames = []
        
        # dict to lookup the priority by name -- the name describes which serverPools
        # should NOT look into that particular queue. Example: 'not1not2not4'
        self.poolQueues = {}

        # map of serverPoolNames to their list of valid retry queue names
        self.nameIndex = {}

        # A list of all queue names
        self.allNotNames = []

    def clear(self):
        """ Clear all the queues """
        for queue in self.poolQueues.itervalues():
            queue.clear()

    def addServerPool(self, serverPoolName):
        """ Add an additional serverPool. This does not create any associated PriorityQueues, that
        work is done by createQueues """
        self.serverPoolNames.append(serverPoolName)

    def removeServerPool(self, serverPoolName):
        """ Remove a serverPool. FIXME: probably never needed, so not implemented """
        raise NotImplementedError()

    def requeue(self, serverPoolName, segment):
        """ Requeue the segment (which failed to download on the specified serverPool) for later
        retry by another serverPool

        The segment is requeued by adding it to the correct PriorityQueue -- dictated by
        which serverPools have previously failed to download the specified segment. A
        PoolsExhausted exception is thrown when all serverPools have failed to download
        the segment """
        # All serverPools we know about failed to download this segment
        if len(segment.failedServerPools) == len(self.serverPoolNames):
            raise PoolsExhausted()

        # Figure out the correct queue by looking at the previously failed serverPool
        # names
        notName = ''
        i = 0
        for poolName in self.serverPoolNames:
            i += 1
            if poolName in segment.failedServerPools:
                notName += 'not' + str(i)

        # Requeued for later
        self.poolQueues[notName].put((segment.priority, segment))
    
    def get(self, serverPoolName):
        """ Return the next segment for the specified serverPool that is queued to be retried """
        # Loop through all the valid priority queues for the specified serverPool
        valids = self.nameIndex[serverPoolName]
        for queueName in valids:
            queue = self.poolQueues[queueName]

            # Found a segment waiting to be retried
            if len(queue):
                return queue.get_nowait()

        raise Empty()

    def __len__(self):
        length = 0
        for queue in self.poolQueues.itervalues():
            length += len(queue)
        return length

    def createQueues(self):
        """ Create the retry PriorityQueues for all known serverPools

        This is a hairy way to do this. It's not likely to scale for more than probably
        4-5 serverPools. However it is functionally ideal for a reasonable number of
        serverPools

        The idea is you want your downloaders to always be busy. Without the RetryQueue,
        they would simply always pull the next available segment out of the main
        NZBQueue. Once the NZBQueue was empty, all downloaders knew they were done

        Now that we desire the ability to requeue a segment that failed on a particular
        serverPool, the downloaders need to exclude the segments they've previously failed
        to download, when pulling segments out of the NZBQueue

        If we continue keeping all queued (and now requeued) segments in the same queue,
        the potentially many downloaders could easily end up going through the entire
        queue seeking a segment they haven't already tried. This is unacceptable when our
        queues commonly hold over 60K items

        The best way I can currently see to support the downloaders being able to quickly
        lookup the 'actual' next segment they want to download is to have multiple queues,
        indexed by what serverPool(s) have previously failed on those segments

        If we have 3 serverPools (1, 2, and 3) we end up with a dict looking like:

        not1     -> q
        not2     -> q
        not3     -> q
        not1not2 -> q
        not1not3 -> q
        not2not3 -> q

        I didn't quite figure out the exact equation to gather the number of Queues in
        regard to the number of serverPools, but (if my math is right) it seems to grow
        pretty quickly (is quadratic)

        Every serverPool avoids certain queues. In the previous example, serverPool 1 only
        needs to look at all the Queues that are not tagged as having already failed on 1
        (not2, not3, and not2not3) -- only half of the queues

        The numbers:

        serverPools    totalQueues    onlyQueues

        2              2              1
        3              6              3
        4              14             7
        5              30             15
        6              62             31
        7              126            63

        The RetryQueue.get() algorithim simply checks all queues for emptyness until it
        finds one with items in it. The > 5 is worrysome. That means for 6 serverPools,
        the worst case scenario (which could be very common in normal use) would be to
        make 31 array len() calls. With a segment size of 340KB, downloading at 1360KB/s,
        (and multiple connections) we could be doing those 31 len() calls on average of 4
        times a second. And with multiple connections, this could easily spurt to near
        your max connection count, per second (4, 10, even 30 connections?)

        Luckily len() calls are as quick as can be and who the hell uses 6 different
        usenet providers anyway? =]
        """
        # Go through all the serverPools and create the initial 'not1' 'not2'
        # queues
        # FIXME: could probably let the recursive function take care of this
        for i in range(len(self.serverPoolNames)):
            notName = 'not' + str(i + 1)
            self.poolQueues[notName] = PriorityQueue()

            self._recurseCreateQueues([i], i, len(self.serverPoolNames))

        # Finished creating all the pools. Now index every pool's list of valid retry
        # queues they need to check.  (using the above docstring, serverPool 1 would have
        # a list of 'not2', 'not3', and 'not2not3' in its nameIndex
        i = 0
        for name in self.serverPoolNames:
            i += 1
            
            valids = []
            for notName in self.poolQueues.keys():
                if notName.find('not' + str(i)) > -1:
                    continue
                valids.append(notName)
            self.nameIndex[name] = valids

    def _recurseCreateQueues(self, currentList, currentIndex, totalCount):
        """ Recurse through, creating the matrix of 'not1not2not3not4not5' etc and all its
        variants. Avoid creating duplicates """
        # Build the original notName
        notName = ''
        for i in currentList:
            notName += 'not' + str(i + 1)

        if len(currentList) >= totalCount - 1:
            # We've reached the end
            return

        for x in range(totalCount):
            if x == currentIndex or x in currentList:
                # We've already not'd x, skip it
                continue

            newList = currentList[:]
            newList.append(x)
            newList.sort()

            if newList in self.allNotNames:
                # this notName == an already generated notName, skip it
                continue

            self.allNotNames.append(newList)

            newNotName = notName + 'not' + str(x + 1)
            self.poolQueues[newNotName] = PriorityQueue()
            self._recurseCreateQueues(newList, x, totalCount)

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
        self.postponedNzbFiles = Set()
        self.nzbFilesLock = Lock()

        self.nzbs = []
        self.nzbsLock = Lock()

        self.totalQueuedBytes = 0

        # Segments curently on disk
        self.onDiskSegments = {}

        self.retryQueueEnabled = False
        self.rQueue = RetryQueue()

        if fileName is not None:
            self.parseNZB(fileName)

    def cancel(self):
        self.postpone(cancel = True)

    def clear(self):
        """ Clear the queue of all its contents"""
        if self.retryQueueEnabled:
            self.rQueue.clear()
        PriorityQueue.clear(self)

    def postpone(self, cancel = False):
        """ Postpone the current download """
        self.clear()

        self.nzbsLock.acquire()
        self.nzbFilesLock.acquire()

        if not cancel:
            self.postponedNzbFiles.union_update(self.nzbFiles)
        self.nzbFiles.clear()

        self.nzbs = []
        
        self.nzbFilesLock.release()
        self.nzbsLock.release()

        self.totalQueuedBytes = 0

    def _put(self, item):
        """ Add a segment to the queue """
        priority, item = item

        # Support adding NZBFiles to the queue. Just adds all the NZBFile's NZBSegments
        if isinstance(item, NZBFile):
            offset = 0
            for nzbSegment in item.nzbSegments:
                PriorityQueue._put(self, (priority + offset, nzbSegment))
                offset += 1
        else:
            # Assume segment, add to list
            if item.nzbFile not in self.nzbFiles:
                self.nzbFiles.add(item.nzbFile)
            PriorityQueue._put(self, (priority, item))

    def calculateTotalQueuedBytes(self):
        """ Calculate how many bytes are queued to be downloaded in this queue """
        # NOTE: we don't maintain this calculation all the time, too much CPU work for
        # _put
        self.nzbFilesLock.acquire()
        files = self.nzbFiles.copy()
        self.nzbFilesLock.release()
        for nzbFile in files:
            self.totalQueuedBytes += nzbFile.totalBytes

    def currentNZBs(self):
        """ Return a copy of the list of nzbs currently being downloaded """
        self.nzbsLock.acquire()
        nzbs = self.nzbs[:]
        self.nzbsLock.release()
        return nzbs

    def nzbAdd(self, nzb):
        """ Denote this nzb as currently being downloaded """
        self.nzbsLock.acquire()
        self.nzbs.append(nzb)
        self.nzbsLock.release()
        
    def nzbDone(self, nzb):
        """ NZB finished """
        self.nzbsLock.acquire()
        try:
            self.nzbs.remove(nzb)
        except ValueError:
            # NZB might have been canceled
            pass
        self.nzbsLock.release()

    def serverAdd(self, serverPoolName):
        """ Add the specified server pool, for use by the RetryQueue """
        self.rQueue.addServerPool(serverPoolName)

    def initRetryQueue(self):
        """ Initialize and enable use of the RetryQueue """
        self.retryQueueEnabled = True
        self.rQueue.createQueues()

    def serverRemove(self, serverPoolName):
        """ Remove the specified server pool """
        self.rQueue.removeServerPool(serverPoolName)
            
    def getSmart(self, serverPoolName):
        """ Get the next available segment in the queue. The 'smart'ness first checks for segments
        in the RetryQueue, otherwise it falls back to the main queue """
        # Don't bother w/ retryQueue nonsense unless it's enabled (meaning there are
        # multiple serverPools)
        if self.retryQueueEnabled:
            try:
                return self.rQueue.get(serverPoolName)
            except:
                # All retry queues for this serverPool are empty. fall through
                pass

            if not len(self) and len(self.rQueue):
                # Catch the special case where both the main NZBQueue is empty, all the retry
                # queues for the serverPool are empty, but there is still more left to
                # download in the retry queue (scheduled for retry by other serverPools)
                raise EmptyForThisPool()
            
        return PriorityQueue.get_nowait(self)
    
    def requeue(self, serverPoolName, segment):
        """ Requeue the segment for download. This differs from requeueMissing as it's for
        downloads that failed for reasons other than the file or group missing from the
        server (such as a connection timeout) """
        # This segment only needs to go back into the retry queue if the retry queue is
        # enabled AND the segment was previously requeueMissing()'d
        if self.retryQueueEnabled and len(segment.failedServerPools):
            self.rQueue.requeue(serverPoolName, segment)
        else:
            self.put((segment.priority, segment))

        # There's a funny case where other NZBLeechers in the calling NZBLeecher's factory
        # received Empty from the queue, then afterwards the connection is lost (say the
        # connection timed out), causing the requeue. Find and reactivate them because
        # they now have work to do
        self.nudgeIdleNZBLeechers(segment)

    def requeueMissing(self, serverPoolName, segment):
        """ Requeue a missing segment. This segment will be added to the RetryQueue (if enabled),
        where other serverPools will find it and reattempt the download """
        # This serverPool has just failed the download
        assert(serverPoolName not in segment.failedServerPools)
        segment.failedServerPools.append(serverPoolName)

        if self.retryQueueEnabled:
            self.rQueue.requeue(serverPoolName, segment)

            # We might have just requeued a segment onto an idle server pool. Reactivate
            # any idle connections pertaining to this segment
            self.nudgeIdleNZBLeechers(segment)
        else:
            raise PoolsExhausted()

    def nudgeIdleNZBLeechers(self, requeuedSegment):
        """ Activate any idle NZBLeechers that might need to download the specified requeued
        segment """
        if not Hellanzb.downloadPaused and not requeuedSegment.nzbFile.nzb.canceled:
            for nsf in Hellanzb.nsfs:
                if nsf.serverPoolName not in requeuedSegment.failedServerPools:
                    nsf.fetchNextNZBSegment()

    def fileDone(self, nzbFile):
        """ Notify the queue a file is done. This is called after assembling a file into it's
        final contents. Segments are really stored independantly of individual Files in
        the queue, hence this function """
        self.nzbFilesLock.acquire()
        if nzbFile in self.nzbFiles:
            self.nzbFiles.remove(nzbFile)
        self.nzbFilesLock.release()

        for nzbSegment in nzbFile.nzbSegments:
            if self.onDiskSegments.has_key(nzbSegment.getDestination()):
                self.onDiskSegments.pop(nzbSegment.getDestination())

    def segmentDone(self, nzbSegment):
        """ Simply decrement the queued byte count, unless the segment is part of a postponed
        download """
        self.nzbsLock.acquire()
        if nzbSegment.nzbFile.nzb in self.nzbs:
            self.totalQueuedBytes -= nzbSegment.bytes
        self.nzbsLock.release()

        self.onDiskSegments[nzbSegment.getDestination()] = nzbSegment

    def isBeingDownloadedFile(self, segmentFilename):
        """ Whether or not the file on disk is currently in the middle of being
        downloaded/assembled. Return the NZBSegment representing the segment specified by
        the filename """
        segmentFilename = segmentFilename
        if self.onDiskSegments.has_key(segmentFilename):
            return self.onDiskSegments[segmentFilename]

    def parseNZB(self, nzb):
        """ Initialize the queue from the specified nzb file """
        # Create a parser
        parser = make_parser()
        
        # No XML namespaces here
        parser.setFeature(feature_namespaces, 0)
        parser.setFeature(feature_external_ges, 0)

        # Create the handler
        fileName = nzb.nzbFileName
        self.nzbAdd(nzb)
        needWorkFiles = []
        needWorkSegments = []
        dh = NZBParser(nzb, needWorkFiles, needWorkSegments)
        
        # Tell the parser to use it
        parser.setContentHandler(dh)

        # Parse the input
        try:
            parser.parse(fileName)
        except SAXParseException, saxpe:
            self.nzbDone(nzb)
            raise FatalError('Unable to parse Invalid NZB file: ' + os.path.basename(fileName))

        s = time.time()
        # The parser will add all the segments of all the NZBFiles that have not already
        # been downloaded. After the parsing, we'll check if each of those segments have
        # already been downloaded. it's faster to check all segments at one time
        needDlFiles, needDlSegments, onDiskSegments = segmentsNeedDownload(needWorkSegments,
                                                                           overwriteZeroByteSegments = \
                                                                           nzb.overwriteZeroByteFiles)
        e = time.time() - s

        onDiskCount = dh.fileCount - len(needWorkFiles)
        if onDiskCount:
            info('Parsed: ' + str(dh.segmentCount) + ' posts (' + str(dh.fileCount) + ' files, skipping ' + \
                 str(onDiskCount) + ' on disk files)')
        else:
            info('Parsed: ' + str(dh.segmentCount) + ' posts (' + str(dh.fileCount) + ' files)')

        # Tally what was skipped for correct percentages in the UI
        for nzbSegment in onDiskSegments:
            nzbSegment.nzbFile.totalSkippedBytes += nzbSegment.bytes
            nzbSegment.nzbFile.nzb.totalSkippedBytes += nzbSegment.bytes

        # The needWorkFiles will tell us what nzbFiles are missing from the
        # FS. segmentsNeedDownload will further tell us what files need to be
        # downloaded. files missing from the FS (needWorkFiles) but not needing to be
        # downloaded (in needDlFiles) simply need to be assembled
        for nzbFile in needWorkFiles:
            if nzbFile not in needDlFiles:
                # Don't automatically 'finish' the NZB, we'll take care of that in this
                # function if necessary
                info(nzbFile.getFilename() + ': assembling -- all segments were on disk')
                
                # NOTE: this function is destructive to the passed in nzbFile! And is only
                # called on occasion (might bite you in the ass one day)
                try:
                    assembleNZBFile(nzbFile, autoFinish = False)
                except OutOfDiskSpace:
                    self.nzbDone(nzb)
                    error('Cannot assemble ' + nzb.getFileName() + ': No space left on device! Exiting..')
                    shutdown(True)

        if not len(needDlSegments):
            # FIXME: this block of code is the end of tryFinishNZB. there should be a
            # separate function
            # nudge GC
            nzbFileName = nzb.nzbFileName
            self.nzbDone(nzb)
            info(nzb.archiveName + ': assembled archive!')
            for nzbFile in nzb.nzbFileElements:
                del nzbFile.todoNzbSegments
                del nzbFile.nzb
            del nzb.nzbFileElements
            
            # FIXME: put the above dels in NZB.__del__ (that's where collect can go if needed too)
            nzbId = nzb.id
            rarPassword = nzb.rarPassword
            del nzb
            
            gc.collect()

            reactor.callLater(0, handleNZBDone, nzbFileName, nzbId, **{'rarPassword': rarPassword })

            # True == the archive is complete
            return True

        for nzbSegment in needDlSegments:
            self.put((nzbSegment.priority, nzbSegment))

        self.calculateTotalQueuedBytes()

        # Finally, figure out what on disk segments are part of partially downloaded
        # files. adjust the queued byte count to not include these aleady downloaded
        # segments. phew
        for nzbFile in needDlFiles:
            if len(nzbFile.todoNzbSegments) != len(nzbFile.nzbSegments):
                for segment in nzbFile.nzbSegments:
                    if segment not in nzbFile.todoNzbSegments:
                        self.segmentDone(segment)

        # Archive not complete
        return False

DUPE_SEGMENT_RE = re.compile('.*%s\d{1,4}.segment\d{4}$' % DUPE_SUFFIX)
class NZBParser(ContentHandler):
    """ Parse an NZB 1.0 file into an NZBQueue
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

        # Current listing of existing files in the WORKING_DIR
        self.workingDirListing = []
        self.workingDirDupeMap = {}
        files = os.listdir(Hellanzb.WORKING_DIR)
        files.sort()
        for file in files:

            if DUPE_SEGMENT_RE.match(file):
                # Sorry duplicate file segments, handling dupes is a pain enough as it is
                # without segments coming into the mix
                os.remove(Hellanzb.WORKING_DIR + os.sep + file)
                continue

            # Add an entry to the self.workingDirDupeMap if this file looks like a
            # duplicate, and also skip adding it to self.workingDirListing (dupes are
            # handled specially so we don't care for them there)
            if self.handleDupeNZBFiles(file):
                continue
            
            if not validWorkingFile(Hellanzb.WORKING_DIR + os.sep + file,
                                    self.nzb.overwriteZeroByteFiles):
                continue

            self.workingDirListing.append(file)

    def handleDupeNZBFiles(self, filename):
        """ Determine if the specified filename on disk (in the WORKING_DIR) is a duplicate
        file. Duplicate file information is stored in the workingDirDupeMap, in the format:

        Given the duplicate files on disk:

        file.rar
        file.rar.hellanzb_dupe0
        file.rar.hellanzb_dupe2

        Would produce:
        
        workingDirDupeMap = { 'file.rar': [
                                           [0, None],
                                           [1, None],
                                           [2, None],
                                           [-1, None]
                                          ]
                            }


        This represents a mapping of the original file (file.rar) to a list containing
        each duplicate file's number and it's associated NZBFile object. At this point
        (just prior to parsing of the NZB), the NZBFile object associated with the on disk
        duplicate file in the sequence of duplicates is not known (this will be filled in
        later by NZBFile.needsDownload). This function leaves that empty spot for the
        NZBFile as None

        The duplicate with index -1 is special -- it represents the original
        'file.rar'. This ordering correlates to how these duplicates were originally
        written to disk, and the order they'll be encountered in the NZB

        This represents the full RANGE of files that we know of that SHOULD be on
        disk. The file 'file.rar.hellanzb_dupe1' is missing from disk, but given the fact
        that 'file.rar.hellanzb_dupe2' exists means it WILL be there at some point

        Encountering a file listing like this is pretty rare but it could happen under the
        right situations. The point is to avoid even these rare situations as they could
        lead to inconsistent state of the NZB archive, and ultimately ugly hellanzb
        lockups
        """
        match = DUPE_SUFFIX_RE.match(filename)
        if not match:
            # Not a dupe
            return False
        
        else:
            # A dupe, ending in the _hellanzb_dupeX suffix
            strippedFilename = match.group(1) # _hellanzb_dupeX suffix removed
            dupeNum = int(match.group(2)) # the X in _hellanzb_dupeX

            newDupeMapping = False
            if not self.workingDirDupeMap.has_key(strippedFilename):
                newDupeMapping = True
                # A brand new dupe not yet in the map. There must always be an associated
                # file without the _hellanzb_dupeX suffix (branded as index -1)
                
                # This will be a list of (lists with indicies):
                # [0] The dupe number (X of hellanzb_dupeX)
                # [1] The associated dupe's NZBFile (or None if not yet found)
                self.workingDirDupeMap[strippedFilename] = [[-1, None]]

            dupesForFile = self.workingDirDupeMap[strippedFilename]
            
            if not newDupeMapping:
                # There are previous entries in our mapping (besides -1). Ensure any
                # missing indicies are filled in
                prevDupeEntry = dupesForFile[-2]
                
                if prevDupeEntry[0] != dupeNum - 1:
                    # The last entry is not (current - 1), there are missing indicies
                    missingIndex = prevDupeEntry[0]
                    while missingIndex < dupeNum - 1:
                        missingIndex += 1
                        dupesForFile.insert(-1, [missingIndex, None])
                    
            # Finally add the entry we're dealing with -- the dupe represented by the
            # passed in filename
            dupesForFile.insert(-1, [dupeNum, None])
            
            return True
            
    def startElement(self, name, attrs):
        if name == 'file':
            subject = self.parseUnicode(attrs.get('subject'))
            poster = self.parseUnicode(attrs.get('poster'))

            self.file = NZBFile(subject, attrs.get('date'), poster, self.nzb)
            
            self.fileNeedsDownload = \
              self.file.needsDownload(workingDirListing = self.workingDirListing,
                                      workingDirDupeMap = self.workingDirDupeMap)
              
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
                self.needWorkFiles.append(self.file)
            else:
                # done adding all child segments to this NZBFile. make note that none of
                # them need to be downloaded
                self.file.nzb.totalSkippedBytes += self.file.totalBytes
                self.file.todoNzbSegments.clear()

                # FIXME: (GC) can we del self.nzbfile here???
            
            self.file = None
            self.fileNeedsDownload = None
                
        elif name == 'group':
            newsgroup = self.parseUnicode(''.join(self.chars))
            self.file.groups.append(newsgroup)
                        
            self.chars = None
                
        elif name == 'segment':
            self.segmentCount += 1

            messageId = self.parseUnicode(''.join(self.chars))
            nzbs = NZBSegment(self.bytes, self.number, messageId, self.file)
            if self.number == 1:
                self.file.firstSegment = nzbs

            if self.fileNeedsDownload:
                # HACK: Maintain the order in which we encountered the segments by adding
                # segmentCount to the priority. lame afterthought -- after realizing
                # heapqs aren't ordered. NZB_CONTENT_P must now be large enough so that it
                # won't ever clash with EXTRA_PAR2_P + i
                nzbs.priority = NZBQueue.NZB_CONTENT_P + self.segmentCount
                self.needWorkSegments.append(nzbs)

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
