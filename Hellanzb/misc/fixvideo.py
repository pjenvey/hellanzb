#!/usr/bin/env python

import os
import sys

# ---------------------------------------------------------------------------
"""
No idea: \x00\x00\x01\xba\x2f\xff\xff\x13
^ MPEG1 video with MPEG2 audio?

No idea: \x00\x00\x01\xb3\x0a\x00\x78\x15
No idea: \x00\x00\x01\xb3\x0a\x00\x78\x15
No idea: \x00\x00\x01\xb3\x0a\x00\x78\x15
No idea: \x00\x00\x01\xb3\x0a\x00\x78\xc4
No idea: \x00\x00\x01\xb3\x0c\x80\x96\x15
No idea: \x00\x00\x01\xb3\x13\x00\xe4\x12
No idea: \x00\x00\x01\xb3\x14\x00\xf0\x13
No idea: \x00\x00\x01\xb3\x14\x00\xf0\x14
No idea: \x00\x00\x01\xb3\x14\x00\xf0\x14
No idea: \x00\x00\x01\xb3\x14\x00\xf0\x15
No idea: \x00\x00\x01\xb3\x16\x00\xc4\x23
No idea: \x00\x00\x01\xba\x2f\xff\xf9\xed
No idea: \x00\x00\x01\xba\x2f\xff\xff\x13
No idea: \x00\x00\x01\xba\x2f\xff\xff\xab
^ All .mpg files

No idea: \xd7\x7c\xad\xab\x04\x61\xe9\xb8
^ Weird .mpg
"""

MARKERS = (
	('avi', 'RIFF'),
	('m2v', '\x00\x00\x01\xba\x44'),
	('mkv', '\x1a\x45\xdf\xa3\x93\x42\x82\x88\x6d\x61\x74\x72'),
	('mov', '\x00\x03\x17\xe2\x6d\x6f\x6f\x76'),
	('mpg', '\x00\x00\x01\xba\x21'),
	('ogm', '\x4f\x67\x67\x53\x00\x02\x00\x00'),
	('wmv', '\x30\x26\xb2\x75\x8e\x66\xcf\x11'),
)

# ---------------------------------------------------------------------------

def main():
	for filename in sys.argv[1:]:
		try:
			fileid = open(filename).read(32)
		except IOError, msg:
			print 'Failed to open %s: %s' % (filename, msg)
			continue
		
		found = 0
		
		for marker in MARKERS:
			for magic in marker[1:]:
				if fileid[:len(magic)] == magic:
					root, ext = os.path.splitext(filename)
					newname = '%s.%s' % (root, marker[0])
					
					if newname != filename:
						print filename, '-->', newname
						os.rename(filename, newname)
					
					found = 1
					break
			
			if found:
				break
		
		if not found:
			hexid = ''
			for char in fileid:
				hexid += "\\x%02x" % ord(char)
			
			print "No idea: %s - %s" % (hexid, filename)
			continue
		

# ---------------------------------------------------------------------------

if __name__ == '__main__':
	main()
