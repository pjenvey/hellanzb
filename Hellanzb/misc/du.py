#!/usr/bin/env python

import os
import sys


def AddCommas(num):
	s = str(num)
	i = len(s)
	if i <= 3:
		return s
	
	parts = []
	while 1:
		i -= 3
		if i > 0:
			parts.insert(0, s[i:i+3])
		else:
			parts.insert(0, s[0:i+3])
			break
	
	return ','.join(parts)

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


total = 0
for filename in sys.argv[1:]:
	if os.path.exists(filename):
		total += os.path.getsize(filename)
print '%s bytes / %s' % (AddCommas(total), NiceSize(total))
