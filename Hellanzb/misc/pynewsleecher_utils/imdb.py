#!/usr/bin/python

"""
Search the Internet Movie Database for information on movies. Spits out title,
year, and the IMDB number.
"""

import httplib
import re
import sys
import urllib

from HTMLParser import HTMLParser

# ---------------------------------------------------------------------------

SEARCH_URL = "http://us.imdb.com/Tsearch?type=fuzzy&sort=smart&tv=off&title=%s"
RE_TITLE_YEAR = re.compile(r'^(?P<title>.*) \((?P<year>\d+)\S*\)$')

# ---------------------------------------------------------------------------

class IMDBParser(HTMLParser):
	def __init__(self):
		HTMLParser.__init__(self)
		
		self.matches = []
		self.status = 0
	
	def handle_starttag(self, tag, attributes):
		attrs = {}
		for key, value in attributes:
			attrs[key] = value
		
		if self.status == 0:
			if tag == 'a' and attrs.get('name', '') == 'mov':
				self.status = 1
		
		elif self.status == 1:
			if tag == 'a' and attrs.get('href', ''):
				imdbnum = attrs['href'][-8:-1]
				self.matches.append([])
				self.matches[-1].append(imdbnum)
				self.status = 2
	
	def handle_endtag(self, tag):
		if self.status == 1 and tag == 'ol':
			self.status = 0
		
		elif self.status == 2 and tag == 'a':
			self.status = 1
	
	def handle_data(self, data):
		if self.status == 2:
			m = RE_TITLE_YEAR.match(data)
			if not m:
				return
			
			self.matches[-1].append(m.group('year'))
			self.matches[-1].append(m.group('title'))
			self.status = 1

# ---------------------------------------------------------------------------

def Search(title):
	uri = SEARCH_URL % urllib.quote_plus(title)
	headers = {	'User-Agent': 'Mozilla/4.0 (compatible; MSIE 4.01; Windows 98)' }
	
	conn = httplib.HTTPConnection('us.imdb.com')
	conn.request('GET', uri, headers=headers)
	
	resp = conn.getresponse()
	data = resp.read()
	
	parser = IMDBParser()
	parser.feed(data)
	
	matches = parser.matches[:]
	
	found = 0
	tlower = title.lower()
	for info in matches:
		try:
			if info[2].lower() == tlower:
				if not found:
					print 'Found some exact matches:'
					found = 1
				print "INSERT INTO movies (imdb, year, name, format, discs) values ('%s', %s, '%s', " % tuple(info)
		except IndexError:
			print '--DANGER WILL ROBINSON--'
			return
	
	if not found:
		print 'Found %d possible matches for "%s":' % (len(matches), title)
		for info in matches:
			print "INSERT INTO movies (imdb, year, name, format, discs) values ('%s', %s, '%s', " % tuple(info)
	
	print

# ---------------------------------------------------------------------------

def main():
	if len(sys.argv) < 2:
		print 'USAGE: imdb.py "movie 1" "movie 2" ... "movie n"'
		print
		sys.exit(-1)
	
	for title in sys.argv[1:]:
		Search(title)

# ---------------------------------------------------------------------------

if __name__ == '__main__':
	main()
