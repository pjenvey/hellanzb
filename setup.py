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

__id__ = '$Id$'

# Put this here, so we can overwrite it in build.py
version = Hellanzb.version

def runSetup():
    setup(
        name = 'hellanzb',
        version = version,
        author = 'Philip Jenvey',
        author_email = '<pjenvey@groovie.org>',
        url = 'http://www.hellanzb.com',
        license = 'BSD',

        packages = [ 'Hellanzb', 'Hellanzb.Newsleecher', 'Hellanzb.NewzSlurp' ],
        scripts = [ 'hellanzb.py', 'hellagrowler.py' ],
        data_files = [ ( 'etc', [ 'etc/hellanzb.conf.sample' ] ),
                       ( 'share/doc/hellanzb', [ 'README', 'LICENSE' ] ) ],
        )

if __name__ == '__main__':
    runSetup()
