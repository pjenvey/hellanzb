#!/usr/bin/env python
#----------------------------------------------------------------------------
# $Id: pynewsleecher.py,v 1.62 2004/08/01 08:22:46 freddie Exp $
#----------------------------------------------------------------------------

'yEnc capable newsgroup leecher, using an SQL database for header storage.'

__version__ = '0.7'

#----------------------------------------------------------------------------

import getopt
import os
import sys

from ConfigParser import ConfigParser

from classes.HeadHoncho import HeadHoncho

# ---------------------------------------------------------------------------

def ShowUsage():
	print "USAGE: newsleecher.py [-p] <group:match OR nzbfile> [group:match OR nzbfile]"
	print
	print "-p      - run with the python profiler active"
	print
	print "group   - either the full name or an alias for the newsgroup"
	print "match   - text string to match against the subject"
	print "nzbfile - path to a .nzb file to use"
	
	sys.exit(-1)

# ---------------------------------------------------------------------------

def main():
	print "pynewsleecher %s by Freddie (freddie@madcowdisease.org)" % __version__
	print
	
	# Parser our options
	try:
		opts, args = getopt.getopt(sys.argv[1:], 'p', [ 'profile' ])
	except getopt.GetoptError:
		ShowUsage()
	
	Profiled = 0
	for opt, arg in opts:
		if opt in ('-p', '--profile'):
			Profiled = 1
			print 'Running with hotshot profiler.'
	
	# Verify parameters
	if len(args) < 1:
		ShowUsage()
	
	# Read and verify our config file
	global Config
	Config = ConfigParser()
	
	confname = os.path.expanduser('~/.newsleecher.conf')
	print 'Loading options from %s' % confname
	Config.read(confname)
	print
	
	# Get ready, HeadHoncho!
	hh = HeadHoncho(Config, args)
	
	# Maybe profile it
	if Profiled:
		import hotshot
		prof = hotshot.Profile('pynl.prof')
		prof.runcall(hh.main_loop)
		prof.close()
		
		# Print some profile stats
		import hotshot.stats
		stats = hotshot.stats.load('pynl.prof')
		stats.strip_dirs()
		stats.sort_stats('time', 'calls')
		stats.print_stats(30)
	
	# Or not
	else:
		hh.main_loop()

# ---------------------------------------------------------------------------

if __name__ == '__main__':
	main()
