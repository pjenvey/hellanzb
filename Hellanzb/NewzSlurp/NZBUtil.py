"""
NZBModel -

"""
import re, time
from sets import Set
from threading import Lock, RLock
from xml.sax import make_parser
from xml.sax.handler import ContentHandler, feature_external_ges, feature_namespaces
from Hellanzb.Logging import *
from Hellanzb.NewzSlurp.ArticleDecoder import parseArticleData, setRealFileName, tryFinishNZB
from Hellanzb.Util import archiveName, getFileExtension, PriorityQueue

#s/NZBUtil/NZBModel/

# o could put failed segments into a failed queue, connections that are flaged as being
# fill servers will try to attemp to d/l the file if any of them fail?

def needsDownload(object):
    """ Whether or not this object needs to be downloaded (isn't on the file system). This
    function is generalized to support both NZBFile and NZBSegment objects. A NZBFile
    needs to be downloaded when it's file does not exist on the filesystem. An NZBSegment
    needs to be downloaded when either it's segment file, or it's parent NZBFile's file
    does not exist on the filesystem. This function does some magic to handle
    tempFileNames """
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
        return False

    elif filename == None:
        # We only know about the temp filename. In that case, fall back to matching
        # filenames in our subject line
        from Hellanzb import WORKING_DIR
        for file in os.listdir(WORKING_DIR):
            ext = getFileExtension(file)

            # Segment Match
            if isSegment and ext != None and re.match(r'^segment\d{4}$', ext):

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
                        setRealFileName(object, prefix)

                    tempFileNameLock.release()
                    return False

            # Whole file match
            elif subject.find(file) > -1:
                tempFileNameLock.release()
                return False

    tempFileNameLock.release()
    return True

class NZB:
    def __init__(self, nzbFileName):
        self.nzbFileName = nzbFileName
        self.archiveName = archiveName(self.nzbFileName)
        self.nzbFileElements = []
        
class NZBFile:
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
        
        self.number = len(self.nzb.nzbFileElements)
        self.groups = []
        self.nzbSegments = []

        # FIXME: file needs a destination. if None, we overwrite it with WORKING_DIR
        #self.destination = None

        # The real filename, determined from the actual decoded articleData
        self.filename = None
        # The filename used temporarily until the real filename is determined
        self.tempFilename = None

        # FIXME: BLAH!
        self.tempFileNameLock = RLock()

        
        self.totalBytes = 0

        self.downloadStartTime = None
        self.totalReadBytes = 0
        self.downloadPercentage = 0

    def getDestination(self):
        """ Return the destination of where this file will lie on the filesystem. The filename
        information is grabbed from the first segment's articleData (uuencode's fault --
        yencode includes the filename in every segment's articleData). In the case where a
        segment needs to know it's filename, and that first segment doesn't have
        articleData (hasn't been downloaded yet), a temp filename will be
        returned. Downloading segments out of order can easily occur in app like hellanzb
        that downloads the segments in parallel """
        # FIXME: blah imports
        from Hellanzb import WORKING_DIR

        if self.filename == None:

            firstSegment = None
            if len(self.nzbSegments) > 0:
                firstSegment = self.nzbSegments[0]

            # Return the cached tempFilename until the firstSegment is downloaded
            if self.tempFilename != None and (firstSegment == None or firstSegment.articleData == None):
                return WORKING_DIR + os.sep + self.tempFilename

            # this will set either filename or tempFilename
            if firstSegment != None:
                firstSegment.getFilenameFromArticleData()
            else:
                self.tempFilename = self.getTempFileName()

            # Again return tempFilename until we find the real filename
            # NOTE: seems like there'd be no notification if we're unable to retrieve the
            # real filename, we'd just be stuck with the temp
            if self.filename == None:
                return WORKING_DIR + os.sep + self.tempFilename
                    
        return WORKING_DIR + os.sep + self.filename

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
        # FIXME
        return 'NZBFile subject: ' + str(self.subject) + 'fileName: ' + str(self.filename) + \
            ' date: ' + str(self.date) + ' poster: ' + str(self.poster)

class NZBSegment:
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
        if self.articleData == None and self.number == 1:
            #self.nzbFile.tempFilename = self.getTempFileName()
            self.nzbFile.tempFilename = self.nzbFile.getTempFileName()
            return

        # We have article data, get the filename from it
        parseArticleData(self, justExtractFilename = True)
        
        if self.nzbFile.filename == None and self.nzbFile.tempFilename == None:
            raise FatalError('Could not getFilenameFromArticleData, file:' + str(self.nzbFile) +
                             ' segment: ' + str(self))

    def __repr__(self):
        # FIXME
        return 'messageId: ' + str(self.messageId) + ' number: ' + str(self.number) + ' bytes: ' + \
            str(self.bytes)

class NZBQueue(PriorityQueue):
    """ priority fifo queue of segments to download. lower numbered segments are downloaded
    before higher ones """
    NZB_CONTENT_P = 10 # normal nzb downloads
    EXTRA_PAR2_P = 0 # par2 after-the-fact downloads are more important

    def __init__(self, fileName = None):
        PriorityQueue.__init__(self)

        # Maintain a collection of the known nzbFiles belonging to the segments in this
        # queue. Set is much faster for _put & __contains__
        self.nzbFiles = Set()
        self.nzbFilesLock = Lock()
        
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

    def fileDone(self, nzbFile):
        """ Notify the queue a file is done. This is called after assembling a file into it's
        final contents. Segments are really stored independantly of individual Files in
        the queue, hence this function """
        self.nzbFilesLock.acquire()
        if nzbFile in self.nzbFiles:
            self.nzbFiles.remove(nzbFile)
        self.nzbFilesLock.release()

    def parseNZB(self, fileName):
        """ Initialize the queue from the specified nzb file """
        # Create a parser
        parser = make_parser()
        
        # No XML namespaces here
        parser.setFeature(feature_namespaces, 0)
        parser.setFeature(feature_external_ges, 0)
        
        # Dicts to shove things into
        newsgroups = {}
        posts = {}
        
        # Create the handler
        nzb = NZB(fileName)
        dh = NZBParser(self, nzb)
        
        # Tell the parser to use it
        parser.setContentHandler(dh)

        # Parse the input
        parser.parse(fileName)

        # In the case the NZBParser determined the entire archive's contents are already
        # on the filesystem, try to finish up (and move onto post processing)
        return tryFinishNZB(nzb)
        
class NZBParser(ContentHandler):
    def __init__(self, queue, nzb):
        self.newsgroups = []
        #self.posts = posts
        
        # fifo queue of pending segments to d/l
        self.queue = queue

        # key: nzb files loaded into this queue
        # val: all of their NZBFile objects
        self.nzbs = {}
        self.nzb = nzb
        
        self.chars = None
        self.subject = None
        self.file = None
                
        self.bytes = None
        self.number = None

        self.fileNeedsDownload = None
        self.fileCount = 0
        
    def startElement(self, name, attrs):
        if name == 'file':
            #FIXME
            #print 'got: ' + unicode(attrs.get('subject'))
            #i = open('/tmp/ww', 'wb')
            #i.write(attrs.get('subject').encode('utf-8'))
            #i.close()
            #print 'got: ' + attrs.get('subject').encode('utf-8')
            # FIXME: subject can be unicode, any of the other attribs?
            subject = attrs.get('subject')
            if isinstance(subject, unicode):
                subject = subject.encode('latin-1')
            #self.file = NZBFile(attrs.get('subject'), attrs.get('date'), attrs.get('poster'),
            self.file = NZBFile(subject, attrs.get('date'), attrs.get('poster'),
                                self.nzb)
            self.fileNeedsDownload = self.file.needsDownload()
            #debug('fileNeeds: ' + str(self.fileNeedsDownload))
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
            self.file = None
            self.fileNeedsDownload = None
                
        elif name == 'group':
            newsgroup = ''.join(self.chars)

            self.file.groups.append(newsgroup)
                        
            self.chars = None
                
        elif name == 'segment':
            messageId = ''.join(self.chars)
            if isinstance(messageId, unicode):
                messageId = messageId.encode('latin-1')
            nzbs = NZBSegment(self.bytes, self.number, messageId, self.file)
            if self.fileNeedsDownload:
                self.queue.put((NZBQueue.NZB_CONTENT_P, nzbs))

            self.chars = None
            self.number = None
            self.bytes = None    
