#!/usr/bin/python2.3

"Fix BIN/CUE file names"

import glob
import os
import re
import sys

# ---------------------------------------------------------------------------

NFO = {
	'flt-': 'FAiRLiGHT',
	'deviance': 'DEViANCE',
	'ims-': 'iMMERSiON',
	'gru': 'gimpsRus',
	'dino': 'DiNoBYTeS',
	'rzr-': 'Razor1911',
	'fas-': 'FASiSO',
	'rld-': 'RELOADED',
	'vengeance': 'VENGEANCE',
	'ven-': 'VENGEANCE',
	'vng-': 'VENGEANCE',
	'mo-': 'MONEY',
	'egc-': 'ELEGANCE',
	'phx-': 'PHXiSO',
	'myth': 'MYTH',
	'ccd-': 'CLONECD',
	'pcg-': 'CLONEGAME',
}

# ---------------------------------------------------------------------------

def ShowUsage():
	print "fixbins.py <newname> <files>"
	print
	sys.exit(1)

# ---------------------------------------------------------------------------

def main():
	if len(sys.argv) < 3:
		ShowUsage()
	
	newbase = sys.argv[1]
	if newbase.endswith('.'):
		newbase = newbase[:-1]
	
	roots = {}
	nfos = []
	
	# Expand any wildcards
	files = []
	for arg in sys.argv[2:]:
		globbed = glob.glob(arg)
		files.extend(globbed)
	
	for filename in files:
		root, ext = os.path.splitext(filename)
		if ext.lower() in ('.bin', '.cue', '.ccd', '.img', '.sub', '.iso'):
			roots.setdefault(root, []).append([filename, ext.lower()])
		elif ext.lower() == '.nfo':
			nfos.append(filename)
	
	roots = roots.items()
	roots.sort()
	
	if len(roots) == 1:
		cd = None
	else:
		cd = 0
	
	for root, files in roots:
		files.sort(cue_sort)
		
		if cd is not None:
			cd += 1
			rootbase = '%s.CD%s' % (newbase, cd)
		else:
			rootbase = newbase
		
		oldimage = None
		newimage = None
		for filename, ext in files:
			newname = '%s%s' % (rootbase, ext)
			
			if ext in ('.bin', '.img'):
				oldimage = filename
				newimage = newname
			
			# rewrite the cue!
			if ext == '.cue':
				if oldimage is None:
					print '%s -> No CD image found!' % (filename)
					break
				
				if filename != newname:
					lines = open(filename, 'r').readlines()
					
					newfile = open(newname, 'wb')
					for line in lines:
						line = line.rstrip()
						if line.startswith('FILE'):
							line = re.sub(r'".*?"', '"%s"' % newimage, line)
						newfile.write(line)
						newfile.write('\r\n')
					newfile.close()
					
					# Keep our mtime, please
					mtime = os.stat(filename).st_mtime
					os.utime(newname, (mtime, mtime))
					
					os.remove(filename)
			
			else:
				os.rename(filename, newname)
			
			print '%s -> %s' % (filename, newname)
		
	# Check NFOs too?
	for filename in nfos:
		for sw, group in NFO.items():
			if filename.startswith(sw):
				newname = '%s-%s.nfo' % (newbase, group)
				os.rename(filename, newname)
				
				print '%s -> %s' % (filename, newname)
				
				break

# ---------------------------------------------------------------------------
# Sort cues last
def cue_sort(a, b):
	aext = a[1]
	bext = b[1]
	
	if aext == '.cue' and bext == '.cue':
		return cmp(a, b)
	elif aext == '.cue':
		return 1
	elif bext == '.cue':
		return -1
	else:
		return cmp(a, b)

# ---------------------------------------------------------------------------

if __name__ == '__main__':
	main()
