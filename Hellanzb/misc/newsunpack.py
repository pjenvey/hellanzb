#!/usr/bin/python

"""
Unpacks a set of PAR/PAR2 + RAR files, commonly used for posting binaries
on usenet. You'll need par2cmdline and rar/unrar :)
"""

import getopt
import os
import re
import sys
import time

# ---------------------------------------------------------------------------

__version__ = '0.9'

# ---------------------------------------------------------------------------
# Some regexps, fun
PAR_RE = re.compile(r'\.(?P<ext>par|p\d\d|par2)$', re.I)
RAR_RE = re.compile(r'\.(?P<ext>rar|r\d\d|\d\d\d)$', re.I)

LOADING_RE = re.compile(r'^Loading "(.+)"')
TARGET_RE = re.compile(r'^(?:File|Target): "(.+)" -')

# ---------------------------------------------------------------------------
# Find par2cmdline and rar/unrar
PAR2_COMMAND = None
RAR_COMMAND = None

# Windows uses semicolon, how rude
if os.name == 'nt':
	lookhere = os.getenv('PATH').split(';')
	findpar2 = ('par2.exe',)
	findrar = ('rar.exe', 'unrar.exe')
else:
	lookhere = os.getenv('PATH').split(':')
	findpar2 = ('par2',)
	findrar = ('rar', 'unrar', 'rar3', 'unrar3')

for path in lookhere:
	if not PAR2_COMMAND:
		for par2 in findpar2:
			par2_path = os.path.join(path, par2)
			if os.access(par2_path, os.X_OK):
				PAR2_COMMAND = par2_path
				break
	
	if not RAR_COMMAND:
		for rar in findrar:
			rar_path = os.path.join(path, rar)
			if os.access(rar_path, os.X_OK):
				RAR_COMMAND = rar_path
				break

# ---------------------------------------------------------------------------

def Show_Usage():
	head, tail = os.path.split(sys.argv[0])
	print """
Usage: %s [options] <par1> [par2] ... [parN]

  -d     : Delete PAR/PAR2/RAR files after successful extraction.
  -n     : Use 'nice' on all commands.
  -pPASS : Use PASS to unpack the RARs.
  -v     : Be verbose (prints extracted filenames)

  You can set the environment variable NEWSUNPACK to whatever
  string of options you normally like to use.
""" % tail
	sys.exit(1)

def Error(fatal, text, *args):
	if args:
		text = text % args
	print 'ERROR:', text
	if fatal:
		sys.exit(-1)

def main():
	print "newsunpack.py v%s by Freddie (freddie@madcowdisease.org)" % __version__
	
	if len(sys.argv) < 2:
		Show_Usage()
	
	if RAR_COMMAND is None:
		Error(1, "Unable to find RAR/UnRAR binary!")
	elif PAR2_COMMAND is None:
		Error(1, "Unabled to find par2cmdline binary!")
	
	# Parse our command line
	parseme = sys.argv[1:]
	envopts = os.getenv('NEWSUNPACK')
	if envopts and not parseme:
		parseme = envopts
		parseme.insert(0, envopts)
	
	try:
		opts, args = getopt.getopt(parseme, 'dnp:v')
	except getopt.GetoptError:
		Show_Usage()
	
	global DELETE, NICE, PASSWORD, VERBOSE
	DELETE = NICE = VERBOSE = 0
	PASSWORD = None
	
	for opt, arg in opts:
		if opt == '-d':
			DELETE = 1
		elif opt == '-n':
			NICE = 1
		elif opt == '-p':
			PASSWORD = arg
		elif opt == '-v':
			VERBOSE = 1
	
	# No 'nice' on Windows
	if NICE and os.name == 'nt':
		print "! -n won't work on Windows, disabling"
		NICE = 0
	
	# Scan each parity file on our command line
	for parfile in args:
		print
		
		# Sanity checks
		if not os.path.isfile(parfile) or not PAR_RE.search(parfile):
			# Look for PAR/PAR2 files
			head, tail = os.path.split(parfile)
			
			for char in ('[]().'):
				tail = tail.replace(char, '\\' + char)
			
			regexp = '^%s\.?(par|par2|vol\d+\+\d+\.par2)$' % tail
			r = re.compile(regexp, re.I)
			
			# If we can't list the dir, bail
			try:
				files = os.listdir(head)
				files.sort()
			except OSError:
				Error(0, '"%s" does not exist, or is not a PAR/PAR2 file!', parfile)
				continue
			
			matches = [f for f in files if r.match(f)]
			if not matches:
				Error(0, '"%s" does not exist, or is not a PAR/PAR2 file!', parfile)
				continue
			
			parfile = os.path.join(head, matches[0])
		
		print '> Scanning "%s"' % parfile
		
		# Split into dir, filebase
		head, tail = os.path.split(parfile)
		
		# Extracting from the current dir, use '.'
		if head == '':
			head = '.'
		
		# Run the PAR verifier
		result, pars, datafiles = PAR_Verify(parfile)
		if not result:
			continue
		
		# Get a list of RARs
		rars = [f for f in datafiles if RAR_RE.search(f)]
		rars.sort(rar_sort)
		
		# No RARs? Oh well.
		if len(rars) == 0:
			print "=> No RARs to extract."
			continue
		
		# Run the RAR extractor
		rarpath = os.path.join(head, rars[0])
		newfiles = RAR_Extract(rarpath, len(rars))
		
		# If we didn't manage to extract any files, we have nothing more to do
		if newfiles == []:
			continue
		
		for newfile in newfiles:
			# Clean up the files a bit. touch doesn't exist on Windows, and chmod
			# probably doesn't mean anything.
			if os.name != 'nt':
				os.chmod(newfile, 0644)
				cmdline = 'touch "%s"' % newfile
				os.system(cmdline)
			
			# Spit out what files we unpacked if we have to
			if VERBOSE:
				print '==> %s (%s)' % (newfile, NiceSize(os.path.getsize(newfile)))
		
		# Delete the old files if we have to
		if DELETE:
			i = 0
			
			for filename in pars:
				filepath = os.path.join(head, filename)
				os.remove(filepath)
				i += 1
			
			for filename in rars:
				filepath = os.path.join(head, filename)
				os.remove(filepath)
				i += 1
				brokenpath = '%s.1' % (filepath)
				if os.path.exists(brokenpath):
					os.remove(brokenpath)
					i += 1
			
			print "=> Deleted %d file(s)" % i

# ---------------------------------------------------------------------------
# Run par2cmdline and parse what it spits out
def PAR_Verify(parfile):
	start = time.time()
	
	# We need a combined stdout/stderr
	command = '%s r "%s"' % (PAR2_COMMAND, parfile)
	if NICE:
		command = 'nice %s' % (command)
	
	blah, proc = os.popen4(command, 't')
	if blah:
		blah.close()
	
	# Set up our variables
	pars = []
	datafiles = []
	
	linebuf = ''
	finished = 0
	
	verifynum = 1
	verifytotal = 0
	verified = 0
	
	# Loop over the output, whee
	while 1:
		char = proc.read(1)
		if not char:
			break
		
		# Line not complete yet
		if char not in ('\n', '\r'):
			linebuf += char
			continue
		
		line = linebuf.strip()
		linebuf = ''
		
		# Skip empty lines
		if line == '':
			continue
		
		# And off we go
		if line.startswith('All files are correct'):
			print '\r=> Verified in %.1fs, all files correct' % (time.time() - start)
			sys.stdout.flush()
			finished = 1
		
		elif line.startswith('Repair is required'):
			print '\r=> Verified in %.1fs, repair is required' % (time.time() - start)
			sys.stdout.flush()
			start = time.time()
			verified = 1
		
		elif line.startswith('You need'):
			chunks = line.split()
			print '=> Unable to repair, you need %s more recovery %s' % (chunks[2], chunks[5])
		
		elif line.startswith('Repair is possible'):
			start = time.time()
			print '\r=> Repairing : %2d%%' % (0),
			sys.stdout.flush()
		
		elif line.startswith('Repairing:'):
			chunks = line.split()
			per = float(chunks[-1][:-1])
			print '\r=> Repairing : %2d%%' % (per),
			sys.stdout.flush()
		
		elif line.startswith('Repair complete'):
			print '\r=> Repaired in %.1fs' % (time.time() - start)
			finished = 1
		
		# This has to go here, zorg
		elif not verified:
			if line.startswith('Verifying source files'):
				print '\r=> Verifying : 01/%02d' % (verifytotal),
				sys.stdout.flush()
			
			elif line.startswith('Scanning:'):
				pass
			
			else:
				# Loading parity files
				m = LOADING_RE.match(line)
				if m:
					pars.append(m.group(1))
					continue
				
				# Target files
				m = TARGET_RE.match(line)
				if m:
					if verifytotal == 0 or verifynum < verifytotal:
						verifynum += 1
						print '\r=> Verifying : %02d/%02d' % (verifynum, verifytotal),
						sys.stdout.flush()
					datafiles.append(m.group(1))
					continue
				
				# Verify done
				m = re.match(r'There are (\d+) recoverable files', line)
				if m:
					verifytotal = int(m.group(1))
	
	return (finished, pars, datafiles)

def RAR_Extract(rarfile, numrars):
	start = time.time()
	
	# We need a combined stdout/stderr
	if PASSWORD:
		command = '%s x -idp -o+ -p"%s" "%s"' % (RAR_COMMAND, PASSWORD, rarfile)
	else:
		command = '%s x -idp -o+ -p- "%s"' % (RAR_COMMAND, rarfile)
	if NICE:
		command = 'nice %s' % (command)
	
	blah, proc = os.popen4(command, 't')
	if blah:
		blah.close()
	
	print '\r=> Unpacking : 00/%02d' % (numrars),
	sys.stdout.flush()
	
	# Loop over the output from rar!
	curr = 0
	extracted = []
	fail = 0
	while 1:
		line = proc.readline()
		if not line:
			break
		
		line = line.strip()
		#print '>', line
		
		if line.startswith('Extracting from'):
			curr += 1
			print '\r=> Unpacking : %02d/%02d' % (curr, numrars),
			sys.stdout.flush()
		
		elif line.startswith('Cannot find volume'):
			filename = os.path.basename(line[19:])
			print '\r=> ERROR: unable to find "%s"' % filename
			fail = 1
		
		elif line.endswith('- CRC failed'):
			filename = line[:-12].strip()
			print '\r=> ERROR: CRC failed in "%s"' % filename
			fail = 1
		
		elif line.startswith('Write error'):
			print '\r=> ERROR: write error, disk full?'
			fail = 1
		
		elif line.startswith('ERROR: '):
			print '\r=> ERROR: %s' % (line[7:])
			fail = 1
		
		elif line.startswith('Encrypted file:  CRC failed'):
			filename = line[31:-23].strip()
			print '\r=> ERROR: CRC failed in "%s" - password incorrect?' % filename
			fail = 1
		
		else:
			m = re.search(r'^(Extracting|...)\s+(.*?)\s+OK\s*$', line)
			if m:
				extracted.append(m.group(2))
		
		if fail:
			if proc:
				proc.close()
			for filename in extracted:
				os.remove(filename)
			return []
	
	if proc:
		proc.close()
	
	print '\r=> Unpacked %d file(s) in %.1fs' % (len(extracted), time.time() - start)
	
	return extracted

# ---------------------------------------------------------------------------
# Sort the various RAR filename formats properly :\
def rar_sort(a, b):
	aext = a.split('.')[-1]
	bext = b.split('.')[-1]
	
	if aext == 'rar' and bext == 'rar':
		return cmp(a, b)
	elif aext == 'rar':
		return -1
	elif bext == 'rar':
		return 1
	else:
		return cmp(a, b)

# Sort the various PAR filename formats properly :\
def par_sort(a, b):
	aext = a.split('.')[-1]
	bext = b.split('.')[-1]
	
	if aext == bext:
		return cmp(a, b)
	elif aext == 'par2':
		return -1
	elif bext == 'par2':
		return 1
	elif aext == 'par':
		return -1
	elif bext == 'par':
		return 1
	else:
		return cmp(a, b)

# Format a byte count nicely
def NiceSize(bytes):
	bytes = float(bytes)
	
	if bytes < 1024:
		return '<1KB'
	elif bytes < (1024 * 1024):
		return '%dKB' % (bytes / 1024)
	elif bytes < (1024 * 1024 * 1024):
		return '%.1fMB' % (bytes / 1024.0 / 1024.0)
	else:
		return '%.1fGB' % (bytes / 1024.0 / 1024.0 / 1024.0)

# ---------------------------------------------------------------------------

if __name__ == '__main__':
	main()
