#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-

"""
Fairly simple script to 'properly' rename TV episodes using information
gathered from epguides.com.
"""

__author__ = 'Freddie (freddie@madcowdisease.org)'
__version__ = '0.6'

# ---------------------------------------------------------------------------

import getopt
import glob
import httplib
import os
import re
import sys

# ---------------------------------------------------------------------------
# Filename format string. The 's' or '02d' after the field name are printf
# format specifiers.
#
# epguide : Squished epguides name of the show, ie 'JoanofArcadia'
# show    : Full name of the show, ie 'Joan of Arcadia'
# season  : Season number
# episode : Episode number
# airdate : Episode air date, ie '03 Jan 45'
# title   : Episode title

# My way! "Joan of Arcadia - S01E01 - Pilot"
FILENAME_FORMAT = '%(show)s - S%(season)02dE%(episode)02d - %(title)s'

# Other way! "1-1 JoanOfArcadia 26 Sep 03 [Pilot]"
#FILENAME_FORMAT = '%(season)d-%(episode)d %(epguide)s %(airdate)s [%(title)s]'

# ---------------------------------------------------------------------------
# Common dir name mappings to actual show names
SHOW_MAP = {
	'CSINewYork': 'CSINY',
	'The4400': '4400',
	'TheDA': 'DA_2004',
	'TheGrid': 'Grid_2004',
	'TheOuterLimits': 'OuterLimits_1995',
	'ThePretender': 'Pretender',
	'TheSimpsons': 'Simpsons',
	'TouchingEvil': 'TouchingEvil_US',
}

# Annoying shows that list the Pilot as two seperate episodes
BROKEN_PILOT = (
	'TouchingEvil_US',
)

# ---------------------------------------------------------------------------

TITLE_RE = re.compile(r'^(.+)\s\(a Titles')
EPISODE_RE = re.compile(r'^\s*(?:<li>|\d+\.)\s+(\d+)-\s*(\d+)\s+(?:\S+\s+|)(\d+ \w+ \d+)\s+(?:<a.*?>|)(.*?)(?:</a>|)\s*$')

FILENAME_REs = (
	re.compile('S(\d{1,2})\.?E(\d{1,3})', re.I),
	re.compile('(\d{1,2})[x-](\d{1,3})', re.I),
	re.compile('[-\. ]([12]\d|\d)(\d\d)[-\. ]'),
)

# ---------------------------------------------------------------------------

def Show_Usage():
	print 'USAGE: fixtv.py [-cd] <show name> <file1> [file2] ... [fileN]'
	print
	print '-c : use the current directory for the show name'
	print '-d : actually rename the files'
	print
	print '<show name> should be the epguides.com directory name, ie'
	print '"JoanofArcadia" or "Jake20".'
	sys.exit(1)

def main():
	# Parse our command line arguments
	try:
		opts, args = getopt.getopt(sys.argv[1:], "cd", [])
	except getopt.GetoptError:
		Show_Usage()
	
	# Check our options
	CURRDIR = 0
	DOIT = 0
	
	for opt, _ in opts:
		if opt == '-c':
			CURRDIR = 1
		elif opt == '-d':
			DOIT = 1
	
	# Make sure we have enough parameters
	if CURRDIR:
		if len(args) < 1:
			Show_Usage()
	elif len(args) < 2:
		Show_Usage()
	
	# Spit out our banner
	print 'fixtv.py v%s by %s' % (__version__, __author__)
	print
	
	# Go fetch our show info
	if CURRDIR:
		show = os.path.split(os.getcwd())[-1]
		for char in (' ', "'", '-', '.'):
			show = show.replace(char, '')
		
		# Maybe map it to something else
		show = SHOW_MAP.get(show, show)
	
	else:
		show = args.pop(0)
	
	uri = 'http://www.epguides.com/%s/' % (show)
	headers = {	'User-Agent': 'Mozilla/4.0 (compatible; MSIE 4.01; Windows 98)' }
	
	conn = httplib.HTTPConnection('www.epguides.com')
	conn.request('GET', uri, headers=headers)
	
	# Get the response
	resp = conn.getresponse()
	
	# If it was a 404, we're stuffed
	if resp.status == 404:
		print 'ERROR: Unable to find TV show "%s"' % (show)
		sys.exit(2)
	
	# If it was a 200, we're fine!
	elif resp.status == 200:
		info = {}
		
		# Might as well remember this now
		info['epguide'] = show
		
		# Read the data and split it into lines
		lines = UnquoteHTML(resp.read()).splitlines()
		
		# Clean up our connections
		resp.close()
		conn.close()
		
		# Find the title of this show
		info['show'] = ''
		
		for i in range(3, 10):
			m = TITLE_RE.match(lines[i])
			if m:
				info['show'] = Safe_Filename(m.group(1))
				break
		
		if info['show'] == '':
			print 'ERROR: unable to find title for this show!'
			sys.exit(2)
		
		# Eat any stupid brackets
		m = re.match(r'^(.*?) \(.*?\)$', info['show'])
		if m:
			info['show'] = m.group(1)
		
		# Find the episode information
		episodes = {}
		
		for line in lines:
			m = EPISODE_RE.match(line)
			if m:
				# season, episode, air date, title
				season = int(m.group(1))
				episode = int(m.group(2))
				
				if season not in episodes:
					episodes[season] = {}
				
				n = m.group(4).find('</a>')
				if n >= 0:
					episodes[season][episode] = (m.group(3), m.group(4)[:n])
				else:
					episodes[season][episode] = (m.group(3), m.group(4))
		
		# If we found no episodes, we have a problem
		if episodes == {}:
			print "ERROR: Couldn't find any episode information for '%s'!" % (args[0])
			sys.exit(2)
		
		# Expand globs on windows now
		if os.name == 'nt':
			newargs = []
			for arg in args:
				if '*' in arg:
					newargs.extend(glob.glob(arg))
				else:
					newargs.append(arg)
			args = newargs
		
		# Go through our episodes, trying to match them
		args.sort()
		
		for filename in args:
			# Don't do anything for files that aren't files/there
			if not os.path.isfile(filename):
				print "WARN: '%s' is not a file, or does not exist!" % (filename)
				continue
			
			found = 0
			
			# Try to match the season/episode info with our regexp collection
			for regexp in FILENAME_REs:
				m = regexp.search(filename)
				if m:
					season = int(m.group(1))
					episode = int(m.group(2))
					
					# Find out if we have info for this episode
					if show in BROKEN_PILOT and episode > 1:
						epinfo = episodes.get(season, {}).get(episode + 1, None)
					else:
						epinfo = episodes.get(season, {}).get(episode, None)
					
					if epinfo == None:
						print 'WARN: no episode info for "%s / %d / %d"' % (info['show'], season, episode)
						found = 1
						break
					
					# Fix up a broken pilot title
					if show in BROKEN_PILOT and episode == 1 and epinfo[1].endswith(' (1)'):
						eptitle = epinfo[1][:-4]
					else:
						eptitle = epinfo[1]
					
					# Fill in the bits of info we need
					info['season'] = season
					info['episode'] = episode
					info['airdate'] = epinfo[0]
					info['title'] = Safe_Filename(eptitle)
					
					# Make up the new name
					newname = FILENAME_FORMAT % info
					
					# Get our filename extension
					root, ext = os.path.splitext(filename)
					newname = newname + ext.lower()
					
					# If the new name is the same as the old one, do nothing
					if newname == filename:
						pass
					
					# If the new name already exists, do nothing
					elif os.path.exists(newname):
						print "WARN: '%s' already exists, not clobbering!" % (newname)
					
					# Otherwise, rename!
					else:
						print '%s --> %s' % (filename, newname)
						if DOIT:
							os.rename(filename, newname)
					
					found = 1
					break
			
			# If we didn't find anything, grumble
			if found == 0:
				print "WARN: unable to get season/episode from '%s'!" % (filename)
	
	# If it was another sort of response, we have no idea what happened
	else:
		print "ERROR: unknown HTTP response '%s'" % (resp.status)

# ---------------------------------------------------------------------------
# Make a "safe" filename that is valid on most systems (Windows at least).
# Removes the following characters:
#   \ | / : * ? < > "
# ---------------------------------------------------------------------------
def Safe_Filename(safe):
	safe = safe.replace('F*ck', 'Fuck')
	
	for char in ["\\", '|', '/', ':', '*', '?', '<', '>', '"']:
		safe = safe.replace(char, '')
	
	return safe

# ---------------------------------------------------------------------------
# Replace &blah; quoted things with the actual thing
def UnquoteHTML(text):
	# thing name -> char
	quoted = {
		'lt': '<',
		'gt': '>',
		'amp': '&',
		'quot': '"',
		'nbsp': ' ',
		'ordm': '°',
		'agrave': 'a',
	}
	
	# regexp helper function to do the replacement
	def unquote_things(m):
		whole = m.group(0)
		thing = m.group(1).lower()
		if thing.startswith('#'):
			try:
				return chr(int(thing[1:]))
			except ValueError:
				return whole
		else:
			return quoted.get(thing, whole)
	
	# go!
	return re.sub(r'&([#A-Za-z0-9]+);', unquote_things, text)

# ---------------------------------------------------------------------------

if __name__ == '__main__':
	main()
