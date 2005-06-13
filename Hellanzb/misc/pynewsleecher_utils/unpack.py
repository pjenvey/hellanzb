#!/usr/bin/env python

__version__ = '0.3.0'

"""
This is a not particularly simple script to ease the burden of unpacking
annoying RAR archive sets. I wrote this for a friend, and it seems to work
fairly well, so here it is :)

  USAGE: unpack.py <directory>
  
  This will unpack any RAR archives (including files in CDn directories) to
  the current directory. It will also copy any .nfo files it finds to the
  current directory for you.
"""

# ---------------------------------------------------------------------------

import getopt
import os
import re
import shutil
import sys
import time

# ---------------------------------------------------------------------------
# Find rar/unrar and vcdgear
RAR_COMMAND = None
VCDGEAR_COMMAND = None

# Windows uses semicolon, how rude
if os.name == 'nt':
	lookhere = os.getenv('PATH').split(';')
	findrar = ('rar.exe', 'unrar.exe')
	findvcdg = ()
else:
	lookhere = os.getenv('PATH').split(':')
	findrar = ('rar', 'unrar', 'rar3', 'unrar3')
	findvcdg = ('vcdgear',)

for path in lookhere:
	if not RAR_COMMAND:
		for rar in findrar:
			rar_path = os.path.join(path, rar)
			if os.access(rar_path, os.X_OK):
				RAR_COMMAND = rar_path
				break
	
	if not VCDGEAR_COMMAND:
		for vcdg in findvcdg:
			vcdg_path = os.path.join(path, vcdg)
			if os.access(vcdg_path, os.X_OK):
				VCDGEAR_COMMAND = vcdg_path
				break
# ---------------------------------------------------------------------------

RAR_RE = re.compile(r'\.(?P<ext>rar|r\d\d|\d\d\d)$', re.I)

# ---------------------------------------------------------------------------

def Error(text, *args):
	if args:
		text = text % args
	print
	print 'ERROR:', text
	sys.exit(-1)

def main():
	# Parse our command line arguments
	try:
		opts, args = getopt.getopt(sys.argv[1:], "m", ["mpeg"])
	except getopt.GetoptError:
		Show_Usage()
		sys.exit(-1)
	
	global ExtractMPEG
	ExtractMPEG = 0
	for opt, arg in opts:
		if opt in ('-m', '--mpeg'):
			if os.path.isfile(VCDGEAR_COMMAND) and os.access(VCDGEAR_COMMAND, os.X_OK):
				ExtractMPEG = 1
			else:
				Error('--mpeg specified, but cannot find your vcdgear binary!')
	
	# Make sure our rar binary is around
	if RAR_COMMAND is None:
		Error("couldn't find your rar/unrar binary!")
	
	if len(args) < 1:
		print 'USAGE: %s [--mpeg] <dir1> [dir2] ... [dirN]' % sys.argv[0]
		sys.exit(-1)
	
	# Scan each directory on our command line
	for release_dir in args:
		# Strip off a trailing slash/whatever
		if release_dir.endswith(os.sep):
			release_dir = release_dir[:-len(os.sep)]
		
		# Get the name of the release dir
		release_name = os.path.split(release_dir)[1]
		
		print '* Scanning directory: %s' % release_dir
		
		if not os.path.isdir(release_dir):
			Error('directory does not exist, or is not a directory!')
		
		if os.getcwd() == release_dir:
			Error('do not run this in the release directory!')
		
		files = os.listdir(release_dir)
		files.sort()
		
		cds = []
		for f in files:
			if f.lower().startswith('cd') or f.lower().startswith('disc'):
				cds.append(f)
			
			elif f.lower().endswith('nfo'):
				print "=> Copying NFO file '%s'" % f
				filename = os.path.join(release_dir, f)
				shutil.copy(filename, f)
		
		# If we have CDs, check each one
		if cds:
			if len(cds) == 1:
				Error('only found 1 CD directory, incomplete release?')
			
			print "=> Found %d CDs, scanning" % len(cds)
			for i in range(len(cds)):
				cd = cds[i]
				cd_path = os.path.join(release_dir, cd)
				RAR_Check(release_name, cd_path, i+1)
		
		else:
			RAR_Check(release_name, release_dir)

# ---------------------------------------------------------------------------
# Scan a directory, looking for some RARs. Try to work out which filename
# format it's using.
def RAR_Check(release_name, path, cd=0):
	if cd:
		print '==> CD %d:' % (cd)
		pre = '===>'
	else:
		pre = '==>'
	
	files = os.listdir(path)
	
	# Find the RAR files
	rars = [f for f in files if RAR_RE.search(f)]
	if rars == []:
		Error('unable to find any RAR volumes')
	
	# Work out how many RARs we have and their total size
	numrars = len(rars)
	size = 0
	for rar in rars:
		file_path = os.path.join(path, rar)
		size += os.path.getsize(file_path)
	
	print '%s Found %d archives (%.1fMB)' % (pre, numrars, size / 1024.0 / 1024.0)
	
	# Do some popen hackery. popen4 gives us a combined stdout+stderr
	first_path = os.path.join(path, rars[0])
	command = '%s x -idp -o+ "%s"' % (RAR_COMMAND, first_path)
	
	blah, proc = os.popen4(command, 't')
	if blah:
		blah.close()
	
	print '\r%s Unpacking, please wait : 00/%02d' % (pre, numrars),
	sys.stdout.flush()
	
	# Loop over the output from rar!
	curr = 0
	extracted = []
	start = time.time()
	while 1:
		line = proc.readline()
		if not line:
			break
		
		line = line.strip()
		
		if line.startswith('Extracting from'):
			curr += 1
			print '\r%s Unpacking, please wait : %02d/%02d' % (pre, curr, numrars),
			sys.stdout.flush()
		
		elif line.startswith('Cannot find volume'):
			filename = os.path.basename(line[19:])
			Error("'%s' is missing!", filename)
		
		elif line.endswith('CRC failed'):
			Error('CRC failure!')
		
		elif line.startswith('Write error'):
			for filename in extracted:
				os.remove(filename)
			Error('Write error, disk full?!')
		
		else:
			m = re.match(r'^(Extracting|...)\s+(.*?)\s+OK\s*$', line)
			if m:
				extracted.append(m.group(2))
	
	
	# Work out how long it took
	blah = time.time() - start
	hours, blah = divmod(blah, 60*60)
	mins, secs = divmod(blah, 60)
	
	if hours:
		elapsed = '%d:%02d:%02d' % (hours, mins, secs)
	else:
		elapsed = '%d:%02d' % (mins, secs)
	
	print '\r%s Unpacked %d file(s) in %s     ' % (pre, len(extracted), elapsed)
	
	
	# Extract MPEGs if we really have to
	if ExtractMPEG:
		print '%s Extracting MPEG(s)...' % pre
		
		cues = [f for f in extracted if f.lower().endswith('.cue')]
		cues.sort()
		for cue in cues:
			# Construct the filename!
			if cd:
				mpegname = '%s.CD%d.mpg' % (release_name, cd)
			else:
				mpegname = '%s.mpg' % release_dir
			
			# Extract the MPEG
			cmdline = '%s -cue2mpg %s %s' % (VCDGEAR_COMMAND, cue, mpegname)
			os.system(cmdline)
			
			# If the MPEG doesn't exist, try again with track02
			if not os.path.exists(mpegname):
				cmdline = '%s -cue2mpg -track02 %s %s' % (VCDGEAR_COMMAND, cue, mpegname)
				os.system(cmdline)
			
			
			# If the MPEG exists and is larger than 0 bytes, delete the bin/cue
			if os.path.exists(mpegname) and os.path.getsize(mpegname):
				os.remove(cue)
				binname = '%s.bin' % cue[:-4]
				try:
					os.remove(binname)
				except OSError:
					pass
	
	# Otherwise, we'll just clean up the files a bit. chmod/touch don't work
	# for Windows!
	elif os.name != 'nt':
		for filename in extracted:
			os.chmod(filename, 0644)
			cmdline = 'touch "%s"' % filename
			os.system(cmdline)

# ---------------------------------------------------------------------------
# Sort the various RAR filename formats properly :\
def rar_sort(a, b):
	aext = a.split('.')[-1].lower()
	bext = b.split('.')[-1].lower()
	
	if aext == 'rar' and bext == 'rar':
		return cmp(a, b)
	elif aext == 'rar':
		return -1
	elif bext == 'rar':
		return 1
	else:
		return cmp(a, b)

# ---------------------------------------------------------------------------

if __name__ == '__main__':
	main()
