from xml.sax import make_parser
from xml.sax.handler import ContentHandler, feature_external_ges, feature_namespaces

def parseNZB(fileName):
    """ Initialize the queue from the specified nzb file """
    # Create a parser
    parser = make_parser()
    
    # No XML namespaces here
    parser.setFeature(feature_namespaces, 0)
    parser.setFeature(feature_external_ges, 0)
    
    # Create the handler
    #nzb = NZB(fileName)
    #dh = NZBParser(self, nzb)
    dh = NZBParser()
    
    # Tell the parser to use it
    parser.setContentHandler(dh)

    # Parse the input
    parser.parse(fileName)

    # In the case the NZBParser determined the entire archive's contents are already
    # on the filesystem, try to finish up (and move onto post processing)
    #if hasattr(Hellanzb, 'queue'):
    #    return tryFinishNZB(nzb)

    return (dh.groups, dh.queue)
        
class NZBParser(ContentHandler):
    """ Parse an NZB 1.0 file into a list of msgids
    http://www.newzbin.com/DTD/nzb/nzb-1.0.dtd """
    def __init__(self):
        # downloading queue to add NZB segments to
        self.queue = []

        # nzb file to parse
        #self.nzb = nzb
        self.groups = []

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

            #self.file = NZBFile(subject, attrs.get('date'), poster, self.nzb)
            #self.fileNeedsDownload = self.file.needsDownload()

            self.fileCount += 1
            #self.file.number = self.fileCount
                
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
            #self.file.groups.append(newsgroup)
            self.groups.append(self.parseUnicode(newsgroup))
                        
            self.chars = None
                
        elif name == 'segment':
            self.segmentCount += 1

            messageId = self.parseUnicode(''.join(self.chars))
            #nzbs = NZBSegment(self.bytes, self.number, messageId, self.file)
            #if self.segmentCount == 1:
            #    self.file.firstSegment = nzbs

            #if self.fileNeedsDownload:
                # HACK: Maintain the order in which we encountered the segments by adding
                # segmentCount to the priority. lame afterthought -- after realizing
                # heapqs aren't ordered. NZB_CONTENT_P must now be large enough so that it
                # won't ever clash with EXTRA_PAR2_P + i
            #    self.queue.put((NZBQueue.NZB_CONTENT_P + self.segmentCount, nzbs))
            self.queue.append(messageId)

            self.chars = None
            self.number = None
            self.bytes = None    

    def parseUnicode(self, unicodeOrStr):
        if isinstance(unicodeOrStr, unicode):
            return unicodeOrStr.encode('latin-1')
        return unicodeOrStr
