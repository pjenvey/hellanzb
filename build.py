#!/usr/bin/env python
"""
build.py - Strip the HEAD connotation from the version number, bump the number, build a
distribution, and finally check in the version number bump change

@author pjenvey

"""
import optparse, os, re, setup, sys, tarfile
from Hellanzb.Util import assertIsExe, stringEndsWith

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
    portStubDir = 'freebsd-port'
    
    portDestDir = 'dist/hellanzb-freebsd-port-' + version
    destDir = portDestDir + os.sep + 'hellanzb'

    if not os.path.isdir(portDestDir):
        os.mkdir(portDestDir)
    if not os.path.isdir(destDir):
        os.mkdir(destDir)

    # replace the version
    os.system('cat ' + portStubDir + os.sep + 'Makefile | sed s/____VERSION____/' + version + '/ > ' +
              destDir + os.sep + 'Makefile')

    # copy over the pkg-descr file
    input = file(portStubDir + os.sep + 'pkg-descr')
    lines = input.readlines()
    input.close()
    
    output = file(destDir + os.sep + 'pkg-descr', 'w')
    output.writelines(lines)
    output.close()

    dir = portDestDir[len('dist/'):]
    createTarBall('dist', dir, dir + '.tar.gz')

def buildDPort(version):
    print "Building new Darwin port"
    portStubDir = 'darwin-dport'
    
    portDestDir = 'dist/hellanzb-darwin-dport-' + version
    destDir = portDestDir + os.sep + 'hellanzb'

    if not os.path.isdir(portDestDir):
        os.mkdir(portDestDir)
    if not os.path.isdir(destDir):
        os.mkdir(destDir)

    # replace the version
    os.system('cat ' + portStubDir + os.sep + 'Portfile | sed s/____VERSION____/' + version + '/ > ' +
              destDir + os.sep + 'Portfile')

    dir = portDestDir[len('dist/'):]
    createTarBall('dist', dir, dir + '.tar.gz')

def createTarBall(workingDir, dirName, fileName):
    """ tar -cxvf """
    cwd = os.getcwd()
    os.chdir(workingDir)
    
    tarBall = tarfile.open(fileName, 'w:gz')
    for file in os.listdir(dirName):
        tarBall.add(dirName + os.sep + file)
    tarBall.close()
        
    os.chdir(cwd)
    
try:
    parser = optparse.OptionParser()
    parser.add_option('-l', '--local', action='store_true', dest='local',
                      help='Do a local build (don\'t commit version changes')
    parser.add_option('-t', '--trunk', action='store_true', dest='head',
                      help='Assume this is a trunk (HEAD) build, and do not bump the version number')
    options, args = parser.parse_args()

    assertIsExe('svn')

    versionFile = open(VERSION_FILENAME)
    versionLine = versionFile.read()
    versionLine = versionLine.rstrip()
    versionFile.close()
    
    assert(versionLine[0:len('version')] == 'version', 'version file is broken!')

    versionLine = re.sub(r'^.*\ \'', r'', versionLine)
    version = re.sub(r'\'', r'', versionLine)

    if stringEndsWith(version, '-HEAD'):
        if not options.head:
            # Bump the version to a stable number
            version = version[0:-len('-HEAD'):]
            newVersion = bumpVersion(version)
            writeVersion(newVersion)
            version = newVersion

        # Build
        print 'Building version: ' + version
        setup.version = version
        buildDist()
        buildPort(version)
        buildDPort(version)

        if not options.head:
            # Append -HEAD back to the number and check in bump
            newVersion = version + '-HEAD'
            writeVersion(version)
        
        if not options.local:
            print 'Checking in new version number: ' + version
            os.system('svn ci -m "New build, version: ' + version + '" ' + VERSION_FILENAME)

    else:
        print 'Error: Version number: ' + version + ' is not HEAD!'
        sys.exit(1)
    
except IndexError:
    sys.exit(1)
