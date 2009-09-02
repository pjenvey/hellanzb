"""

Util - hellanzb misc functions

(c) Copyright 2005 Philip Jenvey, Ben Bangert
[See end of file]
"""
import errno, os, re, signal, string, sys, thread, Hellanzb
try:
    from distutils import spawn
except:
    pass
from heapq import heapify, heappop, heappush
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

# Size of buffer for file i/o
BUF_SIZE = 16 * 1024

class FatalError(Exception):
    """ An error that will cause the program to exit """

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
    skipIds = []
    def getNextId():
        """ Return a new unique identifier """
        while IDPool.nextId in IDPool.skipIds:
            IDPool.nextId += 1
        id = IDPool.nextId
        IDPool.nextId += 1
        return id
    getNextId = staticmethod(getNextId)
    
SPLIT_CMDLINE_ARGS_RE = re.compile(r'( |"[^"]*")')
class Topen(protocol.ProcessProtocol):
    """ Ptyopen (popen + extra hellanzb stuff)-like class for Twisted. Runs a sub process
    and wait()s for output """

    activePool = []
    
    def __init__(self, cmd, postProcessor, captureStdErr = True):
        # FIXME: seems like twisted just writes something to stderr if there was a
        # problem. this class should probably always capture stderr, optionally to another
        # stream
        self.cmd = cmd
        self.captureStdErr = captureStdErr
        self.outBuf = StringIO()
        self.finished = Condition()
        self.returnCode = None
        self.isRunning = False
        self.postProcessor = postProcessor

        self.threadIdent = thread.get_ident()

        # ProcessProtocol has no instructor (when I wrote this). just incase
        if hasattr(protocol.ProcessProtocol, '__init__') and \
                callable(protocol.ProcessProtocol.__init__):
            protocol.ProcessProtocol.__init__(self)

    def getPrettyCmd(self):
        """ Return a pretty representation of this command (one that could be ran via the
        command line) """
        quote = lambda item: ' ' in item and '"%s"' % item.replace('"', r'\"') or item
        return ' '.join(map(quote, self.cmd))
    prettyCmd = property(getPrettyCmd)

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
        debug('processEnded THREAD ID: ' + str(thread.get_ident()) + ' (' + \
                  self.prettyCmd + ') ' + 'aquiring lock')
        self.finished.acquire()
        debug('processEnded THREAD ID: ' + str(thread.get_ident()) + ' (' + \
                  self.prettyCmd + ')' + ' (pid: ' + str(self.getPid()) + ')')
        self.finished.notify()
        self.finished.release()

        self.isRunning = False
        Topen.activePool.remove(self)

    def kill(self):
        from Hellanzb.Log import debug, error
        if isWindows():
            warn('Left running process: %s' % self.prettyCmd)
            return
        if self.isRunning:
            try:
                os.kill(self.getPid(), signal.SIGKILL)
            except OSError, ose:
                error('Unexpected problem while kill -9ing pid: ' + str(self.getPid()) + \
                      ' process: ' + self.prettyCmd, ose)
            except Exception, e:
                debug('could not kill process: ' + self.prettyCmd + ': ' + str(e))

        self.postProcessor.killed = True
                
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
        debug('spawnProcess THREAD ID: ' + str(thread.get_ident()) + ' (' + \
                  self.prettyCmd + ')')

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
        reactor.callFromThread(reactor.spawnProcess, self, self.cmd[0], self.cmd, os.environ,
                               usePTY = (not isWindows() and not isSolaris()) and 1 or 0)

        self.finished.wait()
        self.finished.release()

        # Here is where PostProcessor will typically die. After a process has been killed
        checkShutdown()

        # prepare the outbuffer (LAME)
        output = [line + '\n' for line in self.outBuf.getvalue().split('\n')]
        
        return output, self.returnCode

    def getPid(self):
        """ Return the pid of the process if it exists """
        if self.transport:
            return getattr(self.transport, 'pid', None)
        return None
    
    def killAll():
        """ kill -9 all active topens """
        for active in Topen.activePool:
            active.kill()
    killAll = staticmethod(killAll)

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

    def dequeueItems(self, items):
        """ Explicitly dequeue the specified items. Yes, this queue supports random access """
        succeded = items[:]
        self.mutex.acquire()
        for item in items:
            try:
                self.queue.remove(item)
            except ValueError:
                succeded.remove(item)

        heapify(self.queue)
        
        # python 2.3
        if not hasattr(self, 'not_empty') and not len(self.queue):
            self.esema.acquire()
        self.mutex.release()
        
        return succeded

class UnicodeList(list):
    """ Ensure all contained objects are casted to unicode. Allows Nones """
    def remove(self, value):
        super(UnicodeList, self).remove(toUnicode(value))
        
    def append(self, value):
        super(UnicodeList, self).append(toUnicode(value))

    def extend(self, iterable):
        super(UnicodeList, self).extend([toUnicode(value) for value in iterable])

    def insert(self, index, value):
        super(UnicodeList, self).insert(index, toUnicode(value))

def getLocalClassName(klass):
    """ Get the local name (no package/module information) of the specified class instance """
    klass = str(klass)
    
    lastDot = klass.rfind('.')
    if lastDot > -1:
        klass = klass[lastDot + 1:]
        
    return klass    
    
def assertIsExe(exe_list):
    """ Abort the program if none of the specified files are executable """
    if not isinstance(exe_list, (list, tuple)):
        exe_list = [exe_list]
    if exe_list:
        for exe in exe_list:
            if exe == os.path.basename(exe):
                try:
                    fullPath = spawn.find_executable(exe)
                except:
                    raise FatalError('Cannot continue program, your platform does not support searching the path for an executable and you did not supply the full path to the %s executable.' % exe)
            else:
                fullPath = exe
            if fullPath != None and os.access(fullPath, os.X_OK):
                return fullPath
    raise FatalError('Cannot continue program, required executable not found: \'' + \
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

NEWZBIN_FILE_PREFIX = r'^(?:(?:msgid|NZB)_)?(\d+)_(.*)'
NEWZBIN_FILE_SUFFIX = r'\.nzb$'
NEWZBIN_FILE_SUFFIX_RE = re.compile(r'\.nzb$', re.I)
NEWZBIN_FILE_RE = re.compile(NEWZBIN_FILE_PREFIX + NEWZBIN_FILE_SUFFIX, re.I)
def archiveName(dirName, unformatNewzbinNZB = True):
    """ Extract the name of the archive from the archive's absolute path, or its .nzb file
    name. Optionally remove newzbin 'msgid_99999' or 'NZB_' prefixes and the '.nzb' suffix
    from a newzbin formatted .nzb filename """
    from Hellanzb.PostProcessorUtil import DirName
    # pop off separator and basename
    while dirName[len(dirName) - 1] == os.sep:
        dirName = dirName[0:len(dirName) - 1]
    if isinstance(dirName, DirName) and dirName.isSubDir():
        name = os.path.basename(dirName.parentDir) + \
        normpath(dirName).replace(normpath(dirName.parentDir), '')
    else:
        name = os.path.basename(dirName)

    # Strip the msg_id and .nzb extension from an nzb file name
    if unformatNewzbinNZB:
        newzbinMatch = NEWZBIN_FILE_RE.match(name)
        if newzbinMatch:
            name = newzbinMatch.group(2)
        else:
            name = NEWZBIN_FILE_SUFFIX_RE.sub('', name)

    return name

def getMsgId(archiveName):
    """ Grab the msgid from a newzbin filename/archiveName """
    archiveName = os.path.basename(archiveName)
    match = NEWZBIN_FILE_RE.match(archiveName)
    if match:
        return match.group(1)
    return None

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
        Hellanzb.SERVERS[id][var] = args[var]

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
    """ Rename a dupe file to filename _hellanzb_renamedX, and return the renamed filename
    """
    if os.path.exists(filename):
        # Rename the dir if it exists already
        renamedPrefix = filename + RENAME_SUFFIX
        i = 0
        while os.path.exists(renamedPrefix + str(i)):
            i += 1
        renamed = renamedPrefix + str(i)
        move(filename, renamed)
        return renamed

DUPE_SUFFIX = '_hellanzb_dupe'
DUPE_SUFFIX_RE = re.compile('(.*)' + DUPE_SUFFIX + '(\d{1,4})$')
def cleanDupeName(filename):
    """ For the given duplicate filename, return a tuple containing the non-duplicate
    filename, and the duplicate filename index. Returns an index of -1 for non-duplicate
    filenames.

    e.g.:

    cleanDupeName('/test/file') would return:
    ('/test/file', -1)

    cleanDupeName('/test/file_hellanzb_dupe0') would return:
    ('/test/file', 0)
    """
    i = -1
    dupeMatch = DUPE_SUFFIX_RE.match(filename)
    
    # If this is a dupe name already, pull the DUPE_SUFFIX off
    if dupeMatch:
        filename = dupeMatch.group(1)
        i = int(dupeMatch.group(2))
    return filename, i
    
def _nextDupeName(filename):
    """ Return the next dupeName in the dupeName sequence """
    filename, i = cleanDupeName(filename)

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
    if (not checkOnDisk or not os.path.exists(filename)) and minIteration == 0 and \
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

def prettyElapsed(seconds):
    """ Return a pretty string representing the elapsed time in hours, minutes, seconds """
    def shiftTo(seconds, shiftToSeconds, shiftToLabel):
        """ Return a pretty string, shifting seconds to the specified unit of measure """
        prettyStr = '%i%s' % ((seconds / shiftToSeconds), shiftToLabel)
        mod = seconds % shiftToSeconds
        if mod != 0:
            prettyStr += ' %s' % prettyElapsed(mod)
        return prettyStr
    
    seconds = int(seconds)
    if seconds < 60:
        return '%is' % seconds
    elif seconds < 60 * 60:
        return shiftTo(seconds, 60, 'm')
    else:
        return shiftTo(seconds, 60 * 60, 'h')

def unPrettyBytes(prettyBytes):
    """ Convert a string representing a count in KB, MB, or GB to actual bytes as
    an integer """
    reStr = '^(\d+)%sB?$'
    res = {re.compile(reStr % 'K'): 2 ** 10,
               re.compile(reStr % 'M'): 2 ** 20,
               re.compile(reStr % 'G'): 2 ** 30}
               
    prettyBytes = str(prettyBytes).upper()
    for size_re, size in res.iteritems():
        if size_re.match(prettyBytes):
            return int(size_re.sub(r'\1', prettyBytes)) * size
    return int(prettyBytes)

def toUnicode(str):
    """ Convert the specified string to a unicode string """
    if str == None:
        return str
    elif not isinstance(str, unicode):
        # iso-8859-1 aka latin-1
        return unicode(str, 'iso-8859-1')
    return str

def tempFilename(prefix = 'hellanzb-tmp'):
    """ Return a temp filename, prefixed with 'hellanzb-tmp' """
    return prefix + str(randint(10000000, 99999999))

def prettySize(bytes):
    """ format a byte count for pretty display """
    bytes = float(bytes)
    
    if bytes < 1024:
            return '<1KB'
    elif bytes < (1024 * 1024):
            return '%dKB' % (bytes / 1024)
    else:
            return '%.1fMB' % (bytes / 1024.0 / 1024.0)

def nuke(filename):
    """ Delete the specified file on disk, ignoring any exceptions """
    try:
        os.remove(filename)
    except Exception, e:
        pass

def validNZB(nzbfilename):
    """ Return true if the specified filename is a valid NZB """
    from Hellanzb.Log import error
    if nzbfilename == None or not os.path.isfile(nzbfilename):
        error('Invalid NZB file: %s' % nzbfilename)
        return False
    elif not os.access(nzbfilename, os.R_OK):
        error('Unable to read NZB file: %s' % nzbfilename)
        return False
    elif archiveName(nzbfilename) == '':
        error('Invalid NZB file (No archive name): %s' % nzbfilename)
        return False
    return True

def ensureDirs(dirNames):
    """ Ensure the specified map of Hellanzb options to their required directory exist and are
    writable, otherwise attempt to create them. Raises a FatalError if any one of them
    cannot be created, or is not writable """
    # NOTE: this function is called prior to Logging is fully setup -- it CANNOT use the
    # logging system
    badPermDirs = []
    for arg, dirName in dirNames.iteritems():
        if not os.path.isdir(dirName):
            try:
                os.makedirs(dirName)
            except OSError, ose:
                raise FatalError('Unable to create directory for option: Hellanzb.' + \
                                 arg + ' dirName: ' + dirName + ' error: ' + str(ose))
        elif not os.access(dirName, os.W_OK):
            badPermDirs.append(dirName)

    if len(badPermDirs):
        dirTxt = 'directory'
        if len(badPermDirs) > 1:
            dirTxt = 'directories'
        err = 'Cannot continue: hellanzb needs write access to ' + dirTxt + ':'
        
        for dirName in badPermDirs:
            err += '\n' + dirName
            
        raise FatalError(err)

def uopen(filename, *args, **kwargs):
    """ Open a file. Unicode filenames are specially handled on certain platforms (OS X) """
    if Hellanzb.SYSNAME == "Darwin":
        filename = toUnicode(filename)
    return open(filename, *args, **kwargs)

def isHellaTemp(filename):
    """ Determine whether or not the specified file is a 'hellanzb-tmp-' file """
    return filename.find('hellanzb-tmp-') == 0

def find_packager():
    """ Detect packaging systems such as py2app and py2exe """
    frozen = getattr(sys, 'frozen', None)
    if not frozen:
        # COULD be certain cx_Freeze options or bundlebuilder, nothing to worry about though
        return None
    elif frozen in ('dll', 'console_exe', 'windows_exe'):
        return 'py2exe'
    elif frozen in ('macosx_app',):
        return 'py2app'
    elif frozen is True:
        # it doesn't ALWAYS set this
        return 'cx_Freeze'
    else:
        return '<unknown packager: %r>' % (frozen,)

def isPy2App():
    """ Whether or not this process is running via py2app """
    try:
        return Hellanzb.PACKAGER == 'py2app'
    except AttributeError:
        return find_packager() == 'py2app'

def isWindows():
    """ Whether or not this process is running in Windows (not cygwin) """
    return sys.platform.startswith('win')

def isSolaris():
    """ Whether or not this process is running in Solaris """
    return sys.platform.startswith('sunos')

ONE_MB = float(1024*3)
try:
    import statvfs
    def diskFree(dirName):
        """ Return the disk free space for the specified dir's volume, in MB """
        try:
            s = os.statvfs(dirName)
            return (s[statvfs.F_BFREE] * s[statvfs.F_FRSIZE]) / ONE_MB
        except OSError:
            return 0.0

except AttributeError:
    try:
        import win32api
    except ImportError:
        pass
    def diskFree(dirName):
        """ Return the disk free space for the specified dir's volume, in MB """
        try:
            secp, byteper, freecl, noclu = win32api.GetDiskFreeSpace(dirName)
            return (secp * byteper * freecl) / ONE_MB
        except:
            return 0.0

Hellanzb.CMHELLA = \
'''
           ;;;;            .  .
      ... :liil ...........:..:      ,._    ,._      ...................
      :   l$$$:  _.,._       _..,,._ "$$$b. "$$$b.   `_..,,._        :::
      :   $$$$.d$$$$$$L   .d$$$$$$$$L $$$$:  $$$$: .d$$$$$$$$$;      :::
      :  :$$$$P`  T$$$$: :$$$$`  7$$F:$$$$  :$$$$ :$$$$: `$$$$ __  _  |_
      :  l$$$F   :$$$$$  8$$$l"""""` l$$$l  l$$$l l$$$l   $$$L | ) /_ |_)
      :  $$$$:   l$$$$$L `4$$$bcmang;ACID$::$$$88:`4$$$bmm$$$$;.     ...
      :    ```      ```""              ```    ```    .    ```.     ..:::..
      :..............................................:              `:::`
                                                                      `
'''

Hellanzb.CMHELLA_VERSIONED = \
'''
           ;;;;            .  .
      ... :liil ...........:..:      ,._    ,._      ...................
      :   l$$$:  _.,._       _..,,._ "$$$b. "$$$b.   `_..,,._        :::
      :   $$$$.d$$$$$$L   .d$$$$$$$$L $$$$:  $$$$: .d$$$$$$$$$;      :::
      :  :$$$$P`  T$$$$: :$$$$`  7$$F:$$$$  :$$$$ :$$$$: `$$$$ __  _  |_
      :  l$$$F   :$$$$$  8$$$l"""""` l$$$l  l$$$l l$$$l   $$$L | ) /_ |_)
      :  $$$$:   l$$$$$L `4$$$bcmang;ACID$::$$$88:`4$$$bmm$$$$;.     ...
      :    ```      ```""              ```    ```    .    ```.     ..:::..
      :..............................................:   %s  `:::`
                                                                      `
'''
def cmVersion(version = Hellanzb.version):
    """ try to make Hellanzb.version always look like this: 'V 1 . 0' """
    #cmV = '  V 1 . 0'
    version = version.replace('-trunk', '')
    muck = lambda v : 'v' + v.replace('', ' ').rstrip()
    if len(version) == len('0.10') and version.startswith('0.'):
        version = muck(version)
    elif len(version) == len('1.0'):
        version = muck(version)
        version = ' %s ' % version
    return version

def cmHella(version = Hellanzb.version):
    """ brand the ascii with a properly formatted version number """
    return Hellanzb.CMHELLA_VERSIONED % (cmVersion(version))

def daemonize():
    """ From twisted's twisted.scripts.twistd """
    # See http://www.erlenstar.demon.co.uk/unix/faq_toc.html#TOC16
    if os.fork():   # launch child and...
        os._exit(0) # kill off parent
    os.setsid()
    if os.fork():   # launch child and...
        os._exit(0) # kill off parent again.
    os.umask(077)
    null=os.open('/dev/null', os.O_RDWR)
    for i in range(3):
        try:
            os.dup2(null, i)
        except OSError, e:
            if e.errno != errno.EBADF:
                raise
    os.close(null)

"""
Copyright (c) 2005 Philip Jenvey <pjenvey@groovie.org>
                   Ben Bangert <bbangert@groovie.org>
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
