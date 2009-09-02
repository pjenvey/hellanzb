#!/usr/bin/env python
"""

build_util.py - Build related functions 

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import distutils.util, distutils.spawn, os, re, setup, shutil, sys, tarfile
try:
    from hashlib import md5
except ImportError:
    from md5 import md5

if sys.version >= '2.5':
    from hashlib import sha256

__id__ = '$Id$'

VERSION_FILENAME = './Hellanzb/__init__.py'
# rpm builds aren't very portable when built from FreeBSD machines.
# srpms are useless
#BDIST_RPM_REQUIRES = 'python >= 2.3 python-twisted pararchive rar flac shorten'

import popen2, pty, re, signal, thread, time
SPLIT_CMDLINE_ARGS_RE = re.compile(r'( |"[^"]*")')
# FIXME: Ptyopen has been deprecated by Topen (because we now used twisted all of the
# time, all processes are ran through twisted). However it is still used by the build
# scripts. they should be converted to normal popen, or the Ptyopen code should be moved
# into the build code
    
# NOTE: Ptyopen, like popens, is odd with return codes and their status. You seem to be
# able to get the correct *return code* from a Ptyopen.wait(), but you won't be able to
# get the correct WCOREDUMP *status*. This is because pty/popen run your executable via
# /bin/sh. The shell will relay the *return code* of the process back to python correctly,
# but I suspect when you check for WCOREDUMP you're checking whether or not /bin/sh core
# dumped, not your process. The solution to this is to pass the cmd as a list -- the cmd
# and its args. This tells pty/popen to run the process directly instead of via /bin/sh,
# and you get the right WCOREDUMP *status*
class Ptyopen(popen2.Popen3):
    def __init__(self, cmd, capturestderr = False, bufsize = -1):
        """ Popen3 class (isn't this actually Popen4, capturestderr = False?) that uses ptys
        instead of pipes, to allow inline reading (instead of potential i/o buffering) of
        output from the child process. It also stores the cmd its running (as a string)
        and the thread that created the object, for later use """
        import pty
        # NOTE: most of this is cutnpaste from Popen3 minus the openpty calls
        #popen2._cleanup()
        self.prettyCmd = cmd
        cmd = self.parseCmdToList(cmd)
        self.cmd = cmd
        self.threadIdent = thread.get_ident()

        p2cread, p2cwrite = pty.openpty()
        c2pread, c2pwrite = pty.openpty()
        if capturestderr:
            errout, errin = pty.openpty()
        self.pid = os.fork()
        if self.pid == 0:
            # Child
            os.dup2(p2cread, 0)
            os.dup2(c2pwrite, 1)
            if capturestderr:
                os.dup2(errin, 2)
            self._run_child(cmd)
        os.close(p2cread)
        self.tochild = os.fdopen(p2cwrite, 'w', bufsize)
        os.close(c2pwrite)
        self.fromchild = os.fdopen(c2pread, 'r', bufsize)
        if capturestderr:
            os.close(errin)
            self.childerr = os.fdopen(errout, 'r', bufsize)
        else:
            self.childerr = None

    def parseCmdToList(self, cmd):
        cleanDoubleQuotesRe = re.compile(r'^"|"$')
        args = []
        fields = SPLIT_CMDLINE_ARGS_RE.split(cmd)
        for field in fields:
            if field == '' or field == ' ':
                continue
            args.append(cleanDoubleQuotesRe.sub('', field))
        return args

    def getPid(self):
        return self.pid

    def kill(self):
        os.kill(self.pid, signal.SIGKILL)

    def poll(self):
        """Return the exit status of the child process if it has finished,
        or -1 if it hasn't finished yet."""
        if self.sts < 0:
            try:
                pid, sts = os.waitpid(self.pid, os.WNOHANG)
                if pid == self.pid:
                    self.sts = sts
            except os.error:
                pass
        return self.sts

    def wait(self):
        """Wait for and return the exit status of the child process."""
        if self.sts < 0:
            pid, sts = os.waitpid(self.pid, 0)
            if pid == self.pid:
                self.sts = sts
        return self.sts

    def readlinesAndWait(self):
        """ Read lines and wait for the process to finish. Don't read the lines too
        quickly, otherwise we could cause a deadlock with the scroller. Slow down the
        reading by pausing shortly after every read """
        output = []
        while True:
            line = self.fromchild.readline()
            if line == '': # EOF
                break
            output.append(line)

            # Somehow the scroll locks end up getting blocked unless their consumers pause
            # as short as around 1/100th of a milli every loop. You might notice this
            # delay when nzbget scrolling looks like a slightly different FPS from within
            # hellanzb than running it directly
            time.sleep(.0001)

        returnStatus = self.wait()
        return output, os.WEXITSTATUS(returnStatus)

class Ptyopen2(Ptyopen):
    """ Ptyopen = Popen3
        Ptyopen2 = Popen4
        Python was lame for naming it that way and I am just as lame
        for following suit """
    def __init__(self, cmd, bufsize = -1):
        """ Popen3 class (isn't this actually Popen4, capturestderr = False?) that uses ptys
        instead of pipes, to allow inline reading (instead of potential i/o buffering) of
        output from the child process. It also stores the cmd its running (as a string)
        and the thread that created the object, for later use """
        import pty
        #popen2._cleanup()
        self.prettyCmd = cmd
        cmd = self.parseCmdToList(cmd)
        self.cmd = cmd
        self.threadIdent = thread.get_ident()

        p2cread, p2cwrite = pty.openpty()
        c2pread, c2pwrite = pty.openpty()
        self.pid = os.fork()
        if self.pid == 0:
            # Child
            os.dup2(p2cread, 0)
            os.dup2(c2pwrite, 1)
            os.dup2(c2pwrite, 2)
            self._run_child(cmd)
        os.close(p2cread)
        self.tochild = os.fdopen(p2cwrite, 'w', bufsize)
        os.close(c2pwrite)
        self.fromchild = os.fdopen(c2pread, 'r', bufsize)

def assertIsExe(exe_list):
    """ Abort the program if none of the specified files are executable """
    if not isinstance(exe_list, (list, tuple)):
        exe_list = [exe_list]
    if exe_list:
        for exe in exe_list:
            if exe == os.path.basename(exe):
                try:
                    fullPath = distutils.spawn.find_executable(exe)
                except:
                    raise Exception(
                        'Cannot continue program, your platform does not support '
                        'searching the path for an executable and you did not supply '
                        'the full path to the %s executable.' % exe)
            else:
                fullPath = exe
            if fullPath != None and os.access(fullPath, os.X_OK):
                return fullPath
    raise Exception('Cannot continue program, required executable not found: \'' + \
                     exe + '\'')

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
    branchURL = repository.replace('trunk', 'tags') + '/' + version
    print 'Branching from: ' + fromRepository + ' to: ' + branchURL
    os.system('svn copy -m "Tagging new release, version: ' + version + '" . ' + branchURL)
    
    print 'Switching working copy to the new branch'
    os.system('svn switch ' + branchURL)

def buildDist():
    """ build the source and binary distributions """
    oldArg = sys.argv

    # Build source and binary distributions
    sys.argv = [ 'setup.py', 'sdist' ]
    setup.runSetup()
    
    sys.argv = [ 'setup.py', 'bdist' ]
    setup.runSetup()

    #sys.argv = [ 'setup.py', 'bdist_rpm', '--requires', BDIST_RPM_REQUIRES ]
    #setup.runSetup()
    
    sys.argv = oldArg

def buildPort(version):
    """ build a FreeBSD port """
    print 'Building new FreeBSD port'
    portStubDir = 'freebsd-port'
    
    portDestDir = 'dist/hellanzb-freebsd-port-' + version
    destDir = os.path.join(portDestDir, 'hellanzb')

    if not os.path.isdir(portDestDir):
        os.mkdir(portDestDir)
    if not os.path.isdir(destDir):
        os.mkdir(destDir)

    # replace the version
    os.system('cat ' + os.path.join(portStubDir, 'Makefile') + ' | sed s/____VERSION____/' + \
              version + '/ > ' + os.path.join(destDir, 'Makefile'))

    # copy over the port files
    shutil.copy(os.path.join(portStubDir, 'pkg-descr'), os.path.join(destDir, 'pkg-descr'))
    shutil.copy(os.path.join(portStubDir, 'pkg-plist'), os.path.join(destDir, 'pkg-plist'))
    shutil.rmtree(os.path.join(destDir, 'files'), ignore_errors=True)
    shutil.copytree(os.path.join(portStubDir, 'files'), os.path.join(destDir, 'files'))
    dotSVNDir = os.path.join(destDir, 'files', '.svn')
    if os.path.isdir(dotSVNDir):
        shutil.rmtree(dotSVNDir)

    # create a distinfo with the checksum
    distinfo = open(os.path.join(destDir, 'distinfo'), 'w')
    distinfo.write('MD5 (hellanzb-' + version + '.tar.gz) = ' +
                 md5File('dist/hellanzb-' + version + '.tar.gz') + '\n')
    distinfo.write('SHA256 (hellanzb-' + version + '.tar.gz) = ' +
                 sha256File('dist/hellanzb-' + version + '.tar.gz') + '\n')
    distinfo.write('SIZE (hellanzb-' + version + '.tar.gz) = ' +
                 str(os.path.getsize('dist/hellanzb-' + version + '.tar.gz')) + '\n')
    distinfo.close()

    dir = portDestDir[len('dist/'):]
    createTarBall('dist', dir, dir + '.tar.gz')

def buildDPort(version):
    print 'Building new Darwin port'
    portStubDir = 'darwin-dport'
    
    portDestDir = os.path.join('dist', 'hellanzb-darwin-dport-' + version)
    destDir = os.path.join(portDestDir, 'hellanzb')

    if not os.path.isdir(destDir):
        os.makedirs(destDir)

    # replace the version, and darwinports seems to require a checksum
    checksum = md5File('dist/hellanzb-' + version + '.tar.gz')
    os.system('cat ' + os.path.join(portStubDir, 'Portfile') + ' | sed s/____VERSION____/' + \
              version + '/ | ' + 'sed s/____MD5_CHECKSUM____/' + 'md5\ ' + checksum + '/ > ' + \
              os.path.join(destDir, 'Portfile'))

    dir = portDestDir[len('dist' + os.sep):]
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
        tarBall.add(os.path.join(dirName, file))
    tarBall.close()
        
    os.chdir(cwd)

def getRepository():
    """ Determine the SVN repostiory for the cwd """
    p = Ptyopen2('svn info')
    output, status = p.readlinesAndWait()
    
    for line in output:
        if len(line) > 3 and line[0:3] == 'URL':
            return line[5:].rstrip()
        
    raise Exception('Could not determine SVN repository')

def md5File(fileName):
    """ Return the md5 checksum of the specified file """
    m = md5()
    file = open(fileName)
    for line in file.readlines():
        m.update(line)
    file.close()
    return m.hexdigest()

def sha256File(fileName):
    """ Return the SHA-256 hash of the specified file """
    if sys.version >= '2.5':
        s = sha256()
        file = open(fileName)
        for line in file.readlines():
            s.update(line)
        file.close()
        return s.hexdigest()
    else:
        p = Ptyopen2('sha256 -q ' + fileName)
        output, status = p.readlinesAndWait()
        return output[0].rstrip()

def uploadToHost(version, host, dir):
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
    cmd += host + ':' + dir

    # NOTE: actually, keep the old releases around. Don't break their url so soon, someone
    # could even be installing an old port
    # First, move the old release out of the way.
    #os.system('ssh ' + host + ' mv ' + dir + '/*.gz ' + dir + '/old/')
        
    os.system(cmd)

def writeVersion(newVersion, destDir = None):
    """ Write out a new version number """
    if destDir:
        versionFile = open(os.path.join(destDir, VERSION_FILENAME), 'w')
    else:
        versionFile = open(VERSION_FILENAME, 'w')
    versionFile.write('version = \'' + newVersion + '\'\n')
    versionFile.close()

"""
Copyright (c) 2005 Philip Jenvey <pjenvey@groovie.org>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:
1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.
3. The name of the author or contributors may not be used to endorse or
   promote products derived from this software without specific prior
   written permission.

THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
SUCH DAMAGE.

$Id$
"""
