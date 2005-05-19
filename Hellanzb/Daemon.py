"""

Daemon (aka Ziplick) - Filesystem queue daemon functions. They're all called from inside
the twisted reactor loop, except for initialization functions

(c) Copyright 2005 Ben Bangert, Philip Jenvey
[See end of file]
"""
import Hellanzb, os, re, PostProcessor
from shutil import move
from twisted.internet import reactor
from Hellanzb.Log import *
from Hellanzb.Logging import prettyException
from Hellanzb.Util import *

__id__ = '$Id$'

def ensureDaemonDirs():
    """ Ensure that all the required directories exist, otherwise attempt to create them """
    for arg in dir(Hellanzb):
        if stringEndsWith(arg, "_DIR") and arg == arg.upper():
            exec 'dirName = Hellanzb.' + arg
            if not os.path.isdir(dirName):
                try:
                    os.makedirs(dirName)
                except OSError, ose:
                    # FIXME: this isn't caught -- it's not a clean way to exit the program
                    raise FatalError('Unable to create directory for option: Hellanzb.' + \
                                     arg + ' dirName: ' + dirName + ' error: ' + str(ose))
def initDaemon():
    """ Start the daemon """
    ensureDaemonDirs()

    reactor.callLater(0, info, 'hellanzb - Now monitoring queue...')
    reactor.callLater(0, growlNotify, 'Queue', 'hellanzb', 'Now monitoring queue..', False)
    reactor.callLater(0, scanQueueDir)

    #if hasattr(Hellanzb, 'BACKDOOR') and Hellanzb.BACKDOOR == True:
    if True:
        from backdoor import serve
        from thread import start_new_thread
        reactor.callLater(0, start_new_thread, serve, ())

    Hellanzb.queued_nzbs = []

    from Hellanzb.NZBLeecher import initNZBLeecher
    initNZBLeecher()
    
def scanQueueDir():
    """ Find new/resume old NZB download sessions """
    debug('Ziplick scanning queue dir..')

    current_nzbs = [x for x in os.listdir(Hellanzb.CURRENT_DIR) if re.search(r'\.nzb$',x)]

    # Intermittently check if the app is in the process of shutting down when it's
    # safe (in between long processes)
    checkShutdown()
    
    # See if we're resuming a nzb fetch
    resuming = False
    if not current_nzbs:
        # Refresh our queue and append the new nzb's, 
        new_nzbs = [x for x in os.listdir(Hellanzb.QUEUE_DIR) \
                    if x not in Hellanzb.queued_nzbs and re.search(r'\.nzb$',x)]

        if len(new_nzbs) > 0:
            Hellanzb.queued_nzbs.extend(new_nzbs)
            Hellanzb.queued_nzbs.sort()
            for nzb in new_nzbs:
                msg = 'Found new nzb: '
                info(msg + archiveName(nzb))
                growlNotify('Queue', 'hellanzb ' + msg,archiveName(nzb), False)
                
        # Nothing to do, lets wait 5 seconds and start over
        if not Hellanzb.queued_nzbs:
            reactor.callLater(5, scanQueueDir)
            return

        nzbfilename = Hellanzb.queued_nzbs[0]
        del Hellanzb.queued_nzbs[0]
        
        # nzbfile will always be a absolute filename 
        nzbfile = Hellanzb.QUEUE_DIR + nzbfilename
        move(nzbfile, Hellanzb.CURRENT_DIR)
    else:
        resuming = True
        nzbfilename = current_nzbs[0]
        info('Resuming: ' + archiveName(nzbfilename))
        growlNotify('Queue', 'hellanzb Resuming:', archiveName(nzbfilename), False)
        del current_nzbs[0]
        
    if not resuming and len(Hellanzb.queued_nzbs):
        info('Downloading: ' + archiveName(nzbfilename))
        
    nzbfile = Hellanzb.CURRENT_DIR + nzbfilename

    # Change the cwd for Newsleecher, and download the files
    os.chdir(Hellanzb.WORKING_DIR)

    # Parse the NZB file into the Queue. Unless the NZB file is deemed already
    # fully processed at the end of parseNZB, tell the factory to start
    # downloading it
    try:
        if not Hellanzb.queue.parseNZB(nzbfile):
            
            for nsf in Hellanzb.nsfs:
                nsf.fetchNextNZBSegment()
    except FatalError, fe:
        scrollEnd()
        error('Problem while parsing the NZB', fe)
        growlNotify('Error', 'hellanzb', 'Problem while parsing the NZB' + prettyException(fe), True)
        error('Moving bad NZB out of queue into TEMP_DIR: ' + Hellanzb.TEMP_DIR)
        move(nzbfile, Hellanzb.TEMP_DIR + os.sep)
        reactor.callLater(5, scanQueueDir)

def handleNZBDone(nzbfilename):
    """ Hand-off from the downloader -- make a dir for the NZB with it's contents, then post
    process it in a separate thread"""
    checkShutdown()
    
    # Make our new directory, minus the .nzb
    newdir = Hellanzb.DEST_DIR + archiveName(nzbfilename)
    
    # Grab the message id, we'll store it in the newdir for later use
    msgId = re.sub(r'.*msgid_', r'', os.path.basename(nzbfilename))
    msgId = re.sub(r'_.*', r'', msgId)

    # Move our nzb contents to their new location, clear out the temp dir
    if os.path.exists(newdir):
        # Rename the dir if it exists already
        renamedDir = newdir + '_hellanzb_renamed'
        i = 0
        while os.path.exists(renamedDir + str(i)):
            i += 1
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
        # Give NZBLeecher some time (another reactor loop) to killHistory() & scrollEnd()
        # without any logging interference from PostProcessor
        reactor.callLater(0, troll.start)

    reactor.callLater(0, scanQueueDir)

"""
/*
 * Copyright (c) 2005 Ben Bangert <bbangert@groovie.org>
 *                    Philip Jenvey <pjenvey@groovie.org>
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
