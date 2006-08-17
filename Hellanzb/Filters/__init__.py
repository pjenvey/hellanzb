import Hellanzb
import os, string

class FilterError(Exception):
    """
        This is thrown when a filter can temporarily not handle a group, but
        would like to try again later (e.g. needs assembly first)
    """
    pass

class UnhandleableError(Exception:
    """
        This is raised when a filters process method can not handle a group
        it thought it could handle before. The group should not be passed
        back to it.
    """
    pass

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

from rar import isRar, RarFilter
from par import isPar, ParFilter
ourFilters = {}
ourFilters['rar'] = RarFilter()
ourFilters['par'] = ParFilter()
