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

if __name__ == '__main__':
    runSetup()
