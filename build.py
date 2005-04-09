#!/usr/bin/env python
"""

build.py - Strip the trunk connotation from the version number, bump the number, branch,
build a distribution, and finally check in the version number bump change.

Can do local builds with -lt

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import optparse, os, re, setup, sys
from build_util import *
from Hellanzb.Util import assertIsExe, stringEndsWith

__id__ = '$Id$'

UPLOAD_HOST = 'groovie.org:/usr/local/www/hellanzb.com/distfiles/'
    
try:
    parser = optparse.OptionParser()
    parser.add_option('-l', '--local', action='store_true', dest='local',
                      help='Do a local build (don\'t commit version changes)')
    parser.add_option('-t', '--trunk', action='store_true', dest='trunk',
                      help='Assume this is a trunk build, and do not bump the version number')
    options, args = parser.parse_args()

    if not options.local:
        assertIsExe('svn')

    # If not local, make sure the working copy is up to date with the repository!
    if not options.local:
        assertUpToDate()
        pass
        
    versionFile = open(VERSION_FILENAME)
    versionLine = versionFile.read()
    versionLine = versionLine.rstrip()
    versionFile.close()
    
    assert(versionLine[0:len('version')] == 'version', 'version file is broken!')

    versionLine = re.sub(r'^.*\ \'', r'', versionLine)
    version = re.sub(r'\'', r'', versionLine)
    newVersion = version

    if stringEndsWith(version, '-trunk'):
        if not options.trunk:
            # Bump the version to a stable number
            version = version[0:-len('-trunk'):]
            newVersion = bumpVersion(version)
            writeVersion(newVersion)
            version = newVersion

        # branch if doing a release
        if not options.trunk and not options.local:
            # branch the codebase, and make our working copy that branch
            origRepository = getRepository()
            # NOTE: This will switch our working directory to the new branch
            branchRelease(version)

        # Build
        print 'Building version: ' + version

        # overwrite setup's version to the new, and build the distributions
        setup.version = version
        buildDist()
        buildPort(version)
        buildDPort(version)

        if not options.trunk and not options.local:
            print 'Switching back to trunk'
            os.system('svn switch ' + origRepository)

        if not options.trunk:
            # Append -trunk back to the number
            newVersion = version + '-trunk'
            writeVersion(newVersion)

        # Check in changes to trunk
        if not options.local and not options.trunk:
            print 'Checking in new version number: ' + newVersion
            os.system('svn ci -m "New build, version: ' + version + '" ' + VERSION_FILENAME)
            
            print 'Deploying new build to host: ' + UPLOAD_HOST
            uploadToHost(version, UPLOAD_HOST)

    else:
        print 'Error: Version number: ' + version + ' is not the trunk!'
        sys.exit(1)
    
except IndexError:
    sys.exit(1)

"""
/*
 * Copyright (c) 2005 Philip Jenvey <pjenvey@groovie.org>
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 * 3. The name of the author or contributors may not be used to endorse or
 *    promote products derived from this software without specific prior
 *    written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
 * FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 * DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
 * OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
 * HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 * LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
 * OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
 * SUCH DAMAGE.
 *
 * $Id$
 */
"""
