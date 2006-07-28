class Filter:
    """ Base class for all filters, cannot be used directly """
    def __init__(self):
        pass

    def canHandle(self, file):
        raise NotImplementedError()

    def processFile(self, file):
        raise NotImplementedError()

def getFileExtension(fileName):
    """ Return the extenion of the specified file name, in lowercase """
    if len(fileName) > 1 and fileName.find('.') > -1:
        return string.lower(os.path.splitext(fileName)[1][1:])
