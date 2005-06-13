#!/usr/bin/env python

import os, re

files = os.listdir('.')
files.sort()

for file in files:
	m = re.match('^(.*)\.(doc|htm|html|lit|pdf|rtf|txt)$', file)
	if not m:
		continue
	
	desc, ext = m.groups()
	
	
	# Put brackets around the series name
	desc = re.sub(r'- ([^\(\)-]+ \d+) -', r'- (\1) -', desc)
	
	# Replace old [] brackets with ()
	desc = re.sub(r'- \[([^-]+)\] -', r'- (\1) -', desc)
	
	# Pad the series number to 2 digits
	desc = re.sub(r'- (\([^\(\)-]+) (\d)\) -', r'- \1 0\2) -', desc)
	
	
	if ext == 'htm':
		ext = 'html'
	
	
	os.chmod(file, 0644)
	
	newname = '%s.%s' % (desc, ext)
	os.rename(file, newname)
	
	rar = 'rar3 m -m5 -md4096 "%s [%s].rar" "%s"' % (desc, ext.upper(), newname)
	os.system(rar)
