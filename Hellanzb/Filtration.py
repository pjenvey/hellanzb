"""

Filtration - dispatch downloaded files to the various Filters to be 
             post-processed

(c) Copyright 2006 Alexander Botero-Lowry
[See end of file]
"""
import gc, os, re, sys, time, Hellanzb
from os.path import join as pathjoin
from shutil import move, rmtree
from threading import Thread, Condition, Lock, RLock
from Hellanzb.Log import *
from Hellanzb.Logging import prettyException
from Hellanzb.Util import *
from Filters import *

__id__ = '$Id$'

class FiltrationMaster:
    """ Organize and dispatch the various post processing filters """
    def __init__(self, processDir):
        self.processDir = processDir
        self._handles = {}

        # We should basically take a last of the files, and then try
        # to group them to the correct filters.
        files = os.listdir(processDir)

        # If we're going to do file operations on these things, we should
        # hand off the absolute paths to the files
        files = [ pathjoin(self.processDir, a) for a in files ]

        for a in ourFilters:
            self._handles[a] = []
            self._handles[a] = [ b for b in files if ourFilters[a].canHandle(b) ]
            # TODO: Pop files off the files list once they've been marked as
            # handlable

        # Now that files are split into their correct filters, we should get
        # some file groups and pass them off to the processors.

        for a in self._handles:
            groupedFiles = ourFilters[a].groupAlikes(self._handles[a])
            print groupedFiles

fil = FiltrationMaster('/usr/home/alex/news/usenet/stargatesg-11003wsdsr-dimension/processed')

