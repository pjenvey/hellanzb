#!/usr/bin/env python

"""
Simple-ish script to grab .nzb files from Newzbin.

Make a file in your home directory called '.grabnzb.conf'. On the first line,
put your Newzbin username, and on the second line put your password.
"""

import getopt
import httplib
import os
import sys
import time
import urllib

__author__ = 'Freddie (freddie@madcowdisease.org)'
__version__ = '0.4'

# --------------------
# v0.4      2004-10-10
# --------------------
# Switch to using httplib and doing redirects/etc ourselves, urllib sucks.
# Big mangling to work with changed Newzbin pages (again).
# Change our User-Agent to our own name, might as well not hide.
# --------------------
# v0.3      2004-08-09
# --------------------
# Also save the returned headers when debug is on.
# Give a nice error when we don't manage to find any files.
# Fix the file retrieval match.
# Fix the option parsing junk.
# --------------------
# v0.2      2004-08-08
# --------------------
# Fix our cookie code to login properly.
# Add a -d (debug) command line option.
# Improve error handling a bit.

# ---------------------------------------------------------------------------

def ShowUsage():
	print "USAGE: grabnzb.py [-d] <num> [num] [num]"
	print
	print "-d  - Write debug information to files."
	print
	print "num - Newzbin post number to grab."
	sys.exit(2)

# ---------------------------------------------------------------------------

def main():
	# Parse our command line options
	try:
		opts, args = getopt.getopt(sys.argv[1:], "d", [])
	except getopt.GetoptError:
		Show_Usage()
	
	DEBUG = 0
	for opt, arg in opts:
		if opt == '-d':
			DEBUG = 1
	
	# Make sure we have some arguments
	if len(args) < 1:
		ShowUsage()
	
	# Load our info
	confname = os.path.expanduser('~/.grabnzb.conf')
	print 'Loading info from %s...' % confname,
	sys.stdout.flush()
	
	lines = open(confname, 'r').readlines()
	username = lines[0].strip()
	password = lines[1].strip()
	
	print 'done.'
	
	# See if we have to login
	print 'Checking auth cookie...',
	sys.stdout.flush()
	
	phpsessid = None
	
	cookname = os.path.expanduser('~/.grabnzb.cookie')
	if os.access(cookname, os.R_OK):
		phpsessid = CheckCookie(cookname)
		if phpsessid:
			print 'OK.'
	
	headers = {
		'Referer': 'http://www.newzbin.com',
		'User-Agent': 'grabnzb.py %s' % __version__,
	}
	
	# Guess we have to login
	if phpsessid is None:
		print 'no data, logging in...',
		sys.stdout.flush()
		
		# Fetch the URL!
		conn = httplib.HTTPConnection('www.newzbin.com')
		if DEBUG:
			conn.debuglevel = 1
		
		postdata = urllib.urlencode({'username': username, 'password': password})
		headers['Content-type'] = 'application/x-www-form-urlencoded'
		conn.request('POST', '/account/login/', postdata, headers)
		
		response = conn.getresponse()
		
		# Save debug info if we have to
		data = response.read()
		if DEBUG:
			f = open('debug.login', 'w')
			f.write(str(response.msg.dict))
			f.write(data)
			f.close()
		
		# Try getting our cookie
		try:
			cookie = response.getheader('Set-Cookie')
		except KeyError:
			print 'failed!'
			sys.exit(1)
		
		# Save the cookie
		open(cookname, 'w').write('%s\n' % cookie)
		
		phpsessid = CheckCookie(cookname)
		if phpsessid is None:
			print 'failed, wtf?'
			sys.exit(0)
		
		# Follow the redirect
		del headers['Content-type']
		
		location = response.getheader('Location')
		if not location or not location.startswith('http://www.newzbin.com/'):
			print 'failed, wtf?'
			sys.exit(0)
		
		conn.request('GET', location, headers=headers)
		
		response = conn.getresponse()
		conn.close()
		
		if response.status == 200:
			print 'OK.'
		else:
			print 'failed, wtf?'
			sys.exit(0)
	
	# Add our cookie for later attempts
	headers['Cookie'] = 'PHPSESSID=%s' % (phpsessid)
	
	# Off we go then
	conn = httplib.HTTPConnection('www.newzbin.com')
	if DEBUG:
		conn.debuglevel = 1
	
	for num in args:
		print 'Checking NZB #%s...' % num,
		sys.stdout.flush()
		
		# Reset the headers we care about
		if 'Content-type' in headers:
			del headers['Content-type']
		headers['Referer'] = 'http://www.newzbin.com'
		
		# Go fetch
		browseurl = 'http://www.newzbin.com/browse/post/%s/' % num
		conn.request('GET', browseurl, headers=headers)
		response = conn.getresponse()
		
		# Save debug info if we have to
		data = response.read()
		if DEBUG:
			f = open('debug.check.%s' % num, 'w')
			f.write(str(response.msg.dict))
			f.write(data)
			f.close()
		
		# Save our latest cookie expiry
		cookie = response.getheader('Set-Cookie')
		if cookie is not None:
			open(cookname, 'w').write('%s\n' % cookie)
		
		# Ruh-roh
		if data.find('The specified post does not exist.') >= 0:
			print 'post not found!'
			continue
		elif data.find('No files attached') >= 0:
			print 'has no files!'
			continue
		elif data.find('you must be logged in') >= 0:
			print "you're not logged in?!"
			sys.exit(1)
		
		# Build our huge post data string
		postdata = { 'msgidlist': 'Get Message-IDs' }
		
		# Find all of the attached files :0
		chunks = FindChunks(data, ')" type="checkbox" name="', '" checked="checked"')
		for chunk in chunks:
			if chunk.isdigit():
				postdata[chunk] = 'on'
		
		# Oops, no files here
		if len(postdata) == 1:
			print 'no files found!'
			continue
		
		postdata = urllib.urlencode(postdata)
		
		# Grab it
		print 'fetching...',
		sys.stdout.flush()
		
		# Fake some referer here too
		headers['Content-type'] = 'application/x-www-form-urlencoded'
		headers['Referer'] = browseurl
		
		fetchurl = 'http://www.newzbin.com/database/post/edit/?ps_id=%s' % num
		conn.request('POST', fetchurl, postdata, headers)
		response = conn.getresponse()
		
		# Save debug info if we have to
		data = response.read()
		if DEBUG:
			f = open('debug.fetch.%s' % num, 'w')
			f.write(str(response.msg.dict))
			f.write(data)
			f.close()
		
		# Follow the redirect again
		del headers['Content-type']
		headers['Referer'] = fetchurl
		
		location = response.getheader('Location')
		if not location or not location.startswith('http://www.newzbin.com/'):
			print 'redirect failed, ruh-roh!'
			continue
		
		conn.request('GET', location, headers=headers)
		response = conn.getresponse()
		data = response.read()
		
		# Get the filename
		cd = response.getheader('Content-Disposition')
		n = cd.find('filename=')
		if n >= 0:
			newname = cd[n+9:]
			print 'saved as %s.' % newname
		# Or just make one up
		else:
			newname = 'msgid_%s.nzb' % num
			print 'no name! saved as %s.' % newname
		
		# Save it!
		open(newname, 'w').write(data)
		
# ---------------------------------------------------------------------------
# Check our cookie, possibly returning the session id
def CheckCookie(filename):
	cookie = open(filename, 'r').readlines()[0]
	expiretime = FindChunk(cookie, 'expires=', ' GMT')
	
	# Sun, 08-Aug-2004 08:57:42	
	t = time.strptime(expiretime, '%a, %d-%b-%Y %H:%M:%S')
	now = time.gmtime()
	
	# Woops, expired
	if now > t:
		os.remove(filename)
		return None
	else:
		phpsessid = FindChunk(cookie, 'PHPSESSID=', ';')
		if phpsessid is None or phpsessid == 'None':
			return None
		else:
			return phpsessid

# ---------------------------------------------------------------------------
# Search through text, finding the chunk between start and end.
def FindChunk(text, start, end, pos=None):
	# Can we find the start?
	if pos is None:
		startpos = text.find(start)
	else:
		startpos = text.find(start, pos)
	
	if startpos < 0:
		return None
	
	startspot = startpos + len(start)
	
	# Can we find the end?
	endpos = text.find(end, startspot)
	if endpos <= startspot:
		return None
	
	# Ok, we have some text now
	chunk = text[startspot:endpos]
	if len(chunk) == 0:
		return None
	
	# Return!
	if pos is None:
		return chunk
	else:
		return (endpos+len(end), chunk)

# As above, but return all matches. Poor man's regexp :)
def FindChunks(text, start, end, limit=0):
	chunks = []
	n = 0
	
	while 1:
		result = FindChunk(text, start, end, n)
		if result is None:
			return chunks
		else:
			chunks.append(result[1])
			if limit and len(chunks) == limit:
				return chunks
			n = result[0]

# ---------------------------------------------------------------------------

if __name__ == '__main__':
	main()
