#!/usr/bin/env python
"""

build_util.py - Build related functions 

@author pjenvey

"""
import distutils.util, md5, os, setup, shutil, sys, tarfile
from Hellanzb.Util import Ptyopen2

__id__ = '$Id$'

VERSION_FILENAME = './Hellanzb/__init__.py'

def assertUpToDate(workingCopyDir = None):
    """ Ensure the working copy is up to date with the repository """
    if workingCopyDir == None:
        p = Ptyopen2('svn diff')
    else:
        p = Ptyopen2('svn diff ' + workingCopyDir)
        
    output, status = p.readlinesAndWait()
    
    if len(output) > 0:
        print 'Error: Cannot continue, working copy is not up to date with repository!'
        print '       Run: svn diff'
        sys.exit(1)

def branchRelease(version):
    """ branch the code base """
    fromRepository = getRepository()
    
    repository = fromRepository
    if repository[len(repository) - 1:] == '/':
        repository = repository[:len(repository) - 1]
        
    # Branch
    branchURL = repository.replace('trunk', 'branches') + '/' + version
    print 'Branching from: ' + fromRepository + ' to: ' + branchURL
    os.system('svn copy -m "TEST -- Branching new release, version: ' + version + '" . ' + branchURL)
    
    print 'Switching working copy to the new branch'
    os.system('svn switch ' + branchURL)

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
    print 'Building new FreeBSD port'
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
    shutil.copy(portStubDir + os.sep + 'pkg-descr', destDir + os.sep + 'pkg-descr')

    # create a distinfo with the checksum
    distinfo = open(destDir + os.sep + 'distinfo', 'w')
    distinfo.write('MD5 (hellanzb-' + version + '.tar.gz) = ' +
                 md5File('dist/hellanzb-' + version + '.tar.gz') + '\n')
    distinfo.write('SIZE (hellanzb-' + version + '.tar.gz) = ' +
                 str(os.path.getsize('dist/hellanzb-' + version + '.tar.gz')) + '\n')
    distinfo.close()

    dir = portDestDir[len('dist/'):]
    createTarBall('dist', dir, dir + '.tar.gz')

def buildDPort(version):
    print 'Building new Darwin port'
    portStubDir = 'darwin-dport'
    
    portDestDir = 'dist/hellanzb-darwin-dport-' + version
    destDir = portDestDir + os.sep + 'hellanzb'

    if not os.path.isdir(portDestDir):
        os.mkdir(portDestDir)
    if not os.path.isdir(destDir):
        os.mkdir(destDir)

    # replace the version, and darwinports seems to require a checksum
    checksum = md5File('dist/hellanzb-' + version + '.tar.gz')
    os.system('cat ' + portStubDir + os.sep + 'Portfile | sed s/____VERSION____/' + version + '/ | ' +
              'sed s/____MD5_CHECKSUM____/' + 'md5\ ' + checksum + '/ > ' + destDir + os.sep + 'Portfile')

    dir = portDestDir[len('dist/'):]
    createTarBall('dist', dir, dir + '.tar.gz')

def bumpVersion(oldVersion):
    """ Bump the ver number. Is dumb and expects 0.0. Will bump by .1 """
    dot = oldVersion.rfind('.')
    prefix = oldVersion[0:dot + 1]
    decimal = int(oldVersion[dot + 1:])
    decimal += 1

    return prefix + str(decimal)

def createTarBall(workingDir, dirName, fileName):
    """ tar -cxvf """
    cwd = os.getcwd()
    os.chdir(workingDir)
    
    tarBall = tarfile.open(fileName, 'w:gz')
    for file in os.listdir(dirName):
        tarBall.add(dirName + os.sep + file)
    tarBall.close()
        
    os.chdir(cwd)

def getRepository():
    """ Determine the SVN repostiory for the cwd """
    p = Ptyopen2('svn info')
    output, status = p.readlinesAndWait()
    
    for line in output:
        if len(line) > 3 and line[0:3] == 'URL':
            return line[5:].rstrip()
        
    raise FatalError('Could not determine SVN repository')

def md5File(fileName):
    """ Return the md5 checksum of the specified file """
    m = md5.new()
    file = open(fileName)
    for line in file.readlines():
        m.update(line)
    return m.hexdigest()

def uploadToHost(version, host):
    """ Upload the new build of version to the UPLOAD_HOST """
    files = []
    for file in os.listdir('dist'):
        # Upload only files for the specified version that aren't platform specific
        if file.find('-' + version + '.') > -1 and file.find(distutils.util.get_platform()) == -1:
            files.append(file)

    if len(files) == 0:
        print 'Error, could not find files to upload'

    cmd = 'scp '
    for file in files:
            cmd += 'dist/' + file + ' '
    cmd += host

    os.system(cmd)

def writeVersion(newVersion, destDir = None):
    """ Write out a new version number """
    if destDir:
        versionFile = open(destDir + os.sep + VERSION_FILENAME, 'w')
    else:
        versionFile = open(VERSION_FILENAME, 'w')
    versionFile.write('version = \'' + newVersion + '\'\n')
    versionFile.close()
