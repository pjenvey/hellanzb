"""

Core - All of our main()ish functions. Initialization/shutdown/etc

(c) Copyright 2005 Philip Jenvey, Ben Bangert
[See end of file]
"""
# Install our custom twisted reactor immediately
import twisted.internet.abstract
twisted.internet.abstract.FileDescriptor.bufferSize = 4096

from Hellanzb.HellaReactor import HellaReactor
HellaReactor.install()

import optparse, os, signal, sys, thread, threading, Hellanzb, Hellanzb.PostProcessor
from distutils import spawn
from threading import Lock
from twisted.internet import reactor
from Hellanzb.Daemon import initDaemon
from Hellanzb.Log import *
from Hellanzb.Logging import initLogging, stdinEchoOn
from Hellanzb.PostProcessorUtil import defineMusicType
from Hellanzb.Util import *

__id__ = '$Id$'

def findAndLoadConfig(optionalConfigFile = None):
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
        
        # Cache this operation (whether or not we're in debug mode) for faster (hardly)
        # debug spamming (from NZBLeecher)
        Hellanzb.DEBUG_MODE_ENABLED = False
        if hasattr(Hellanzb, 'DEBUG_MODE') and Hellanzb.DEBUG_MODE != None and \
                Hellanzb.DEBUG_MODE != False:
            Hellanzb.DEBUG_MODE_ENABLED = True
            
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

        # If there aren't any proceses to wait for exit immediately
        if len(popen2._active) == 0:
            logShutdown('Caught interrupt, exiting..')
            shutdownNow(Hellanzb.SHUTDOWN_CODE)

        # The idea here is to 'cheat' again to exit the program ASAP if all the processes
        # are associated with the main thread (the processes would have already gotten the
        # signal. I'm not exactly sure why)
        threadsOutsideMain = False
        for ptyopen in popen2._active:
            # signal guarantees us to be within the main thread
            if ptyopen.thread != threading.currentThread():
                # FIXME: only Ptyopen has a popen.thread. And Do I need to bother to look
                # at this _active list? since everything is Ptyopen now
                threadsOutsideMain = True

        if not threadsOutsideMain:
            logShutdown('Caught interrupt, exiting..')
            shutdownNow(Hellanzb.SHUTDOWN_CODE)

        # We couldn't cheat our way out of the program, tell the user the processes
        # (threads) we're waiting on, and wait for another signal
        if not 'stopSignalCount' in dir(Hellanzb):
            # NOTE: initiazing this HERE means we'll run through the above block of code
            # after the second signal. this is preferable because it gives quicker
            # feedback after the CTRL-C, and all the threads might have gone away right
            # before/after the second CTRL-C
            Hellanzb.stopSignalCount = 0
            info('Caught interrupt, exiting..')

        Hellanzb.stopSignalCount = Hellanzb.stopSignalCount + 1

        if Hellanzb.stopSignalCount < 2:
            msg = 'Caught CTRL-C, waiting for the child processes to finish:\n'
            for ptyopen in popen2._active:
                msg += ' '*4 + ptyopen.prettyCmd + '\n'
            msg += '(Press CTRL-C again to kill them and exit immediately)..'
            warn(msg)
            
        else:
            # Simply kill anything. If any processes are lying around after a kill -9,
            # it's either an o/s problem (we don't care) or a bug in hellanzb (we aren't
            # allowing the process to exit/still reading from it)
            warn('Killing child processes (wait a second..)')
            for ptyopen in popen2._active:
                try:
                    os.kill(ptyopen.pid, signal.SIGKILL)
                except OSError, ose:
                    logShutdown('Unexpected problem while kill -9ing process' + ptyopen.cmd, ose)

            logShutdown('Killed child processes, exiting..')
            shutdownNow(Hellanzb.SHUTDOWN_CODE)

def init(options = {}):
    """ initialize the app """
    # Whether or not the app is in the process of shutting down
    Hellanzb.shutdown = False

    # we can compare the current thread's ident to our MAIN_THREAD's to determine whether
    # or not we may need to route things through twisted's callFromThread
    Hellanzb.MAIN_THREAD_IDENT = thread.get_ident()

    # Get logging going ASAP
    initLogging()

    # FIXME: ?
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

    # One and only signal handler
    signal.signal(signal.SIGINT, signalHandler)

    if hasattr(options, 'configFile'):
        findAndLoadConfig(options.configFile)
    else:
        findAndLoadConfig()
        
    if hasattr(options, 'logFile'):
        Hellanzb.Logging.initLogFile(options.logFile)
    else:
        Hellanzb.Logging.initLogFile()

def shutdown():
    """ turn the knob that tells all parts of the program we're shutting down """
    # that knob, that threads will constantly check
    Hellanzb.shutdown = True

    # stop the twisted reactor
    reactor.callLater(0, reactor.stop)

    # Just in case we left it off
    stdinEchoOn()
    
def shutdownNow(returnCode = 0):
    """ shutdown the program ASAP """
    shutdown()

    sys.exit(returnCode)

def parseArgs():
    """ Parse the command line args """
    parser = optparse.OptionParser(version = Hellanzb.version)
    parser.add_option('-c', '--config', type='string', dest='configFile',
                      help='specify the configuration file')
    parser.add_option('-l', '--log-file', type='string', dest='logFile',
                      help='specify the log file (overwrites the config file setting)')
    # FIXME: TODO
    #parser.add_option('-d', '--debug-file', type='string', dest='debugFile',
    #                  help='specify the debug log file (overwrites the DEUBG_MODE config file setting)')
    parser.add_option('-p', '--post-process-dir', type='string', dest='postProcessDir',
                      help='don\'t run the daemon: post-process the specified nzb archive dir and exit')
    parser.add_option('-P', '--rar-password', type='string', dest='rarPassword',
                      help='when used with the -p option, specifies the nzb archive\'s rar password')
    return parser.parse_args()

def processArgs(options):
    """ By default run the daemon, otherwise process the specified dir and exit """
    if options.postProcessDir:
        if not os.path.isdir(options.postProcessDir):
            error('Unable to process, not a directory: ' + options.postProcessDir)
            shutdownNow(1)

        if not os.access(options.postProcessDir, os.R_OK):
            error('Unable to process, no read access to directory: ' + options.postProcessDir)
            shutdownNow(1)

        rarPassword = None
        if options.rarPassword:
            rarPassword = options.rarPassword
            
        troll = Hellanzb.PostProcessor.PostProcessor(options.postProcessDir, background = False,
                                                     rarPassword = rarPassword)
        info('\nStarting post processor')
        troll.start()
        troll.join()
        shutdownNow()
    
    else:
        info('\nStarting queue daemon')
        initDaemon()

def main():
    """ Program main loop. Always called from the main thread """
    options, args = parseArgs()

    try:
        init(options)
    
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

    processArgs(options)

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
