# <DEBUGGING>
import sys
sys.path.append('/home/pjenvey/src/hellanzb-asynchella')
# </DEBUGGING>

import re, time
from sets import Set
from threading import Lock
from xml.sax import make_parser
from xml.sax.handler import ContentHandler, feature_external_ges, feature_namespaces
from Hellanzb.Logging import *
from Hellanzb.NewzSlurp.ArticleDecoder import parseArticleData
from Hellanzb.Util import PriorityQueue, archiveName

class NZBSegment:
    def __init__(self, bytes, number, messageId, nzbFile):
        # from xml attributes
        self.bytes = bytes
        self.number = number
        self.messageId = messageId

        # Reference to the parent NZBFile this is segment belongs to
        self.nzbFile = nzbFile

        self.articleData = None

    # FIXME: 
    def guessFileName(self):
        """ Where this decoded segment will reside on the fs """
        return self.nzbFile.guessFileName() + '.hellanzb' + str(self.number).zfill(4)

    def getDestination(self):
        """ Where this decoded segment will reside on the fs """
        return self.nzbFile.getDestination() + '.hellanzb' + str(self.number).zfill(4)

    doh = """
    def getFilenameFromArticleData(self):
        # Determine the segment's filename via the articleData
        if articleData == None:
            raise FatalError('Could not getFilenameFromArticleData')

        fileName = None
        for line in articleData:
            pass
        
        # FIXME: kind of lame that i have to code both uudecode/ydecode/what else?? ways
        # of getting the filename in this function

        # after getting filename, make sure it's string exists in the segment subject. if
        # it doesn't, log a warn()
    """
    def getTempFileName(self):
        """ """
        return self.nzbFile.getTempFileName() + '_' + str(self.number).zfill(4)

    def getFilenameFromArticleData(self):
        """ Determine the segment's filename via the articleData """
        # FIXME: tempfile name will be segment.nzbFile.nzb.archiveName + segment.nzbFile.number
        if self.articleData == None and self.number == 1:
            self.nzbFile.tempFilename = self.nzbFile.subject
            return
            
        parseArticleData(self, justExtractFilename = True)
        
        if self.nzbFile.filename == None and self.nzbfile.tempFilename == None:
            raise FatalError('Could not getFilenameFromArticleData, file:' + str(self.nzbFile) + ' segment: ' + str(self))

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
        self.subject = subject
        self.date = date
        self.poster = poster
        # Name of the actual nzb file this <file> is part of
        self.nzb = nzb
        # FIXME: thread safety?
        self.nzb.nzbFileElements.append(self)
        self.groups = []
        self.nzbSegments = []

        self.decodedNzbSegments = []
        self.decodedNzbSegmentsLock = Lock()

        #self.fileNameGuess = None
        #self.guessFileName()

        self.filename = None
        self.tempFilename = None

    def getDestination(self):
        """ """
        # Lazily determine the actual filename via the article data in the first segment
        if self.filename == None:
            
            if self.tempFilename != None:
                from Hellanzb import WORKING_DIR
                return WORKING_DIR + os.sep + self.tempFilename
                
            firstSegment = self.nzbSegments[0]
            
            # This function will set our filename if it's successful
            firstSegment.getFilenameFromArticleData()
            
            if self.filename == None and self.tempFilename != None:
                from Hellanzb import WORKING_DIR
                return WORKING_DIR + os.sep + self.tempFilename


        # FIXME: blah

        from Hellanzb import WORKING_DIR
        #return WORKING_DIR + os.sep + self.fileNameGuess
        return WORKING_DIR + os.sep + self.filename

    def getTempFileName(self):
        """ Generate a temporary filename for this file, for when we don't have it's actual file
        name on hand """
        from Hellanzb import WORKING_DIR
        return WORKING_DIR + os.sep + 'hellanzb-tmp-' + self.nzb.archiveName + str(self.number).zfill(4)

    # FIXME: have to get file name information from a segment articleData, if you can't
    # get it that way, throw an exception
    def guessFileName(self):
        """ Filenames are included in <file> subjects. We should always be able to safely extract
        the file name from this subject with this RE, but we'll only use it temporarily --
        we'll distrust it and prefer to use the filename encountered during the
        download/decode process """
        #subjectFileNameRE = re.compile(r'.*\&\#34\;(.*)\&\#34\;.*')
        subjectFileNameRE = re.compile(r'.*\"(.*)\".*')
        #self.fileNameGuess = subjectFileNameRE.sub(r'\1', self.subject)
        fileNameGuess = subjectFileNameRE.sub(r'\1', self.subject)
        
        if fileNameGuess == None or fileNameGuess == self.subject:
            #raise FatalError('Could not guess NZBFile\'s filename, file subject: ' + self.subject)
            #info('$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$')
            #info('s: ' + self.subject + ' fileNameGuess: ' + self.fileNameGuess)
            #info('$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$')
            pass

        info('fileNameGuess: ' + fileNameGuess)
        return fileNameGuess

    def isAssembled(self):
        """ We should only write the finished file if we completely assembled """
        if os.path.isfile(self.getDestination()):
            return True
        return False

    def isAllSegmentsDecoded(self):
        """ Determine whether all these file's segments have been decoded """
        #self.decodedNzbSegmentsLock.acquire()
        #if len(self.decodedNzbSegments) == len(self.nzbSegments):
        #    self.decodedNzbSegmentsLock.release()
        #    return True
        #
        #self.decodedNzbSegmentsLock.release()
        #return False

        start = time.time()

        decodedSegmentFiles = []
        for nzbSegment in self.nzbSegments:
            decodedSegmentFiles.append(os.path.basename(nzbSegment.getDestination()))

        dirName = os.path.dirname(self.getDestination())
        for file in os.listdir(dirName):
            ####if re.match(self.filename + '\.hellanzb\d{4}$', file) and file in decodedSegmentFiles:
            if re.match('\.hellanzb\d{4}$', file):
                stripped = re.sub('\.hellanzb\d{4}', '', file)
                info('>')
                if re.match(file, self.subject):
                    # Found it -- this file is done
                    #info('!file: ' + file)
                    info('>>>>')
                    decodedSegmentFiles.remove(file)

        # Just be stupid -- we're only finished until we've found all the known files
        # (segments)
        if len(decodedSegmentFiles) == 0:
            finish = time.time() - start
            info('isAllSegmentsDecoded (T) took: ' + str(finish) + ' seconds')
            return True

        finish = time.time() - start
        info(self.filename + 'isAllSegmentsDecoded (F) took: ' + str(finish))
        #info(self.fileNameGuess + 'isAllSegmentsDecoded (F) took: ' + str(finish) + \
        #     ' seconds len: ' + str(len(decodedSegmentFiles)) + ' ' + str(decodedSegmentFiles))
        return False

    def __repr__(self):
        # FIXME
        return 'NZBFile subject: ' + str(self.subject) + 'fileNameGuess: ' + str(self.filename) + \
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
        #self.file = None
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
            #self.subject = attrs.get('subject')
            ##debug('subject: %s' % self.subject)
            ##self.posts[self.subject] = WrapPost()
            ##self.queue.put((NZB_CONTENT_P, ))
                
        elif name == 'group':
            self.chars = []
                        
        elif name == 'segment':
            self.bytes = int(attrs.get('bytes'))
            self.number = int(attrs.get('number'))
                        
            self.chars = []
                
            #print name, repr(attrs)
        
    def characters(self, content):
        if self.chars is not None:
            self.chars.append(content)
        
    def endElement(self, name):
        if name == 'file':
            #self.subject = None
            self.file = None
                
        elif name == 'group':
            newsgroup = ''.join(self.chars)
            #debug('group: ' + newsgroup)

            ##self.newsgroups.append(newsgroup)
            #FIXME: group - support multiple
            self.file.groups.append(newsgroup)
                        
            self.chars = None
                
        elif name == 'segment':
            #msgid = ''.join(self.chars)
            messageId = ''.join(self.chars)
            #self.posts[self.subject].add_part(self.number, msgid, self.bytes)
            #nzbs = NZBSegment(self.bytes, self.number, messageId, self.subject)
            nzbs = NZBSegment(self.bytes, self.number, messageId, self.file)
            self.file.nzbSegments.append(nzbs)
            self.queue.put((NZBQueue.NZB_CONTENT_P, nzbs))
                        
            self.chars = None
            self.number = None
            self.bytes = None    
