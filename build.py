#!/usr/bin/env python
"""

build.py - Strip the trunk connotation from the version number, bump the number, branch,
build a distribution, and finally check in the version number bump change.

Can do local builds with -lt

@author pjenvey

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
        # FIXME
        #assertUpToDate()
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

            # if not local, branch here.
            if not options.local:
                # branch the codebase, and make our working copy that branch
                origRepository = getRepository()
                branchRelease(version)
                #origDir = os.getcwd()
                #os.chdir('build/hellanzb-' + version)
                #print 'Switching to new branch: ' + version
            #os.system('svn switch "New build, version: ' + version + '" ' + VERSION_FILENAME)

        # Build
        print 'Building version: ' + version

        #if not options.local or not options.trunk:
        #    # branch the codebase, and make our working copy that branch
        #    branchRelease(version)

        # overwrite setup's version to the new, and build the distributions
        setup.version = version
        buildDist()
        buildPort(version)
        buildDPort(version)

        if not options.trunk and not options.local:
            #os.chdir(origDir)
            print 'Switching back to trunk'
            os.system('svn switch ' + origRepository)

        if not options.trunk:
            # Append -trunk back to the number and check in bump
            newVersion = version + '-trunk'
            writeVersion(newVersion)
                
        if not options.local:
            print 'Checking in new version number: ' + newVersion
            print "WOOP!"
            #os.system('svn ci -m "New build, version: ' + version + '" ' + VERSION_FILENAME)
            
            print 'Deploying new build to host: ' + UPLOAD_HOST
            #uploadToHost(version, UPLOAD_HOST)

    else:
        print 'Error: Version number: ' + version + ' is not the trunk!'
        sys.exit(1)
    
except IndexError:
    sys.exit(1)
