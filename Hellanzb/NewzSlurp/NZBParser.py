# ---------------------------------------------------------------------------
# $Id: NZBParser.py,v 1.2 2004/09/28 16:03:15 freddie Exp $
# ---------------------------------------------------------------------------

"Simple-ish XML parser for .nzb files."

from xml.sax import make_parser
from xml.sax.handler import ContentHandler, feature_external_ges, feature_namespaces
# <DEBUGGING>
import sys
sys.path.append('/home/pjenvey/src/hellanzb-asynchella')
# </DEBUGGING>


# ---------------------------------------------------------------------------

def ParseNZB(filename):
        # Create a parser
        parser = make_parser()
        
        # No XML namespaces here
        parser.setFeature(feature_namespaces, 0)
        parser.setFeature(feature_external_ges, 0)
        
        # Dicts to shove things into
        newsgroups = {}
        posts = {}
        
        # Create the handler
        dh = NZBParser(newsgroups, posts)
        
        # Tell the parser to use it
        parser.setContentHandler(dh)
        
        # Parse the input
        parser.parse(filename)
        
        return (newsgroups, posts)

# ---------------------------------------------------------------------------

class WrapPost:
        def __init__(self):
                self.numparts = 0
                self.totalbytes = 0
                
                self.parts = {}
        
        def __repr__(self):
                return '<WrapPost: %d parts, %d bytes>' % (self.numparts, self.totalbytes)
        
        # Add a new part to our data chunks
        def add_part(self, partnum, msgid, bytes):
                if not msgid.startswith('<') and not msgid.startswith('>'):
                        msgid = '<%s>' % msgid
                
                if not partnum in self.parts:
                        self.parts[partnum] = []
                        self.parts[partnum].append(msgid)
                        
                        self.numparts += 1
                        self.totalbytes += bytes
                
        
        # Return the next part
        def get_next_part(self):
                parts_i = self.parts.items()
                parts_i.sort()
                
                return parts_i[0]



class NZBParser(ContentHandler):
        def __init__(self, newsgroups, posts):
                self.newsgroups = newsgroups
                self.posts = posts
                
                self.chars = None
                self.subject = None
                
                self.bytes = None
                self.partnum = None
        
        def startElement(self, name, attrs):
                if name == 'file':
                        self.subject = attrs.get('subject')
                        #print 'subject: %s' % self.subject
                        
                        self.posts[self.subject] = WrapPost()
                
                elif name == 'group':
                        self.chars = []
                
                elif name == 'segment':
                        self.bytes = int(attrs.get('bytes'))
                        self.partnum = int(attrs.get('number'))
                        
                        self.chars = []
                
                #print name, repr(attrs)
        
        def characters(self, content):
                if self.chars is not None:
                        self.chars.append(content)
        
        def endElement(self, name):
                if name == 'file':
                        self.subject = None
                
                elif name == 'group':
                        newsgroup = ''.join(self.chars)
                        #print 'group:', newsgroup
                        self.newsgroups[newsgroup] = 1
                        
                        self.chars = None
                
                elif name == 'segment':
                        msgid = ''.join(self.chars)
                        self.posts[self.subject].add_part(self.partnum, msgid, self.bytes)
                        
                        self.chars = None
                        self.partnum = None
                        self.bytes = None

# ---------------------------------------------------------------------------

if __name__ == '__main__':
        import sys
        #(newsgroups, posts) = ParseNZB(sys.argv[1], [1, 2])
        (newsgroups, posts) = ParseNZB(sys.argv[1])
        for n in newsgroups:
                print "n: " + n
        print 'l: ' + str(len(posts))
        total = 0
        from Hellanzb.Util import PriorityQueue
        pq = PriorityQueue()
        NZB_CONTENT_P = 25
        from time import time
        start = time()
        for p in posts:
                print "p: " + p
                print "contents: " + posts[p].__repr__()
                total += posts[p].numparts
                for part in posts[p].parts:
                        pq.put((NZB_CONTENT_P, posts[p].parts[part], True))

        elapsed = time() - start
        print 'elapsed: ' + str(elapsed)
        print 'total: ' + str(total)

        #while 1:
        #        print 'p:' + str(pq.get(True)[1])

        

from xml.sax import make_parser
from xml.sax.handler import ContentHandler, feature_external_ges, feature_namespaces
# <DEBUGGING>
#import sys
#sys.path.append('/home/pjenvey/src/hellanzb-asynchella')
# </DEBUGGING>
from Hellanzb.Util import PriorityQueue
class NZBQueue(PriorityQueue):
    def parseNZB(self, fileName):
        # Create a parser
        parser = make_parser()
        
        # No XML namespaces here
        parser.setFeature(feature_namespaces, 0)
        parser.setFeature(feature_external_ges, 0)
        
        # Dicts to shove things into
        newsgroups = {}
        posts = {}
        
        # Create the handler
        dh = NZBParser(newsgroups, posts)
        
        # Tell the parser to use it
        parser.setContentHandler(dh)
        
        # Parse the input
        parser.parse(filename)
        
        return (newsgroups, posts)                
