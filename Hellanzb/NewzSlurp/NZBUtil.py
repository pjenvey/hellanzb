# <DEBUGGING>
import sys
sys.path.append('/home/pjenvey/src/hellanzb-asynchella')
# </DEBUGGING>

import shutil, re, time
from sets import Set
from threading import Lock, RLock
from xml.sax import make_parser
from xml.sax.handler import ContentHandler, feature_external_ges, feature_namespaces
from Hellanzb.Logging import *
from Hellanzb.NewzSlurp.ArticleDecoder import parseArticleData
from Hellanzb.Util import archiveName, getFileExtension, PriorityQueue

class NZBSegment:
    def __init__(self, bytes, number, messageId, nzbFile):
        # from xml attributes
        self.bytes = bytes
        self.number = number
        self.messageId = messageId

        # Reference to the parent NZBFile this is segment belongs to
        self.nzbFile = nzbFile

        self.articleData = None
        
        self.crc = None

    def getDestination(self):
        """ Where this decoded segment will reside on the fs """
        return self.nzbFile.getDestination() + '.segment' + str(self.number).zfill(4)
    
    def getTempFileName(self):
        """ """
        return self.nzbFile.getTempFileName() + '_' + str(self.number).zfill(4)

    def getFilenameFromArticleData(self):
        """ Determine the segment's filename via the articleData """
        # The first segment marshalls setting of the parent nzbFile.tempFilename, which
        # all other segments will end up using when they call
        # getDestination(). tempFilename is only used when that first segment lacks
        # articleData and can't determine the real filename
        if self.articleData == None and self.number == 1:
            self.nzbFile.tempFilename = self.getTempFileName()
            return

        # We have article data, get the filename from it
        parseArticleData(self, justExtractFilename = True)
        
        if self.nzbFile.filename == None and self.nzbFile.tempFilename == None:
            raise FatalError('Could not getFilenameFromArticleData, file:' + str(self.nzbFile) +
                             ' segment: ' + str(self))

    # FIXME: give file a needsDownload, and we can run the check during queue creation as
    # well
    def needsDownload(self):
        """ Whether or not this segment needs to be downloaded (isn't on the file system) """
        # We need to ensure that we're not in the process of renaming from a temp file
        # name, so we have to lock.
        self.doh('entry')
        self.nzbFile.tempFileNameLock.acquire()
        ##info('my dest: ' + self.getDestination())
        if os.path.isfile(self.nzbFile.getDestination()):
            self.nzbFile.tempFileNameLock.release()
            self.doh('isfile')
            return False
        elif os.path.isfile(self.getDestination()):
            self.nzbFile.tempFileNameLock.release()
            self.doh('isfile segment')
            return False
        elif self.nzbFile.filename == None:
            self.doh('no filename')
            # We only know about the temp filename. In that case, fall back to matching
            # filenames in our subject line
            from Hellanzb import WORKING_DIR
            for file in os.listdir(WORKING_DIR):

                self.doh(file)
                if re.match(r'.*' + file + r'.*', self.nzbFile.subject):
                    self.doh('matched')
                else:
                    self.doh('nomatched')
                if file == 'ps-ncsg38b.vol000+01.PAR2':
                    self.doh('subject: ' + self.nzbFile.subject)
                ext = getFileExtension(file)
                # Segment Match
                if ext != None and re.match(r'^segment\d{4}$', ext):

                    # Quickest/easiest way to determine this file is not this segment's
                    # file is by checking it's segment number
                    segmentNumber = int(file[-4:])
                    if segmentNumber != self.number:
                        #self.doh('none segment mismatch')
                        # FIXME: need to continue instead of return
                        #return False
                        continue

                    # Strip the segment suffix, and if that filename is in our subject,
                    # we've found a match
                    prefix = file[0:-len('.segmentXXXX')]
                    #if re.match(r'.*' + prefix + r'.*', self.nzbFile.subject):
                    if self.nzbFile.subject.find(prefix) > -1:
                        self.nzbFile.tempFileNameLock.release()
                        self.doh('none segment file mismatch')
                        return False
                        #return True

                # Whole file match
                #elif re.match(r'.*' + file + r'.*', self.nzbFile.subject):
                elif self.nzbFile.subject.find(file) > -1:
                    self.nzbFile.tempFileNameLock.release()
                    self.doh('none file')
                    #return True
                    return False
                
            # Looks like none of the files in WORKING_DIR are ours so we need to be
            # downloaded
            #self.nzbFile.tempFileNameLock.release()
            #return True

        self.doh('final')
        self.nzbFile.tempFileNameLock.release()
        return True

    def doh(self, m):
        #if True:
        #if self.number == 16 and self.nzbFile.subject == '(Naughty.College.School.Girls.38.XXX.DVDRip.XviD-Pr0nStarS-CD1)))[50/50] - "ps-ncsg38a.rar" yEnc (1/17)':
        #if self.nzbFile.subject == '(Naughty.College.School.Girls.38.XXX.DVDRip.XviD-Pr0nStarS-CD2-pars)))[1/7] - "ps-ncsg38b.vol000+01.PAR2" yEnc (1/1)':
        if self.nzbFile.subject == '(Naughty.College.School.Girls.38.XXX.DVDRip.XviD-Pr0nStarS-CD1)))[50/50] - "ps-ncsg38a.rar" yEnc (1/17)':
            debug('>>>>' + m)

    def __repr__(self):
        # FIXME
        return 'messageId: ' + str(self.messageId) + ' number: ' + str(self.number) + ' bytes: ' + \
            str(self.bytes)

class NZB:
    def __init__(self, nzbFileName):
        self.nzbFileName = nzbFileName
        self.archiveName = archiveName(self.nzbFileName)
        self.nzbFileElements = []
        
class NZBFile:
    def __init__(self, subject, date = None, poster = None, nzb = None):
        # from xml attributes
        self.subject = str(subject)
        self.date = date
        self.poster = poster
        # Name of the actual nzb file this <file> is part of
        self.nzb = nzb
        # FIXME: thread safety?
        self.nzb.nzbFileElements.append(self)
        self.groups = []
        self.nzbSegments = []

        self.decodedNzbSegments = []
        # FIXME:FIXME:FIXME: ridiculous amount of Lock() spamming what is this for
        # again???
        self.decodedNzbSegmentsLock = Lock()

        self.filename = None
        self.tempFilename = None

        # FIXME: BLAH!
        self.tempFileNameLock = RLock()

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

        noFileName = False
        if self.filename == None:
            noFileName = True

            firstSegment = self.nzbSegments[0]

            # Return the cached tempFilename until the firstSegment is downloaded
            if self.tempFilename != None and firstSegment.articleData == None:
                return WORKING_DIR + os.sep + self.tempFilename

            # this will set either filename or tempFilename
            firstSegment.getFilenameFromArticleData()

            # Again return tempFilename until we find the real filename
            # NOTE: seems like there'd be no notification if we're unable to retrieve the
            # real filename, we'd just be stuck with the temp
            if self.filename == None:
                return WORKING_DIR + os.sep + self.tempFilename

        hi = """
        if noFileName:
            # We were using temp name and just found the new filename. Immediately rename
            # any files that were using the temp name
            tempFileNames = {}
            for nzbSegment in self.nzbSegments:
                tempFileNames[nzbSegment.getTempFileName()] = nzbSegment.getDestination()

            for file in os.listdir(WORKING_DIR):
                if file in tempFileNames:
                    newDest = tempFileNames.get('file')
                    shutil.move(WORKING_DIR + os.sep + file,
                                WORKING_DIR + os.sep + newDest)
        """
                    
        return WORKING_DIR + os.sep + self.filename

    def getTempFileName(self):
        """ Generate a temporary filename for this file, for when we don't have it's actual file
        name on hand """
        return 'hellanzb-tmp-' + self.nzb.archiveName + '.file' + str(self.number).zfill(4)

    def isAssembled(self):
        """ We should only write the finished file if we completely assembled """
        if os.path.isfile(self.getDestination()):
            return True
        return False

    def isAllSegmentsDecoded(self):
        """ Determine whether all these file's segments have been decoded """
        start = time.time()

        decodedSegmentFiles = []
        for nzbSegment in self.nzbSegments:
            decodedSegmentFiles.append(os.path.basename(nzbSegment.getDestination()))

        dirName = os.path.dirname(self.getDestination())
        for file in os.listdir(dirName):
            ####if re.match(self.filename + '\.hellanzb\d{4}$', file) and file in decodedSegmentFiles:
            #if re.match('\.hellanzb\d{4}$', file):
            
            #    stripped = re.sub('\.hellanzb\d{4}', '', file)
            if file in decodedSegmentFiles:
                
                #debug('$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$')
                #debug('stripped: ' + stripped)
                #debug('$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$')
                #debug('>')
                #if re.match(file, self.subject):
                    # Found it -- this file is done
                    #debug('!file: ' + file)
                    #debug('>>>>')
                decodedSegmentFiles.remove(file)

        # Just be stupid -- we're only finished until we've found all the known files
        # (segments)
        if len(decodedSegmentFiles) == 0:
            finish = time.time() - start
            debug('isAllSegmentsDecoded (T) took: ' + str(finish) + ' seconds')
            return True

        finish = time.time() - start
        debug(self.getDestination() + 'isAllSegmentsDecoded (F) took: ' + str(finish))
        #debug(self.getDestination() + 'isAllSegmentsDecoded (F) took: ' + str(finish) + \
        #     ' seconds len: ' + str(len(decodedSegmentFiles)) + ' ' + str(decodedSegmentFiles))
        return False

    def __repr__(self):
        # FIXME
        return 'NZBFile subject: ' + str(self.subject) + 'fileName: ' + str(self.filename) + \
            ' date: ' + str(self.date) + ' poster: ' + str(self.poster)

class NZBQueue(PriorityQueue):
    """ priority fifo queue of segments to download. lower numbered segments are downloaded
    before higher ones """
    NZB_CONTENT_P = 10 # normal nzb downloads
    EXTRA_PAR2_P = 0 # par2 after-the-fact downloads are more important

    def __init__(self, fileName = None):
        PriorityQueue.__init__(self)
        # Set is much faster for _put
        self.nzbFiles = Set()
        
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
                
        self.bytes = None
        self.number = None

        self.fileCount = 0
        
    def startElement(self, name, attrs):
        if name == 'file':
            #FIXME
            #print 'got: ' + unicode(attrs.get('subject'))
            #i = open('/tmp/ww', 'wb')
            #i.write(attrs.get('subject').encode('utf-8'))
            #i.close()
            #print 'got: ' + attrs.get('subject').encode('utf-8')
            self.file = NZBFile(attrs.get('subject'), attrs.get('date'), attrs.get('poster'),
                                self.nzb)
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
                
        elif name == 'group':
            newsgroup = ''.join(self.chars)
            #debug('group: ' + newsgroup)

            self.file.groups.append(newsgroup)
                        
            self.chars = None
                
        elif name == 'segment':
            messageId = ''.join(self.chars)
            nzbs = NZBSegment(self.bytes, self.number, messageId, self.file)
            self.file.nzbSegments.append(nzbs)
            self.queue.put((NZBQueue.NZB_CONTENT_P, nzbs))
                        
            self.chars = None
            self.number = None
            self.bytes = None    
