'A wrapper around a post.'


class WrapPost:
        def __init__(self):
                self.numparts = 0
                self.totalbytes = 0
                
                self.parts = {}
        
        def __repr__(self):
                return '<WrapPost: %d parts, %d bytes>' % (self.numparts, self.totalbytes)
        
        # Add a new part to our data chunks
        def add_part(self, partnum, msgid, bytes, servers):
                if not msgid.startswith('<') and not msgid.startswith('>'):
                        msgid = '<%s>' % msgid
                
                if not partnum in self.parts:
                        self.parts[partnum] = []
                        self.parts[partnum].append(msgid)
                        
                        self.numparts += 1
                        self.totalbytes += bytes
                
                for swrap in servers:
                        if msgid == self.parts[partnum][0]:
                                self.parts[partnum].append(swrap)
        
        # Return the next part
        def get_next_part(self):
                parts_i = self.parts.items()
                parts_i.sort()
                
                return parts_i[0]
