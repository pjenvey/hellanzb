#!/usr/bin/env python

# 
# hellanzb
#
# $Id$

import sys
from distutils.core import setup, Extension
import Hellanzb
try:
    import py2app
except ImportError:
    py2app = None

__id__ = '$Id$'

# Put this here, so we can overwrite it in build.py
version = Hellanzb.version

def runSetup():
    options = dict(
        name = 'hellanzb',
        version = version,
        author = 'Philip Jenvey',
        author_email = '<pjenvey@groovie.org>',
        url = 'http://www.hellanzb.com',
        license = 'BSD',
        platforms = [ 'unix' ],
        description = 'nzb downloader and post processor',
        long_description = ("hellanzb is an easy to use app designed to retrieve nzb files "
                            "and fully process them. The goal being to make getting files from "
                            "Usenet as hands-free as possible. Once fully installed, all that's "
                            "required is moving an nzb file to the queue directory. The rest: "
                            "downloading, par-checking, un-raring, etc. is done automatically by "
                            "hellanzb."),

        packages = [ 'Hellanzb', 'Hellanzb.NZBLeecher', 'Hellanzb.HellaXMLRPC',
                     'Hellanzb.external', 'Hellanzb.external.elementtree' ],
        scripts = [ 'hellanzb.py' ],
        data_files = [ ( 'etc', [ 'etc/hellanzb.conf.sample' ] ),
                       ( 'share/doc/hellanzb', [ 'CHANGELOG', 'CREDITS', 'README', 'LICENSE' ] ) ],
        )
    py2app_options = dict(
        app = [ 'hellanzb.py' ],
        options = dict(py2app = dict(
                argv_emulation = True,
                # twisted '__import__'s instead of 'import's the syslog module, preventing
                # py2app from detecting its use
                includes = [ 'syslog' ])),
        )
    if py2app:
        options.update(py2app_options)
    setup(**options)

if __name__ == '__main__':
    runSetup()
