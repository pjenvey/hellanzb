#!/usr/bin/env python
"""
build.py - Strip the HEAD connotation from the version number, bump the number, build a
distribution, and finally check in the version number bump change

@author pjenvey

"""
import os, re, setup, sys
from Hellanzb.Troll import assertIsExe, stringEndsWith

__id__ = '$Id$'

VERSION_FILENAME = './Hellanzb/__init__.py'

def bumpVersion(oldVersion):
    """ Bump the ver number. Is dumb and expects 0.0. Will bump by .1 """
    dot = version.rfind('.')
    prefix = version[0:dot + 1]
    decimal = int(version[dot + 1:])
    decimal = decimal + 1

    return prefix + str(decimal)

def writeVersion(newVersion):
    """ Write out a new version number """
    versionFile = open(VERSION_FILENAME, 'w')
    versionFile.write('version = \'' + newVersion + '\'\n')
    versionFile.close()

def buildDist():
    """ build a binary distribution """
    oldArg = sys.argv

    # Build source and binary distributions
    sys.argv = [ 'setup.py', 'sdist' ]
    setup.runSetup()
    
    sys.argv = [ 'setup.py', 'bdist' ]
    setup.runSetup()
    sys.argv = oldArg

def buildPort(version):
    """ build a FreeBSD port """
    print "Building new FreeBSD port"
    
    portDir = 'dist/hellanzb-port'
    if not os.path.isdir(portDir):
        os.mkdir(portDir)

    # replace the version
    os.system('cat port/Makefile | sed s/____VERSION____/' + version + '/ > ' + portDir + '/Makefile')

    # copy over the pkg-descr file
    input = file('port/pkg-descr')
    lines = input.readlines()
    input.close()
    
    output = file(portDir + '/pkg-descr', 'w')
    output.writelines(lines)
    output.close()
    
try:
    assertIsExe('svn')

    versionFile = open(VERSION_FILENAME)
    versionLine = versionFile.read()
    versionLine = versionLine.rstrip()
    versionFile.close()
    
    assert(versionLine[0:len('version')] == 'version', 'version file is broken!')

    versionLine = re.sub(r'^.*\ \'', r'', versionLine)
    version = re.sub(r'\'', r'', versionLine)

    if stringEndsWith(version, '-HEAD'):
        # Bump the version to a stable number
        version = version[0:-len('-HEAD'):]
        newVersion = bumpVersion(version)
        writeVersion(newVersion)

        # Build
        print 'Building version: ' + newVersion
        setup.version = newVersion
        buildDist()
        buildPort(newVersion)

        # Append -HEAD back to the number and check in bump
        newVersion = newVersion + '-HEAD'
        print 'Checking in new version number: ' + newVersion
        writeVersion(newVersion)
        os.system('svn ci -m "New build, version: ' + newVersion + '" ' + VERSION_FILENAME)

    else:
        print 'Error: Version number: ' + version + ' is not HEAD!'
        sys.exit(1)
    
except IndexError:
    sys.exit(1)
