"""
Module: ziplick.py
Author: Ben Bangert, Phil Jenvey
Date: 9/26/04

version 0.2

# TODO: the queue daemon should also monitor files in the final directory, for those that
# require a rar password. when a password is found it will recall Troll to finish
# extracting
"""

import Hellanzb, os, re, PostProcessor, asyncore
from shutil import move
from time import sleep
from twisted.internet import reactor
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
        """ """
        reactor.callLater(0, info, 'hellanzb - Now monitoring queue...')
        reactor.callLater(0, growlNotify, 'Queue', 'hellanzb', 'Now monitoring queue..', False)
        reactor.callLater(0, self.scanQueueDir)
        from Hellanzb.NewzSlurp.NewzSlurper import initNewzSlurp
        initNewzSlurp()

    def scanQueueDir(self):
        """ Find new/resume old NZB download sessions """
        self.queued_nzbs = []
        self.current_nzbs = [x for x in os.listdir(Hellanzb.CURRENT_DIR) if re.search(r'\.nzb$',x)]

        debug('Ziplick scanning queue dir..')

        # Intermittently check if the app is in the process of shutting down when it's
        # safe (in between long processes)
        checkShutdown()
        
        #while 1 and not checkShutdown():
        if not checkShutdown():
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
                    #sleep(5)
                    #continue
                    # FIXME: callLater
                    reactor.callLater(5, self.scanQueueDir)
                    return
                
                nzbfilename = self.queued_nzbs[0]
                del self.queued_nzbs[0]
                
                # nzbfile will always be a absolute filename 
                nzbfile = Hellanzb.QUEUE_DIR + nzbfilename
                #os.spawnlp(os.P_WAIT, 'mv', 'mv', nzbfile, Hellanzb.CURRENT_DIR)
                move(nzbfile, Hellanzb.CURRENT_DIR)
            else:
                nzbfilename = self.current_nzbs[0]
                info('Resuming: ' + archiveName(nzbfilename))
                growlNotify('Queue', 'hellanzb Resuming:', archiveName(nzbfilename), False)
                del self.current_nzbs[0]
            nzbfile = Hellanzb.CURRENT_DIR + nzbfilename

            # Change the cwd for Newsleecher, and download the files
            # FIXME: scroll stuff is broken. Needs to be rethought now that we control the
            # nzb getter
            #oldDir = os.getcwd()
            os.chdir(Hellanzb.WORKING_DIR)

            # The scroll level will flood the console with constantly updating statistics
            # -- the logging system can interrupt this scroll temporarily (after
            # scrollBegin)
            scrollBegin()

            # Parse the NZB file into the Queue. Unless the NZB file is deemed already
            # fully processed at the end of parseNZB, tell the factory to start
            # downloading it
            if not Hellanzb.queue.parseNZB(nzbfile):
                Hellanzb.nsf.fetchNextNZBSegment()

    def handleNZBDone(self, nzbfilename):
        """ Hand-off from the downloader -- make a dir for the NZB with it's contents, then post
        process it in a separate thread"""
        # Back to normal logging behavior
        scrollEnd()

        # Append \n
        info('')

        checkShutdown()
        
        # Make our new directory, minus the .nzb
        newdir = Hellanzb.DEST_DIR + archiveName(nzbfilename)
                    
        # Grab the message id, we'll store it in the newdir for later use
        msgId = re.sub(r'.*msgid_', r'', nzbfilename)
        msgId = re.sub(r'_.*', r'', msgId)

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
        nzbfile = Hellanzb.CURRENT_DIR + os.path.basename(nzbfilename)
        move(nzbfile, newdir)
        os.mkdir(Hellanzb.WORKING_DIR)

        # FIXME: if this ctrl-c is caught we will never bother Trolling the newdir. If
        # we were signaled after the last shutdown check, we would have wanted the
        # previous code block to have completed. But we definitely don't want to
        # proceed to processing
        
        # Finally unarchive/process the directory in another thread, and continue
        # nzbing
        if not checkShutdown():
            troll = PostProcessor.PostProcessor(newdir)
            troll.start()

        reactor.callLater(0, self.scanQueueDir)
