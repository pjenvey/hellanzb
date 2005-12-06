"""

Util - hellanzb misc functions

(c) Copyright 2005 Philip Jenvey, Ben Bangert
[See end of file]
"""
import os, popen2, pty, re, signal, string, thread, threading, time, Hellanzb
from distutils import spawn
from heapq import heappop, heappush
from os.path import normpath
from random import randint
from shutil import move
from threading import Condition
from traceback import print_stack
from twisted.internet import protocol, utils
from Hellanzb.Log import *
from Queue import Empty, Queue
from StringIO import StringIO

__id__ = '$Id$'

class FatalError(Exception):
    """ An error that will cause the program to exit """
    def __init__(self, message):
        self.args = [message]
        self.message = message

class EmptyForThisPool(Empty):
    """ The queue is empty in terms of our current serverPool, but there are still segments to
    be downloaded for alternate download pools """
    pass
    
class OutOfDiskSpace(Exception):
    """ Out of disk space """
    pass

class PoolsExhausted(Exception):
    """ Attempts to download a segment on all known server pools failed """
    pass
    
class IDPool:
    """ Returns a unique identifier, used for keying NZBs and their archives """
    
    nextId = 0
    
    def getNextId():
        """ Return a new unique identifier """
        id = IDPool.nextId
        IDPool.nextId += 1
        return id
    getNextId = staticmethod(getNextId)
    
SPLIT_CMDLINE_ARGS_RE = re.compile(r'( |"[^"]*")')
class Topen(protocol.ProcessProtocol):
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
        self.outBuf = StringIO()
        self.finished = Condition()
        self.returnCode = None
        self.isRunning = False

        self.threadIdent = thread.get_ident()

        # ProcessProtocol has no instructor (when I wrote this). just incase
        if hasattr(protocol.ProcessProtocol, '__init__') and \
                callable(protocol.ProcessProtocol.__init__):
            protocol.ProcessProtocol.__init__(self)

    def received(self, data):
        self.outBuf.write(data)
        
    def outReceived(self, data):
        self.received(data)

    def errReceived(self, data):
        if self.captureStdErr:
            self.received(data)

    def outputError(self, err):
        self.transport.loseConnection()

    def processEnded(self, reason):
        self.returnCode = reason.value.exitCode

        from Hellanzb.Log import debug
        import thread
        debug('processEnded THREAD ID: ' + str(thread.get_ident()) + ' (' + self.cmd + ') ' + \
              'aquiring lock')
        self.finished.acquire()
        debug('processEnded THREAD ID: ' + str(thread.get_ident()) + ' (' + self.cmd + ')')
        self.finished.notify()
        self.finished.release()

        self.isRunning = False
        Topen.activePool.remove(self)

    def kill(self):
        from Hellanzb.Log import debug, error
        if self.isRunning:
            try:
                os.kill(self.transport.pid, signal.SIGKILL)
            except OSError, ose:
                error('Unexpected problem while kill -9ing pid: ' + str(self.transport.pid) + \
                      ' process: ' + self.cmd, ose)
            except Exception, e:
                debug('could not kill process: ' + self.cmd + ': ' + str(e))
                
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
        self.isRunning = True
        Topen.activePool.append(self)

        self.finished.acquire()
        from Hellanzb.Log import debug
        import thread
        debug('spawnProcess THREAD ID: ' + str(thread.get_ident()) + ' (' + self.cmd + ')')

        # The reactor could have fallen asleep on us in -Lp mode! Why? I'm not sure, but
        # it dies after the first par2 process (Topen call) =[
        reactor.wakeUp()

        # Have the main, twisted thread, run the process. If we trigger spawnProcess from
        # a separate thread (which PostProcessor/Topens are always used from) instead, bad
        # things can occur (on Linux 2.6.x we can end up with defunct processes -- Trac
        # ticket #33). Running any twisted call from a non twisted thread is asking for
        # trouble. We also MUST usePTY, otherwise the processes receive signals (in
        # particular, SIGINT, rendering our first CTRL-C ignoring code useless, as it ends
        # up killing our sub processes)
        reactor.callFromThread(reactor.spawnProcess, self, self.args[0], self.args, os.environ,
                               usePTY = 1)

        self.finished.wait()
        self.finished.release()

        # Here is where PostProcessor will typically die. After a process has been killed
        checkShutdown()

        # prepare the outbuffer (LAME)
        output = [line + '\n' for line in self.outBuf.getvalue().split('\n')]
        
        return output, self.returnCode

    def getPid(self):
        # FIXME: this is for compat. w/ ptyopen
        return self.transport.pid
    
    def killAll():
        """ kill -9 all active topens """
        for active in Topen.activePool:
            active.kill()
    killAll = staticmethod(killAll)

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
        Topen.activePool.append(self)

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
                    Topen.activePool.remove(self)
            except os.error:
                pass
        return self.sts

    def wait(self):
        """Wait for and return the exit status of the child process."""
        if self.sts < 0:
            pid, sts = os.waitpid(self.pid, 0)
            if pid == self.pid:
                self.sts = sts
                Topen.activePool.remove(self)
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
        Topen.activePool.append(self)

# Future optimization: Faster way to init this from xml files would be to set the entire
# list backing the queue in one operation (instead of putting 20k times)
# can heapq.heapify(list) help?
class PriorityQueue(Queue):
    """ Thread safe priority queue. This is the easiest way to do it (Queue.Queue
    providing the thread safety and heapq providing priority). We may be able to get
    better performance by using something other than heapq, but hellanzb use of pqueues is
    limited -- so performance is not so important. Notes on performance:
    
    o An O(1) priority queue is always preferable, but I'm not sure that's even feasible
      w/ this collection type and/or python.
    o From various google'd python hacker benchmarks it looks like python lists backed
      pqueues & bisect give you pretty good performance, and you probably won't benefit
      from heap based pqueues unless you're dealing with > 10k items. And dicts don't
      actually seem to help
    """
    def __init__(self):
        """ Python 2.4 replaces the list backed queue with a collections.deque, so we'll just
        emulate 2.3 behavior everywhere for now """
        Queue.__init__(self)
        self.queue = []

    def __len__(self):
        return len(self.queue)

    def clear(self):
        """ empty the queue """
        if len(self.queue):
            self.mutex.acquire()
            del self.queue
            self.queue = []
            if not hasattr(self, 'not_empty'):
                # python 2.3
                self.esema.acquire()
            self.mutex.release()
        
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
    raise FatalError('Cannot continue program, required executable not in path: \'' + \
                     exe + '\'')

def dirHasFileType(dirName, fileExtension):
    return dirHasFileTypes(dirName, [ fileExtension ])

def dirHasFileTypes(dirName, fileExtensionList):
    """ Determine if the specified directory contains any files of the specified type -- that
    type being defined by its filename extension. the match is case insensitive """
    for file in os.listdir(dirName):
        ext = getFileExtension(file)
        if ext:
            for type in fileExtensionList:
                if ext.lower() == type.lower():
                    return True
    return False

def getFileExtension(fileName):
    """ Return the extenion of the specified file name, in lowercase """
    if len(fileName) > 1 and fileName.find('.') > -1:
        return string.lower(os.path.splitext(fileName)[1][1:])

def touch(fileName):
    """ Set the access/modified times of this file to the current time. Create the file if
    it does not exist """
    fd = os.open(fileName, os.O_WRONLY | os.O_CREAT, 0666)
    os.close(fd)
    os.utime(fileName, None)

def archiveName(dirName):
    """ Extract the name of the archive from the archive's absolute path, or its .nzb file
    name """
    from Hellanzb.PostProcessorUtil import DirName
    # pop off separator and basename
    while dirName[len(dirName) - 1] == os.sep:
        dirName = dirName[0:len(dirName) - 1]
    if isinstance(dirName, DirName) and dirName.isSubDir():
        from Hellanzb.Log import info
        name = os.path.basename(dirName.parentDir) + \
        normpath(dirName).replace(normpath(dirName.parentDir), '')
    else:
        name = os.path.basename(dirName)

    # Strip the msg_id and .nzb extension from an nzb file name
    if len(name) > 3 and name[-3:].lower() == 'nzb':
        name = re.sub(r'msgid_.*?_', r'', name)
        name = re.sub(r'\.nzb$', r'', name)

    return name

def checkShutdown(message = 'Shutting down..'):
    """ Raise a SystemExit exception if the SHUTDOWN flag has been set """
    try:
        if Hellanzb.SHUTDOWN:
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
    """ Truncate a string to the specified length. Appends '...' to the string if truncated --
    and those three periods are included in the specified length """
    if str == None:
        return str
    
    if len(str) > int(length):
        if reverse:
            return '...' + str[-(int(length) - 3):]
        else:
            return str[0:int(length) - 3] + '...'
    
    return str

def rtruncate(*args, **kwargs):
    """ Reverse truncate (truncate from the beginning) """ 
    return truncate(reverse = True, *args, **kwargs)

# FIXME: textwrap.fill() should replace this function
def truncateToMultiLine(line, length = 60, prefix = '', indentPrefix = None):
    """ Parse a one line message into multiple lines of the specified length """
    multiLine = StringIO()
    numLines = ((len(line) - 1) / length) + 1
    offset = 0
    for i in range(numLines):
        if indentPrefix != None and i > 0:
            multiLine.write(indentPrefix + line[offset:length * (i + 1)])
        else:
            multiLine.write(prefix + line[offset:length * (i + 1)])
            
        if i + 1 < numLines:
            multiLine.write('\n')
            
        offset += length
    return multiLine.getvalue()

def flattenDoc(docString):
    """ Take an indented doc string, and remove its newlines and their surrounding whitespace
    """
    clean = ''
    lines = docString.split('\n')
    for line in lines:
        clean += line.strip() + ' '
    return clean

RENAME_SUFFIX = '_hellanzb_renamed'
def hellaRename(filename):
    """ rename a dupe file to filename _hellanzb_renamedX """
    if os.path.exists(filename):
        # Rename the dir if it exists already
        renamedDir = filename + RENAME_SUFFIX
        i = 0
        while os.path.exists(renamedDir + str(i)):
            i += 1
        move(filename, renamedDir + str(i))

DUPE_SUFFIX = '_hellanzb_dupe'
DUPE_SUFFIX_RE = re.compile('(.*)' + DUPE_SUFFIX + '(\d{1,4})')
def _nextDupeName(filename):
    """ Return the next dupeName in the dupeName sequence """
    i = -1
    dupeMatch = DUPE_SUFFIX_RE.match(filename)
    
    # If this is a dupe name already, pull the DUPE_SUFFIX off
    if dupeMatch:
        filename = dupeMatch.group(1)
        i = int(dupeMatch.group(2))

    # Increment dupeName sequence
    renamed = filename + DUPE_SUFFIX + str(i + 1)
    return renamed

def dupeName(filename, checkOnDisk = True, eschewNames = [], minIteration = 0):
    """ Returns a new filename with '_hellanzb_dupeX' appended to it (where X is the next
    integer in a sequence producing the first available unique filename on disk). The
    optional checkOnDisk option is mainly intended for use by the nextDupeName
    function. The optional eschewNames list acts as a list of filenames to be avoided --
    as if they were on disk
    
    e.g.:
    With no files in the /test/ dir,
    
    dupeName('/test/file') would return:
    '/test/file'

    dupeName('/test/file', eschewNames = ('/test/file')) would return:
    '/test/file_hellanzb_dupe0'

    With the files 'file' and 'file_hellanzb_dupe0' in the /test/ dir,
    dupeName('/test/file') would return:
    '/test/file_hellanzb_dupe1'

    dupeName('/test/file', eschewNames = ('/test/file_hellanzb_dupe1')) would return:
    '/test/file_hellanzb_dupe2'
    """
    if not os.path.exists(filename) and minIteration == 0 and \
            filename not in eschewNames:
        return filename
    
    def onDisk(filename):
        if not checkOnDisk:
            return False
        return os.path.exists(filename)
        
    i = 0
    while True:
        i += 1
        filename = _nextDupeName(filename)
        if not onDisk(filename) and filename not in eschewNames and i >= minIteration:
            break

    return filename

def nextDupeName(*args, **kwargs):
    """ nextDupeName acts as dupeName, except it will always increment the dupeName sequence
    by at least one time

    e.g.:
    With no files in the /test/ dir,
    
    nextDupeName('/test/file') would return:
    '/test/file_hellanzb_dupe0'

    nextDupeName('/test/file', eschewNames = ('/test/file_hellanzb_dupe0')) would return:
    '/test/file_hellanzb_dupe1'

    With the files 'file' and 'file_hellanzb_dupe0' in the /test/ dir,
    nextDupeName('/test/file') would return:
    '/test/file_hellanzb_dupe1'

    nextDupeName('/test/file', checkOnDisk = False) would return:
    '/test/file_hellanzb_dupe0'

    nextDupeName('/test/file', checkOnDisk = False,
                 eschewNames = ('/test/file_hellanzb_dupe0')) would return:
    '/test/file_hellanzb_dupe1'
    """
    if not kwargs.has_key('minIteration'):
        kwargs['minIteration'] = 1
    return dupeName(*args, **kwargs)

def getMsgId(archiveName):
    """ grab the msgid from a 'msgid_31337_HellaBlah.nzb string """
    msgId = re.sub(r'.*msgid_', r'', os.path.basename(archiveName))
    msgId = re.sub(r'_.*', r'', msgId)
    return msgId

def walk(root, recurse=0, pattern='*', return_folders=0):
    """ return a recursive directory listing.
    Author: Robin Parmar (http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/52664)
    """
    import fnmatch, os, string
    
    # initialize
    result = []

    # must have at least root folder
    try:
            names = os.listdir(root)
    except os.error:
            return result

    # expand pattern
    pattern = pattern or '*'
    pat_list = string.splitfields( pattern , ';' )
    
    # check each file
    for name in names:
            fullname = os.path.normpath(os.path.join(root, name))

            # grab if it matches our pattern and entry type
            for pat in pat_list:
                    if fnmatch.fnmatch(name, pat):
                            if os.path.isfile(fullname) or (return_folders and os.path.isdir(fullname)):
                                    if os.path.isdir(fullname):
                                            result.append(fullname + '/')
                                    else:
                                            result.append(fullname)
                            continue
                            
            # recursively scan other folders, appending results
            if recurse:
                    if os.path.isdir(fullname) and not os.path.islink(fullname):
                            result = result + walk(fullname, recurse, pattern, return_folders)
                    
    return result
    
def getStack():
    """ Return the current execution stack as a string """
    s = StringIO()
    print_stack(file = s)
    s = s.getvalue()
    return s

def inMainThread():
    """ whether or not the current thread is the main thread """
    if Hellanzb.MAIN_THREAD_IDENT == thread.get_ident():
        return True
    return False

def prettyEta(etaSeconds):
    """ return a cute eta string from seconds """
    hours = int(etaSeconds / (60 * 60))
    minutes = int((etaSeconds - (hours * 60 * 60)) / 60)
    seconds = etaSeconds - (hours * 60 * 60) - (minutes * 60)
    return '%.2d:%.2d:%.2d' % (hours, minutes, seconds)

def toUnicode(str):
    """ Convert the specified string to a unicode string """
    if str == None:
        return str
    return unicode(str, 'latin-1')

def tempFilename(prefix = 'hellanzb-tmp'):
    """ Return a temp filename, prefixed with 'hellanzb-tmp' """
    return prefix + str(randint(10000000, 99999999)) + '.nzb'

def prettySize(bytes):
    """ format a byte count for pretty display """
    bytes = float(bytes)
    
    if bytes < 1024:
            return '<1KB'
    elif bytes < (1024 * 1024):
            return '%dKB' % (bytes / 1024)
    else:
            return '%.1fMB' % (bytes / 1024.0 / 1024.0)

# NOTE: if you're cut & pasting -- the ascii is escaped (\") in one spot
Hellanzb.CMHELLA = \
"""
           ;;;;            .  .
      ... :liil ...........:..:      ,._    ,._      ...................
      :   l$$$:  _.,._       _..,,._ "$$$b. "$$$b.   `_..,,._        :::
      :   $$$$.d$$$$$$L   .d$$$$$$$$L $$$$:  $$$$: .d$$$$$$$$$;      :::
      :  :$$$$P`  T$$$$: :$$$$`  7$$F:$$$$  :$$$$ :$$$$: `$$$$ __  _  |_
      :  l$$$F   :$$$$$  8$$$l""\"""` l$$$l  l$$$l l$$$l   $$$L | ) /_ |_)
      :  $$$$:   l$$$$$L `4$$$bcmang;ACID$::$$$88:`4$$$bmm$$$$;.     ...
      :    ```      ```""              ```    ```    .    ```.     ..:::..
      :..............................................:              `:::`
                                                                      `
"""

# NOTE: if you're cut & pasting -- the ascii is escaped (\") in one spot
Hellanzb.CMHELLA_VERSIONED = \
"""
           ;;;;            .  .
      ... :liil ...........:..:      ,._    ,._      ...................
      :   l$$$:  _.,._       _..,,._ "$$$b. "$$$b.   `_..,,._        :::
      :   $$$$.d$$$$$$L   .d$$$$$$$$L $$$$:  $$$$: .d$$$$$$$$$;      :::
      :  :$$$$P`  T$$$$: :$$$$`  7$$F:$$$$  :$$$$ :$$$$: `$$$$ __  _  |_
      :  l$$$F   :$$$$$  8$$$l""\"""` l$$$l  l$$$l l$$$l   $$$L | ) /_ |_)
      :  $$$$:   l$$$$$L `4$$$bcmang;ACID$::$$$88:`4$$$bmm$$$$;.     ...
      :    ```      ```""              ```    ```    .    ```.     ..:::..
      :..............................................:     %s  `:::`
                                                                      `
"""
def cmVersion(version = Hellanzb.version):
    """ try to make Hellanzb.version always look like this: 'V 1 . 0' """
    cmV = 'V 1 . 0'
    orig = version
    muck = lambda v : 'v' + v.replace('', ' ').rstrip()

    # expand it
    v = muck(orig)
    if len(v) < len(cmV):
        # just left justify for now
        return v.ljust(len(cmV))

    elif len(v) > len(cmV):
        # now try removing non digits and non periods, then expand
        v = muck(re.sub('[^\d.]', '', orig))
        
        if len(v) != len(cmV):
            # just left jusity for now
            v = orig.ljust(len(cmV))

    return v

def cmHella(version = Hellanzb.version):
    """ brand the ascii with a properly formatted version number """
    return Hellanzb.CMHELLA_VERSIONED % (cmVersion(version))

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
