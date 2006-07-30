from Hellanzb.Filters import Filter, getFileExtension
from Hellanzb.PostProcessorUtil import Topen

def isRar(filename):
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

class RarFilter(Filter):
	def __init__(self):
		pass

	def groupAlikes(self, files):
		# Make a list of main_rars, we only deal with the first one
		# in the list, and then we return this so it can be removed
		# from the file list and then the new file list can be iterated
		# by the filter handler.
		mainRars = []
		for a in files:
			if a.endswith('.rar'):
				mainRars.append(a)

		# Now we determine the rar group name, and then we get a list of
		# files that match the two common patterns with that rar group name.
		theRar=mainRars[0]
		_splitRar = theRar.split('.')
		groupName = '.'.join(_splitRar[:len(_splitRar)-1])
		groupMembers = [ a for a in files if re.search(groupName+'\.r([0-9]{1,4})', b) or re.search(groupName+'\.part([0-9]{1,4})', a) ]

		return groupMembers

	def canHandle(self, fileName):
        if isRar(fileName):
            return True
        else:
            return False

	def processFile(self, files):
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

