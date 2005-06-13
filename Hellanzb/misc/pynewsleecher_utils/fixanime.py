#!/usr/bin/env python

"""
Fix messy anime filenames. I hate files being named all weirdly, so I hacked
this up to fix them for me. Output looks sort of like this:
 
[Inf-AonE]_Onegai_Twins_02_[A387A082].avi --> Onegai Twins/Onegai Twins - 02.avi
[Live-eviL] Rumic Theater - Ep 01 (xvid).avi --> Rumic Theater - 01.avi
[a-e]_Tenshi_na_Konamaiki_01.avi --> Tenshi na Konamaiki - 01.avi
[hawks]grappler_baki _-_03[hq].avi --> Grappler Baki/Grappler Baki - 03.avi
"""

__version__ = '0.3'

import os
import re
import sys

# ---------------------------------------------------------------------------

def main():
	if len(sys.argv) <= 1:
		print 'USAGE: fixanime.py <file1> [file2] ... [fileN]'
		sys.exit(-1)
	
	for filename in sys.argv[1:]:
		if not os.path.exists(filename) or not os.path.isfile(filename):
			print 'ERROR: %s does not exist, or is not a file!' % filename
			continue
		
		# See if we can match a CRC32 value
		m = re.search(r'\[([A-Za-z0-9]{8,8})\]', filename)
		if m:
			crc32 = m.group(1).upper()
		else:
			crc32 = None
		
		# Change a bracketed episode (Keep-ANBU sometimes) to normal
		mangled = re.sub(r'\[(\d{1,3})\]', r'\1', filename)
		
		# Remove underscores
		mangled = re.sub(r'_', ' ', mangled)
		# Remove bracketed bits (group names, CRC, etc)
		mangled = re.sub(r'[\[\(\{].*?[\]\)\}]', '', mangled)
		# Remove 'Ep' and 'Episode'
		mangled = re.sub(r'(?i)\b(Episode|Ep)(\d*)\b', r'\2', mangled)
		# Remove channel anmes
		mangled = re.sub(r'\#\S+', '', mangled)
		# Remove versions
		mangled = re.sub(r'v\d+', '', mangled)
		# Remove CRC values on the end of the name
		mangled = re.sub(r'\s+[A-Za-z0-9]{8}\.', '.', mangled)
		
		# Squish two or more spaces into one
		mangled = re.sub(r'\s+', ' ', mangled)
		
		# If we can't match the filename, skip it
		m = re.match(r'^[\s-]*(?P<series>.*?)[\s-]+(?P<episode>\d+)(v\d+|)[\s-]*\.(?P<ext>\S+)$', mangled, re.I)
		if not m:
			print 'NO MATCH: %s --> %s' % (filename, mangled)
			continue
		
		# See if there's a directory that matches the series. If there is, we'll
		# use that name, which should be properly capitalised.
		series = m.group('series')
		for dir in os.listdir(os.getcwd()):
			if os.path.isdir(dir) and dir.lower() == series.lower():
				series = dir
				break
		
		# If the new name is different from the original, rename the file,
		# possibly putting it into a series dir.
		newfilename = '%s - %02d.%s' % (series, int(m.group('episode')), m.group('ext'))
		
		if os.path.exists(series) and os.path.isdir(series):
			newname = os.path.join(series, newfilename)
		else:
			newname = newfilename
		
		if newname != filename:
			print "%s --> %s" % (filename, newname)
			if os.path.exists(newname):
				print '^ File exists! Old file is %d bytes, new file is %d' % (os.path.getsize(newname), os.path.getsize(filename))
			else:
				os.rename(filename, newname)
				
				# Now possibly write the CRC32 value of the new file
				if crc32 and os.path.exists(series) and os.path.isdir(series):
					sfvs = [os.path.join(series, f) for f in os.listdir(series) if f.endswith('.sfv')]
					if sfvs:
						sfv = open(sfvs[0], 'a')
						newline = '%s %s\n' % (newfilename, crc32)
						sfv.write(newline)
						sfv.close()

# ---------------------------------------------------------------------------

if __name__ == '__main__':
	main()
