#!/usr/bin/env python

# 
# hellanzb
#
# $Id$

import sys
assert sys.version >= '2', "Install Python 2.0 or greater" # don't know of this is
                                                           # necessary
from distutils.core import setup, Extension
import Hellanzb

def runSetup():
    setup(
        name = "hellanzb",
        version = Hellanzb.version,
        author = "#kgb",
        author_email = "<hellanzb@groovie.org>",
        url = "http://2eleet.for.u/",
        license = "UNAUTHORIZED USE ENTITLES #kgb TO KILL YOU AND YOUR ENTIRE FAMILY",

        packages = ["Hellanzb"],
        scripts = [ "hellanzb" ],
        )

if __name__ == '__main__':
    runSetup()
