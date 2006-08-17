from Filters import Filter, getFileExtension
from Hellanzb.PostProcessorUtil import Topen
import os, os.path, re

def isPar(filename):
	if isPar2(filename) or isPar1(filename):
		return True

def isPar2(filename):
    _PAR2_HEADER_PACKET = 'PAR2\x00PKT'
    if not os.path.isfile(filename):
        return False
    f = file(filename)
    if f.read(8) == _PAR2_HEADER_PACKET:
        f.close()
        return True

def isPar1(filename):
    _PAR1_HEADER_PACKET = 'PAR\x00\x00\x00\x00\x00'
    if not os.path.isfile(filename):
        return False
    f = file(filename)
    if f.read(8) == _PAR1_HEADER_PACKET:
        f.close()
        return True

class ParFilter(Filter):
    def __init__(self):
        self.name = 'par'

    def groupAlikes(self, files):
        """ Returns the first Par group the filter is able to act on """
        mainPars = [ a for a in files if a.lower().endswith('.par2') or a.lower().endswith('.par') ]
        thePar = mainPars[0]
        _splitPar = thePar.split('.')
        groupName = '.'.join(_splitPar[:len(_splitPar)-1])
        groupMembers = [ a for a in files if re.search(groupName, a) ]
        groupMembers.remove(thePar)
        groupMembers.insert(0, thePar)
        return groupMembers

    def canHandle(self, files):
        return [ a for a in files if isPar(a) ]

    def processFiles(self, nzbObject, files):
        pass

