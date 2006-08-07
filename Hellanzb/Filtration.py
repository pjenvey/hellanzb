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

        for a in ourFilters:
            self._handles[a] = []
            self._handles[a] = [ b for b in files if ourFilters[a].canHandle(pathjoin(self.processDir, b)) ]
        print self._handles

fil = FiltrationMaster('/usr/home/alex/news/usenet/stargatesg-11003wsdsr-dimension/processed')

