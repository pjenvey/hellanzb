#!/usr/bin/env python

"""
Looks at all .py files in the current directory and counts lines of actual
code.
"""

import os
import sys

# ---------------------------------------------------------------------------

def main():
	numfiles = numlines = codelines = commentlines = emptylines = 0
	
	for root, dirs, files in os.walk(os.path.realpath('.')):
		dirs.sort()
		files.sort()
		
		for filename in files:
			# We only want python
			if not filename.endswith('.py'):
				continue
			
			# Off we go
			numfiles += 1
			
			filepath = os.path.join(root, filename)
			f = open(filepath, 'r')
			
			for line in f:
				numlines += 1
				
				line = line.strip()
				# Empty
				if not line:
					emptylines += 1
					continue
				# Comment
				if line.startswith('#'):
					commentlines += 1
					continue
				# Probably code
				codelines += 1
			
			f.close()
	
	# All done
	print '%d source files, %d total lines - %d code, %d comment, %d space' % (numfiles, numlines, codelines, commentlines, emptylines)

# ---------------------------------------------------------------------------

if __name__ == '__main__':
	main()
