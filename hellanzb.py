#!/usr/bin/env python
"""
hellanzb - hella nzb

TODO:
o better signal handling (especially re the threads -- they ignore ctrl-c)
  # module-thread.html says:
  # Caveats:
  # Threads interact strangely with interrupts: the KeyboardInterrupt exception will be
  # received by an arbitrary thread. (When the signal module is available, interrupts
  # always go to the main thread.)
OR threads have a daemon mode, utilize this

@author pjenvey, bbangert

"""

import optparse, os, sys, Hellanzb, Hellanzb.Troll, Hellanzb.Ziplick
from Hellanzb.Util import *
from Hellanzb.Troll import defineMusicType

__id__ = '$Id$'

def usage():
    pass

def findAndLoadConfig(optionalConfigFile):
    """ Load the configuration file """
    confDirs = [ sys.prefix + os.sep + 'etc', os.getcwd() + os.sep + 'etc', os.getcwd() ]

    if optionalConfigFile != None:
        if loadConfig(optionalConfigFile):
            return
        else:
            error('Unable to load specified config file: ' + optionalConfigFile)
            sys.exit(1)
    
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
    
    except:
        error('An unexpected error occurred file reading the config file:')
        raise

def runDaemon():
    """ start the daemon """
    daemon = Hellanzb.Ziplick.Ziplick()

    daemon.start()

def runTroll(archiveDir):
    """ run troll as a cmd line app """
    try:
        Hellanzb.Troll.init()
        Hellanzb.Troll.troll(archiveDir)

    except FatalError, fe:
        Hellanzb.Troll.cleanUp(archiveDir)
        error('An unexpected problem occurred: ' + fe.message)
        sys.exit(1)

    except:
        Hellanzb.Troll.cleanUp(archiveDir)
        error('An unexpected problem occurred!')
        raise
    
if __name__ == '__main__':
    
    parser = optparse.OptionParser()
    parser.add_option('-c', '--config', type='string', dest='configFile',
                      help='specify the configuration file')
    parser.add_option('-p', '--process-dir', type='string', dest='processDir',
                      help='don\'t run the daemon: process the specified dir and exit')
    options, args = parser.parse_args()

    findAndLoadConfig(options.configFile)

    # By default run the daemon, otherwise process the specified dir and exit
    if options.processDir:
        if not os.path.isdir(options.processDir):
            error('Unable to process, not a directory: ' + options.processDir)
            sys.exit(1)

        if not os.access(options.processDir, os.R_OK):
            error('Unable to process, no read access to directory: ' + options.processDir)
            sys.exit(1)
            
        runTroll(options.processDir)
        
    else:
        runDaemon()
