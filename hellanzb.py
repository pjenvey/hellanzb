#!/usr/bin/env python
"""
hellanzb - hella nzb

TODO:
o skip downloading par2 files unless they're needed:
  need a small SAX parser to:
   if a 'file' element, and it's attribute 'subject' contains PAR2 (case insensitive),
   set withinPar to true.
   
   if ending a file element, set withinPar to false

   if withinPar, write to nzbfile_JUST_PARS.nzb
   else write to nzbfile_WITHOUT_PARS.nzb
   
   obviously both those files need the correct headers/footers too.

o (troll) More work on passwords. Ideally troll should be able to determine some common rar
archive passwords on it's own

@author pjenvey, bbangert

"""

import optparse, os, signal, sys, threading, Hellanzb, Hellanzb.PostProcessor, Hellanzb.Ziplick
from distutils import spawn
from threading import Lock
from Hellanzb.Logging import *
from Hellanzb.PostProcessorUtil import defineMusicType
from Hellanzb.Util import *

__id__ = '$Id$'

def findAndLoadConfig(optionalConfigFile):
    """ Load the configuration file """
    if optionalConfigFile != None:
        if loadConfig(optionalConfigFile):
            return
        else:
            error('Unable to load specified config file: ' + optionalConfigFile)
            sys.exit(1)

    # look for conf in this order: sys.prefix, ./, or ./etc/
    confDirs = [ sys.prefix + os.sep + 'etc', os.getcwd() + os.sep + 'etc', os.getcwd() ]

    # hard coding preferred Darwin config file location, kind of lame. but I'd rather do
    # this then make an etc dir in os x's Python.framework directory
    (sysname, nodename, release, version, machine) = os.uname()
    if sysname == "Darwin":
        confDirs[0] = '/opt/local/etc'

    foundConfig = False
    for dir in confDirs:
        file = dir + os.sep + 'hellanzb.conf'
        
        if loadConfig(file):
            return
        
    error('Could not find configuration file in the following dirs: ' + str(confDirs))
    sys.exit(1)
    
def loadConfig(fileName):
    """ Attempt to load the specified config file"""
    if not os.path.isfile(fileName):
        return False

    if not os.access(fileName, os.R_OK):
        warn('Unable to read config file: ' + fileName)
        return False

    try:        
        execfile(fileName)
        debug('Found config file in directory: ' + os.path.dirname(fileName))
        return True
    
    except FatalError, fe:
        error('A problem occurred while reading the config file', fe)
        raise
    except Exception, e:
        msg = 'An unexpected error occurred while reading the config file'
        error(msg, e)
        raise

def signalHandler(signum, frame):
    """ The main and only signal handler. Handle cleanup/managing child processes before
exiting """

    # CTRL-C
    if signum == signal.SIGINT:
        # lazily notify everyone they should stop immediately
        Hellanzb.shutdown = True
        
        info('Caught interrupt, exiting..')
        # we expect immediate gratification from a CTRL-C
        sys.stdout.flush()

        # If there aren't any proceses to wait for exit immediately
        if len(popen2._active) == 0:
            shutdownNow(Hellanzb.SHUTDOWN_CODE)

        # The idea here is to 'cheat' again to exit the program ASAP if all the processes
        # are associated with the main thread (the processes would have already gotten the
        # signal. I'm not exactly sure why)
        threadsOutsideMain = False
        for popen in popen2._active:
            # signal guarantees us to be within the main thread
            if popen.thread != threading.currentThread():
                # FIXME: only Ptyopen has a popen.thread. And Do I need to bother to look
                # at this _active list? since everything is Ptyopen now
                threadsOutsideMain = True

        if not threadsOutsideMain:
            shutdownNow(Hellanzb.SHUTDOWN_CODE)

        # We couldn't cheat our way out of the program, tell the user the processes
        # (threads) we're waiting on, and wait for another signal
        if not 'stopSignalCount' in dir(Hellanzb):
            # NOTE: initiazing this HERE means we'll run through the above block of code
            # after the second signal. this is preferable because it gives quicker
            # feedback after the CTRL-C, and all the threads might have gone away right
            # before/after the second CTRL-C
            Hellanzb.stopSignalCount = 0

        Hellanzb.stopSignalCount = Hellanzb.stopSignalCount + 1

        if Hellanzb.stopSignalCount < 2:
            msg = 'Caught CTRL-C, waiting for the child processes to finish:\n'
            for popen in popen2._active:
                msg += ' '*4 + popen.cmd + '\n'
            msg += '(Press CTRL-C again to kill them and exit immediately)..'
            warn(msg)
            sys.stdout.flush()
            
        else:
            # Simply kill anything. If any processes are lying around after a kill -9,
            # it's either an o/s problem (we don't care) or a bug in hellanzb (we aren't
            # allowing the process to exit/still reading from it)
            warn('Killing children (wait a second..)')
            for popen in popen2._active:
                try:
                    os.kill(popen.pid, signal.SIGKILL)
                except OSError, ose:
                    error('Unexpected problem while kill -9ing process' + popen.cmd, ose)

            shutdownNow(Hellanzb.SHUTDOWN_CODE)

def init(options):
    """ initialize the app """
    Hellanzb.SHUTDOWN_CODE = 20

    Hellanzb.SERVERS = {}

    # Troll threads
    Hellanzb.postProcessors = []
    Hellanzb.postProcessorLock = Lock()

    # doppelganger
    for exe in [ 'rar', 'unrar' ]:
        if spawn.find_executable(exe):
            Hellanzb.UNRAR_CMD = exe
    assertIsExe(Hellanzb.UNRAR_CMD)

    # FIXME: cruft
    Hellanzb.Newsleecher.INCOMPLETE_THRESHOLD = 90

    # FIXME
    Hellanzb.NEWSLEECHER_IS_BUGGY = False

    # One and only signal handler
    signal.signal(signal.SIGINT, signalHandler)

    findAndLoadConfig(options.configFile)

    Hellanzb.Logging.initLogFile(options.logFile)

def shutdown():
    """ turn the knob that tells all parts of the program we're shutting down """
    Hellanzb.shutdown = True

    # wakeup the doofus scroll interrupter thread (to die) if it's waiting
    ScrollInterrupter.pendingMonitor.acquire()
    ScrollInterrupter.pendingMonitor.notify()
    ScrollInterrupter.pendingMonitor.release()
    
def shutdownNow(returnCode = 0):
    """ shutdown the program ASAP """
    shutdown()

    sys.exit(returnCode)
    
if __name__ == '__main__':

    parser = optparse.OptionParser(version = Hellanzb.version)
    parser.add_option('-c', '--config', type='string', dest='configFile',
                      help='specify the configuration file')
    parser.add_option('-l', '--log-file', type='string', dest='logFile',
                      help='specify the log file (overwrites the config file setting)')
    # run troll as a cmd line app
    parser.add_option('-p', '--post-process-dir', type='string', dest='postProcessDir',
                      help='don\'t run the daemon: post-process the specified dir and exit')
    options, args = parser.parse_args()

    # Whether or not the app is in the process of shutting down
    Hellanzb.shutdown = False
    
    Hellanzb.Logging.init()

    try:
        init(options)
    
        # By default run the daemon, otherwise process the specified dir and exit
        if options.postProcessDir:
            if not os.path.isdir(options.postProcessDir):
                error('Unable to process, not a directory: ' + options.postProcessDir)
                shutdownNow(1)

            if not os.access(options.postProcessDir, os.R_OK):
                error('Unable to process, no read access to directory: ' + options.postProcessDir)
                shutdownNow(1)
                
            troll = Hellanzb.PostProcessor.PostProcessor(options.postProcessDir, background = False)
            info('\nStarting post processor')
            troll.start()
            troll.join()
            shutdownNow()
        
        else:
            info('\nStarting queue daemon')
            daemon = Hellanzb.Ziplick.Ziplick()
            daemon.run()

    except SystemExit, se:
        # sys.exit throws this, let it go
        raise
    except FatalError, fe:
        error('Exiting', fe)
        shutdownNow(1)
    except Exception, e:
        error('An unexpected problem occurred, exiting', e)
        shutdown()
        raise
