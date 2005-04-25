"""

Util - hellanzb misc functions

(c) Copyright 2005 Philip Jenvey, Ben Bangert
[See end of file]
"""
import os, popen2, pty, re, signal, string, thread, threading, time, Hellanzb
from distutils import spawn
from heapq import heappop, heappush
from threading import Condition
from traceback import print_stack
from twisted.internet import protocol, utils
from Hellanzb.Log import *
from Queue import Queue
from StringIO import StringIO

__id__ = '$Id$'

class FatalError(Exception):
    """ An error that will cause the program to exit """
    def __init__(self, message):
        self.args = [message]
        self.message = message

SPLIT_CMDLINE_ARGS_RE = re.compile(r'( |"[^"]*")')
class TopenTwisted(protocol.ProcessProtocol):
    """ Ptyopen (popen + extra hellanzb stuff)-like class for Twisted. Runs a sub process
    and wait()s for output """

    activePool = []
    
    def __init__(self, cmd, captureStdErr = True):
        # FIXME: seems like twisted just writes something to stderr if there was a
        # problem. this class should probably always capture stderr, optionally to another
        # stream
        self.cmd = cmd
        self.prettyCmd = cmd # FIXME: for compat. with ptyopen
        self.captureStdErr = captureStdErr
        self.args = self.parseCmdToList(cmd)
        self.outBuf = []
        self.finished = Condition()
        self.returnCode = None
        self.isRunning = False

        self.threadIdent = thread.get_ident()

        # ProcessProtocol has no instructor (when I wrote this). just incase
        if hasattr(protocol.ProcessProtocol, '__init__') and callable(protocol.ProcessProtocol.__init__):
            protocol.ProcessProtocol.__init__(self)

    def received(self, data):
        lines = data.split('\n')
        for line in lines:
            self.outBuf.append(line + '\n')
        
    def outReceived(self, data):
        self.received(data)

    def errReceived(self, data):
        if self.captureStdErr:
            self.received(data)

    def outputError(self, err):
        self.transport.loseConnection()

    def processEnded(self, reason):
        self.returnCode = reason.value.exitCode

        self.finished.acquire()
        self.finished.notify()
        self.finished.release()

        self.isRunning = False
        TopenTwisted.activePool.remove(self)

    def kill(self):
        if self.isRunning:
            try:
                os.kill(self.transport.pid, signal.SIGKILL)
            except OSError, ose:
                error('Unexpected problem while kill -9ing pid: ' + str(self.transport.pid) + \
                      ' process: ' + self.cmd, ose)
                
        self.finished.acquire()
        self.finished.notify()
        self.finished.release()

    def parseCmdToList(self, cmd):
        cleanDoubleQuotesRe = re.compile(r'^"|"$')
        args = []
        fields = SPLIT_CMDLINE_ARGS_RE.split(cmd)
        for field in fields:
            if field == '' or field == ' ':
                continue
            args.append(cleanDoubleQuotesRe.sub('', field))
        return args

    def readlinesAndWait(self):
        from twisted.internet import reactor
        reactor.spawnProcess(self, self.args[0], args = self.args, env = os.environ)
        self.isRunning = True
        TopenTwisted.activePool.append(self)
        
        self.finished.acquire()
        self.finished.wait()
        self.finished.release()

        # Here is where PostProcessor will typically die. After a process has been killed
        checkShutdown()

        return self.outBuf, self.returnCode

    def getPid(self):
        # FIXME: this is for compat. w/ ptyopen
        return self.transport.pid
    
    def killAll():
        """ kill -9 all active topens """
        for active in TopenTwisted.activePool:
            active.kill()
    killAll = staticmethod(killAll)

# FIXME: Don't use ptyopen/popen at all any longer
# NOTE: Ptyopen, like popens, is odd with return codes and their status. You seem to be
# able to get the correct *return code* from a Ptyopen.wait(), but you won't be able to
# get the correct WCOREDUMP *status*. This is because pty/popen run your executable via
# /bin/sh. The shell will relay the *return code* of the process back to python correctly,
# but I suspect when you check for WCOREDUMP you're checking whether or not /bin/sh core
# dumped, not your process. The solution to this is to pass the cmd as a list -- the cmd
# and it's args. This tells pty/popen to run the process directly instead of via /bin/sh,
# and you get the right WCOREDUMP *status*
class Ptyopen(popen2.Popen3):
    def __init__(self, cmd, capturestderr = False, bufsize = -1):
        """ Popen3 class (isn't this actually Popen4, capturestderr = False?) that uses ptys
instead of pipes, to allow inline reading (instead of potential i/o buffering) of output
from the child process. It also stores the cmd it's running (as a string) and the thread
that created the object, for later use """
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
        TopenTwisted.activePool.append(self)

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
                    TopenTwisted.activePool.remove(self)
            except os.error:
                pass
        return self.sts

    def wait(self):
        """Wait for and return the exit status of the child process."""
        if self.sts < 0:
            pid, sts = os.waitpid(self.pid, 0)
            if pid == self.pid:
                self.sts = sts
                TopenTwisted.activePool.remove(self)
        return self.sts

    def readlinesAndWait(self):
        """ Read lines and wait for the process to finish. Don't read the lines too quickly,
otherwise we could cause a deadlock with the scroller. Slow down the reading by pausing
shortly after every read """
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
instead of pipes, to allow inline reading (instead of potential i/o buffering) of output
from the child process. It also stores the cmd it's running (as a string) and the thread
that created the object, for later use """
        #popen2._cleanup()
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
        TopenTwisted.activePool.append(self)

def Topen(cmd):
    """ FIXME: Don't use ptyopen anymore at all. Rename TopenTwisted to Topen (or
    something better)"""
    from twisted.internet import reactor
    if reactor.running:
        return TopenTwisted(cmd)
    else:
        return Ptyopen2(cmd)

# Future optimization: Faster way to init this from xml files would be to set the entire
# list backing the queue in one operation (instead of putting 20k times)
# can heapq.heapify(list) help?
class PriorityQueue(Queue):
    """ Thread safe priority queue. This is the easiest way to do it (Queue.Queue providing the thread safety
    and heapq providing priority). We may be able to get better performance by using something other than
    heapq, but hellanzb use of pqueues is limited -- so performance is not so important. Notes on performance:
    
    o An O(1) priority queue is always preferable, but I'm not sure that's even feasible w/ this collection 
      type and/or python.
    o From various google'd python hacker benchmarks it looks like python lists backed pqueues & bisect give
      you pretty good performance, and you probably won't benefit from heap based pqueues unless you're
      dealing with > 10k items. And dicts don't actually seem to help
    """
    def __init__(self):
        """ Python 2.4 replaces the list backed queue with a collections.deque, so we'll just
        emulate 2.3 behavior everywhere for now """
        Queue.__init__(self)
        self.queue = []
        
    def _put(self, item):
        """ Assume Queue is backed by a list. Add the new item to the list, taking into account
            priority via heapq """
        heappush(self.queue, item)

    def _get(self):
        """ Assume Queue is backed by a list. Pop off the first item, taking into account priority
            via heapq """
        return heappop(self.queue)


def getLocalClassName(klass):
    """ Get the local name (no package/module information) of the specified class instance """
    klass = str(klass)
    
    lastDot = klass.rfind('.')
    if lastDot > -1:
        klass = klass[lastDot + 1:]
        
    return klass    
    
def assertIsExe(exe):
    """ Abort the program if the specified file is not in our PATH and executable """
    if len(exe) > 0:
        exe = os.path.basename(exe.split()[0])
        fullPath = spawn.find_executable(exe)
        if fullPath != None and os.access(fullPath, os.X_OK):
            return
    raise FatalError('Cannot continue program, required executable not in path: ' + exe)

def dirHasFileType(dirName, fileExtension):
    return dirHasFileTypes(dirName, [ fileExtension ])

def dirHasFileTypes(dirName, fileExtensionList):
    """ Determine if the specified directory contains any files of the specified type -- that
type being defined by it's filename extension. the match is case insensitive """
    for file in os.listdir(dirName):
        ext = getFileExtension(file)
        if ext:
            for type in fileExtensionList:
                if ext.lower() == type.lower():
                    return True
    return False

def getFileExtension(fileName):
    """ Return the extenion of the specified file name """
    if len(fileName) > 1 and fileName.find('.') > -1:
        return string.lower(os.path.splitext(fileName)[1][1:])

def stringEndsWith(string, match):
    matchLen = len(match)
    if len(string) >= matchLen and string[-matchLen:] == match:
        return True
    return False

def touch(fileName):
    """ Set the access/modified times of this file to the current time. Create the file if it
does not exist. """
    fd = os.open(fileName, os.O_WRONLY | os.O_CREAT, 0666)
    os.close(fd)
    os.utime(fileName, None)

def archiveName(dirName):
    """ Extract the name of the archive from the archive's absolute path, or it's .nzb file
name """
    # pop off separator and basename
    while dirName[len(dirName) - 1] == os.sep:
        dirName = dirName[0:len(dirName) - 1]
    name = os.path.basename(dirName)

    # Strip the msg_id and .nzb extension from an nzb file name
    if len(name) > 3 and name[-3:].lower() == 'nzb':
        name = re.sub(r'msgid_.*?_', r'', name)
        name = re.sub(r'\.nzb$', r'', name)

    return name

def checkShutdown(message = 'Shutting down..'):
    """ Shutdown is a special exception """
    try:
        if Hellanzb.shutdown:
            debug(message)
            raise SystemExit(Hellanzb.SHUTDOWN_CODE)
        return False
    
    except (AttributeError, NameError):
        # typical during app shutdown
        raise SystemExit(Hellanzb.SHUTDOWN_CODE)
    
    except Exception, e:
        print 'Error in Util.checkShutdown' + str(e)
        raise SystemExit(Hellanzb.SHUTDOWN_CODE)

# FIXME: defineServer and anything else called from the config file should be moved into
# their own ConfigFileFunctions Module. all config file functions should: Never call
# debug()
def defineServer(**args):
    """ Define a usenet server """
    id = args['id']
    Hellanzb.SERVERS[id] = {}
    
    for var in (args):
        exec 'Hellanzb.SERVERS[id][\'' + var + '\'] = args[\'' + var + '\']'

def truncate(str, length = 60, reverse = False):
    """ Truncate a string to certain length. Appends '...' to the string if truncated -- and
those three periods are included in the specified length"""
    if str == None:
        return str
    
    if len(str) > int(length):
        if reverse:
            return '...' + str[-(int(length) - 3):]
        else:
            return str[0:int(length) - 3] + '...'
    
    return str

def rtruncate(*args, **kwargs):
    return truncate(reverse = True, *args, **kwargs)

def truncateToMultiLine(line, length = 60, prefix = '', indentPrefix = None):
    """ Parse a message into multiple lines of the specified length """
    multiLine = ''
    numLines = ((len(line) - 1) / 60) + 1
    offset = 0
    for i in range(numLines):
        if indentPrefix != None and i > 0:
            multiLine += indentPrefix + line[offset:length * (i + 1)] + '\n'
        else:
            multiLine += prefix + line[offset:length * (i + 1)] + '\n'
        offset += length
    return multiLine

def getStack():
    """ Return the current execution stack as a string """
    s = StringIO()
    print_stack(file = s)
    s = s.getvalue()
    return s

def inMainThread():
    if Hellanzb.MAIN_THREAD_IDENT == thread.get_ident():
        return True
    return False

"""
/*
 * Copyright (c) 2005 Philip Jenvey <pjenvey@groovie.org>
 *                    Ben Bangert <bbangert@groovie.org>
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
