from Hellanzb.Filters import Filter, getFileExtension
from Hellanzb.PostProcessorUtil import Topen

class RarFilter(Filter):
	def __init__(self):
		pass

	def canHandle(self, filename):
		""" This implements a magic check for Rar files """
		rarHeader = 'Rar!'
		if not os.path.isfile(filename):
			return False

		ext = getFileExtension(filename)
		if ext and ext == 'rar':
			return True

		f = file(filename)
		if f.read(4) == rarHeader:
			f.close()
			return True

	def processFile(self, filename):
		""" Process a file """
		# In a non-encrypted header offset 23=t and offset 24 either ' '
		# if not encypted or '$' if encrypted. If the t isn't there. The
		# header is most likely encypted. An unencrypted header will also 
		# have an R at offset 32. 
		# With encrypted headers the check is obvious, with unencrypted
		# headers, things are a bit more difficult because we can only easily
		# tell if the first file is encrypted not if all of them are. 

		# FIXME: this doesn't actually account for cases where there are 
		# comments in the rar, and thus isn't very useful. 
		f = file(filename)
		buf = f.read(64)
		if buf[22] != 't' and buf[31] != 'R':
			encryptedRar = True

