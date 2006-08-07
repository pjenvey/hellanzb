from Filters import Filter, getFileExtension
from Hellanzb.PostProcessorUtil import Topen
import os, os.path

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
        self.name = 'rar' 

    def groupAlikes(self, files):
        """ Returns the a Rar group the filter is able to act on """
        # Make a list of main_rars, we only deal with the first one
        # in the list, and then we return this so it can be removed
        # from the file list and then the new file list can be iterated
        # by the filter handler.
        mainRars = [ a for a in files if a.endswith('.rar') ]

        # Now we determine the rar group name, and then we get a list of
        # files that match the groupName and are rars.
        theRar=mainRars[0]
        _splitRar = theRar.split('.')
        groupName = '.'.join(_splitRar[:len(_splitRar)-1])
        groupMembers = [ a for a in files if re.search(groupName, a) and isRar(a) ] 

        return groupMembers

    def canHandle(self, theFile):
        return isRar(theFile)

    def processFile(self, nzbObject, files):
        """ Process a file """
        # First file should be the .rar, so we'll check the encryption
        # state on the main rar file.
        _fileName = files[0]
        f = file(_fileName)
        buf = f.read(22)
        # If the header of a rar is encrypted, the binary AND of the 
        # 10th and 11th byte AND 0x80 will be non-zero. This is the
        # encrypted header flag.
        if ( ord(b[10])+ ord(b[11]) ) & 0x80 != 0:
            rarEncrypted=True

        # Determine if the next block is a Comment and if it is
        # determine its size and seek past it. 
        buf = f.read(9)
        if hex(ord(b[0])) == '0x7a':
            head_size = ord(b[3]) + ord(b[4])
            data_size = ord(b[5]) + ord(b[6]) + ord(b[7]) + ord(b[8])
            seek_forward = (data_size+head_size)-9
            buf = f.seek(seek_forward, 1)
            buf = f.read(10)
        # Now check the first file header. If the HEAD_FLAG for the file 
        # header has a non-zero binary AND with 0x04, it is encrypted. 
        if ord(b[1]) & 0x04:
            rarEncrypted=True

        # TODO: handle other files in the Rarchive
        # TODO: methodize the header seek code.
