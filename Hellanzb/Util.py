"""
Util - hellanzb misc functions

"""
import Hellanzb, os, string, sys, xmlrpclib
from distutils import spawn

__id__ = '$Id$'

class FatalError(Exception):
    """ An error that will cause the program to exit """
    def __init__(self, message):
        self.message = message

def warn(message):
    """ Log a message at the warning level """
    sys.stderr.write('Warning: ' + message + '\n')

def error(message):
    """ Log a message at the error level """
    sys.stderr.write('Error: ' + message + '\n')

def info(message):
    """ Log a message at the info level """
    print message

def debug(message):
    if Hellanzb.DEBUG_MODE:
        print message

def assertIsExe(exe):
    """ Abort the program if the specified file is not in our PATH and executable """
    if len(exe) > 0:
        exe = exe.split()[0]
        if spawn.find_executable(exe) == None or os.access(exe, os.X_OK):
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

def growlNotify(type, title, description, sticky):
    """ send a message to the growl daemon via an xmlrpc proxy """
    # FIXME: should validate the server information on startup, and catch connection
    # refused errors here
    if not Hellanzb.ENABLE_GROWL_NOTIFY:
        return

    # NOTE: we probably want this in it's own thread to be safe, i can see this easily
    # deadlocking for a bit on say gethostbyname()
    # AND we could have a LOCAL_GROWL option for those who might run hellanzb on os x
    serverUrl = 'http://' + Hellanzb.SERVER + '/'
    server = xmlrpclib.Server(serverUrl)

    # If for some reason, the XMLRPC server ain't there no more, this will blow up
    # so we put it in a try/except block
    try:
        server.notify(type, title, description, sticky)
    except:
        return

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
