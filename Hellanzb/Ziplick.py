"""
Module: ziplick.py
Author: Ben Bangert, Phil Jenvey
Date: 9/26/04

version 0.2

# TODO: the queue daemon should also monitor files in the final directory, for those that
# require a rar password. when a password is found it will recall Troll to finish
# extracting
"""

import Hellanzb, os, re, PostProcessor
from shutil import move
from time import sleep
from Logging import *
from Util import *

__id__ = '$Id$'

class Ziplick:

    def __init__(self):
        self.ensureDirs()

    def ensureDirs(self):
        """ Ensure that all the required directories exist, otherwise attempt to create them """
        for arg in dir(Hellanzb):
            if stringEndsWith(arg, "_DIR") and arg == arg.upper():
                exec 'dir = Hellanzb.' + arg
                if not os.path.isdir(dir):
                    try:
                        os.mkdir(dir)
                    except IOError:
                        raise FatalError("Unable to create Hellanzb DIRs")

    def run(self):
        self.queued_nzbs = []
        self.current_nzbs = [x for x in os.listdir(Hellanzb.CURRENT_DIR) if re.search(r'\.nzb$',x)]

        # Intermittently check if the app is in the process of shutting down when it's
        # safe (in between long processes)
        checkShutdown()
        
        info('hellanzb - Now monitoring queue...')
        growlNotify('Queue', 'hellanzb', 'Now monitoring queue..', False)
        while 1 and not checkShutdown():
            # See if we're resuming a nzb fetch
            if not self.current_nzbs:
                
                # Refresh our queue and append the new nzb's, 
                new_nzbs = [x for x in os.listdir(Hellanzb.QUEUE_DIR) \
                            if x not in self.queued_nzbs and re.search(r'\.nzb$',x)]

                if len(new_nzbs) > 0:
                    self.queued_nzbs.extend(new_nzbs)
                    self.queued_nzbs.sort()
                    for nzb in new_nzbs:
                        msg = 'Found new nzb:'
                        info(msg + archiveName(nzb))
                        growlNotify('Queue', 'hellanzb ' + msg,archiveName(nzb), False)
                
                # Nothing to do, lets wait 5 seconds and start over
                if not self.queued_nzbs:
                    sleep(5)
                    continue
                
                nzbfilename = self.queued_nzbs[0]
                del self.queued_nzbs[0]
                
                # Fix the filename
                # NOTE: this shouldn't be necessary with Ptyopen
                #newname = re.sub(r'[\[|\]|\(|\)]',r'',nzbfilename)
                #os.rename(Hellanzb.QUEUE_DIR+nzbfilename,Hellanzb.QUEUE_DIR+newname)
                
                move(Hellanzb.QUEUE_DIR+nzbfilename,Hellanzb.QUEUE_DIR+nzbfilename)
                
                # nzbfile will always be a absolute filename 
                nzbfile = Hellanzb.QUEUE_DIR + nzbfilename
                os.spawnlp(os.P_WAIT, 'mv', 'mv', nzbfile, Hellanzb.CURRENT_DIR)
            else:
                nzbfilename = self.current_nzbs[0]
                info('Resuming: ' + archiveName(nzbfilename))
                growlNotify('Queue', 'hellanzb Resuming:', archiveName(nzbfilename), False)
                del self.current_nzbs[0]
            nzbfile = Hellanzb.CURRENT_DIR + nzbfilename

            # Run nzbget. Pipe it's output through the logging system via the special
            # scroll level
            p = Ptyopen(['nzbget', nzbfile]) # Passing Ptyopen a list tells it to run the
                                             # process directly, instead of through
                                             # /bin/sh
            # no input
            p.tochild.close()

            scrollBegin()
            while True:
                try:
                    line = p.fromchild.readline()
                    if line == '': # EOF
                        break
                    line = line.rstrip()
                    scroll(line)
                except Exception, e:
                    pass
            p.fromchild.close()
            statusCode = p.wait()
            nzbgetReturnCode = os.WEXITSTATUS(statusCode)
            scrollEnd()
            
            checkShutdown()
            
            # Make our new directory, minus the .nzb
            newdir = Hellanzb.DEST_DIR + archiveName(nzbfilename)
                        
            # Grab the message id, we'll store it in the newdir for later use
            msgId = re.sub(r'.*msgid_', r'', nzbfilename)
            msgId = re.sub(r'_.*', r'', msgId)

            # Take care of the unfortunate case that we coredumped
            coreFucked = False
            if os.WCOREDUMP(statusCode):
                coreFucked = True
                newdir = newdir + '_corefucked'
                error('Archive: ' + archiveName(nzbfilename) + ' is core fucked :(')
                growlNotify('Error', 'hellanzb Archive is core fucked',
                            archiveName(nzbfilename) + '\n:(', True)
                
            # Move our nzb contents to their new location, clear out the temp dir
            if os.path.exists(newdir):
                # Rename the dir if it exists already
                renamedDir = newdir + '_hellanzb_renamed'
                i = 0
                while os.path.exists(renamedDir + str(i)):
                    i = i + 1
                move(newdir, renamedDir + str(i))
                
            move(Hellanzb.WORKING_DIR,newdir)
            touch(newdir + os.sep + '.msgid_' + msgId)
            move(nzbfile, newdir)
            os.mkdir(Hellanzb.WORKING_DIR)

            # FIXME: if this ctrl-c is caught we will never bother Trolling the newdir. If
            # we were signaled after the last shutdown check, we would have wanted the
            # previous code block to have completed. But we definitely don't want to
            # proceed to processing
            
            # Finally unarchive/process the directory in another thread, and continue
            # nzbing
            if not coreFucked and not checkShutdown():
                troll = PostProcessor.PostProcessor(newdir)
                troll.start()
