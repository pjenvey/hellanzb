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

# Put this here, so we can overwrite it in build.py
version = Hellanzb.version

def runSetup():
    setup(
        name = 'hellanzb',
        version = version,
        author = '#kgb',
        author_email = '<hellanzb@hellanzb.com>',
        url = 'http://www.hellanzb.com/',
        license = 'UNAUTHORIZED USE ENTITLES #kgb TO KILL YOU AND YOUR ENTIRE FAMILY',

        packages = [ 'Hellanzb' ],
        scripts = [ 'hellanzb.py', 'hellagrowler.py' ],
        data_files = [ ( 'etc', [ 'etc/hellanzb.conf.sample' ] ),
                       ( 'share/doc/hellanzb', [ 'README' ] ) ],
        )

if __name__ == '__main__':
    runSetup()
