"""
Util - hellanzb misc functions

"""
import os, popen2, pty, string, sys, thread, threading, time, xmlrpclib, Hellanzb, StringIO
from distutils import spawn
from threading import RLock, Thread
from Logging import *

__id__ = '$Id$'

class FatalError(Exception):
    """ An error that will cause the program to exit """
    def __init__(self, message):
        self.args = [message]
        self.message = message

class Ptyopen(popen2.Popen3):
    def __init__(self, cmd, capturestderr=False, bufsize=-1):
        """ Popen3 class (isn't this actually Popen4, capturestderr = False?) that uses ptys
instead of pipes, to allow inline reading (instead of potential i/o buffering) of output
from the child process. It also stores the cmd it's running (as a string) and the thread
that created the object, for later use """
        # NOTE: this is all stolen from Popen minus the openpty calls
        popen2._cleanup()
        self.cmd = cmd
        self.thread = threading.currentThread()
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
        popen2._active.append(self)

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
    if len(name) > 3 and name[-3:].lower == 'nzb':
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
