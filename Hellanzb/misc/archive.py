#!/usr/bin/env python

"""Do something for nyx?"""

__author__ = 'Freddie (freddie@madcowdisease.org)'
__version__ = '0.1'

# ---------------------------------------------------------------------------

import getopt
import os
import re
import sys

# ---------------------------------------------------------------------------

FILENAME_REs = (
	re.compile('S(\d{1,2})E(\d{1,3})', re.I),
	re.compile('\.(\d{1,2})(\d\d)\.'),
	re.compile('(\d{1,2})[x-](\d{1,3})', re.I),
)

# Format for the new filenames. The %s is the original filename, minus it's
# extension
FILENAME_FORMAT = "%s - ON DVD"

# ---------------------------------------------------------------------------

def Show_Usage():
	print 'USAGE: archive.py [-d] <season> <ep range>'
	print
	print '-d : actually truncate/rename the files'
	sys.exit(1)

def main():
	# Parse our command line arguments
	try:
		opts, args = getopt.getopt(sys.argv[1:], "d", ["do"])
	except getopt.GetoptError:
		Show_Usage()
	
	# If we have -d, party
	if opts:
		DOIT = 1
	else:
		DOIT = 0
	
	# Make sure we have enough parameters
	if len(args) < 2:
		Show_Usage()
	
	# Check the season
	try:
		Season = int(args[0])
	except ValueError:
		print 'ERROR: Invalid season!'
		sys.exit(1)
	
	# Check the episode range
	chunks = args[1].split('-')
	if len(chunks) != 2:
		print 'ERROR: Invalid episode range!'
		sys.exit(1)
	
	try:
		EpStart = int(chunks[0])
		EpEnd = int(chunks[1])
	except ValueError:
		print 'ERROR: Invalid episode range!'
	
	# Look in the current dir for the files
	files = os.listdir('.')
	files.sort()
	
	for filename in files:
		# Don't do anything for non-files
		if not os.path.isfile(filename):
			print "WARN: '%s' is not a file, or does not exist!" % (filename)
			continue
		
		# Try to match the season/episode info with our regexp collection
		for regexp in FILENAME_REs:
			m = regexp.search(filename)
			if m:
				season = int(m.group(1))
				episode = int(m.group(2))
				
				# If it's in the range we're after, squish it
				if season == Season and EpStart <= episode <= EpEnd:
					# Split our filename into bits
					root, ext = os.path.splitext(filename)
					
					# Build the new name
					newname = FILENAME_FORMAT % (root)
					newname = newname + ext.lower()
					
					# If we have to...
					if DOIT:
						# Truncate the file...
						blah = open(filename, 'w')
						blah.close()
						
						# And rename it!
						os.rename(filename, newname)
					
					# Say we did it!
					print "%s --> %s" % (filename, newname)
				
				break

# ---------------------------------------------------------------------------

if __name__ == '__main__':
	main()
