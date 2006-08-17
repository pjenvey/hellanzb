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
    def __init__(self, nzb, processDir):
        self.processDir = processDir

        # We cycle through our filters, passing them a new list of files
        # until there is nothing left to process that hasn't caused problems
        while processableFilesPresent:
            for a in ourFilters:
                files = os.listdir(processDir)
                files = [ pathjoin(self.processDir, a) for a in files ]
                try:
                    a.processFiles(files)
                except UnhandleableError, unmentionables:
                    for b in unmentionables:
                        files.remove(b)

fil = FiltrationMaster('/usr/home/alex/news/usenet/stargatesg-11003wsdsr-dimension/processed')

