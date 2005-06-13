#!/usr/bin/env python

'Find duplicate files with MD5 checksums'

import md5
import os
import sys

# ---------------------------------------------------------------------------

def main():
	# We want at least two files
	if len(sys.argv) < 3:
		print "USAGE: md5dupe.py <file1> <file2> ... [fileN]"
		sys.exit(1)
	
	md5sums = {}
	
	for filename in sys.argv[1:]:
		# We don't want broken things
		if not os.access(filename, os.R_OK):
			print '* %s does not exist or is not readable!' % (filename)
			continue
		
		# And we only want files
		if not os.path.isfile(filename):
			print '* %s is not a file!' % (filename)
		
		# Make the new sum
		md5sum = md5.new(open(filename, 'rb').read()).hexdigest()
		
		md5sums.setdefault(md5sum, []).append(filename)
	
	# See if we have any duplicates
	dupes = [(md5sum, fns) for md5sum, fns in md5sums.items() if len(fns) > 1]
	dupes.sort()
	for md5sum, fns in dupes:
		print '%s :: %s' % (md5sum, ', '.join(fns))

# ---------------------------------------------------------------------------

if __name__ == '__main__':
	main()
