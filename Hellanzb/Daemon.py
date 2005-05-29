"""

Daemon (aka Ziplick) - Filesystem queue daemon functions. They're all called from inside
the twisted reactor loop, except for initialization functions

(c) Copyright 2005 Ben Bangert, Philip Jenvey
[See end of file]
"""
import Hellanzb, os, re, PostProcessor
from shutil import copy, move
from twisted.internet import reactor
from Hellanzb.HellaXMLRPC import initXMLRPCServer, HellaXMLRPCServer
from Hellanzb.Log import *
from Hellanzb.Logging import prettyException
from Hellanzb.Util import *

__id__ = '$Id$'

def ensureDaemonDirs():
    """ Ensure that all the required directories exist and are writable, otherwise attempt to
    create them """
    badPermDirs = []
    for arg in dir(Hellanzb):
        if stringEndsWith(arg, "_DIR") and arg == arg.upper():
            exec 'dirName = Hellanzb.' + arg
            if dirName == None:
                raise FatalError('Required directory not defined in config file: Hellanzb.' + arg)
            elif not os.path.isdir(dirName):
                try:
                    os.makedirs(dirName)
                except OSError, ose:
                    # FIXME: this isn't caught -- it's not a clean way to exit the program
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
            
def initDaemon():
    """ Start the daemon """
    try:
        ensureDaemonDirs()
    except FatalError, fe:
        error('Exiting', fe)
        from Hellanzb.Core import shutdownNow
        shutdownNow(1)        

    reactor.callLater(0, info, 'hellanzb - Now monitoring queue...')
    reactor.callLater(0, growlNotify, 'Queue', 'hellanzb', 'Now monitoring queue..', False)
    reactor.callLater(0, scanQueueDir)

    Hellanzb.queued_nzbs = []

    initXMLRPCServer()

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
    displayNotification = False
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

        if not (len(new_nzbs) == 1 and len(Hellanzb.queued_nzbs) == 0):
            # Show what's going to be downloaded next, unless the queue was empty, and we
            # only found one nzb (The 'Found new nzb' message is enough in that case)
            displayNotification = True
    else:
        nzbfilename = current_nzbs[0]
        displayNotification = True
        del current_nzbs[0]
        resuming = True

    nzbfile = Hellanzb.CURRENT_DIR + nzbfilename

    # Change the cwd for Newsleecher, and download the files
    os.chdir(Hellanzb.WORKING_DIR)

    if resuming:
        parseNZB(nzbfile, 'Resuming')
    elif displayNotification:
        parseNZB(nzbfile)
    else:
        parseNZB(nzbfile, quiet = True)

def parseNZB(nzbfile, notification = 'Downloading', quiet = False):
    """ Parse the NZB file into the Queue. Unless the NZB file is deemed already fully
    processed at the end of parseNZB, tell the factory to start downloading it """
    if not quiet:
        info(notification + ': ' + archiveName(nzbfile))
        growlNotify('Queue', 'hellanzb ' + notification + ':', archiveName(nzbfile),
                    False)

    info('Parsing ' + os.path.basename(nzbfile) + '...')
    try:
        findAndLoadPostponedDir(nzbfile)
        
        if not Hellanzb.queue.parseNZB(nzbfile):
            for nsf in Hellanzb.nsfs:
                if not len(nsf.activeClients):
                    nsf.fetchNextNZBSegment()

    except FatalError, fe:
        error('Problem while parsing the NZB', fe)
        growlNotify('Error', 'hellanzb', 'Problem while parsing the NZB' + prettyException(fe),
                    True)
        error('Moving bad NZB out of queue into TEMP_DIR: ' + Hellanzb.TEMP_DIR)
        move(nzbfile, Hellanzb.TEMP_DIR + os.sep)
        reactor.callLater(5, scanQueueDir)

def findAndLoadPostponedDir(nzbfilename):
    d = Hellanzb.POSTPONED_DIR + os.sep + archiveName(nzbfilename)
    if os.path.isdir(d):
        try:
            os.rmdir(Hellanzb.WORKING_DIR)
        except OSError:
            files = os.listdir(Hellanzb.WORKING_DIR)[0]
            if len(files):
                name = files[0]
                ext = getFileExtension(name)
                if ext != None:
                    name = name.replace(ext, '')
                move(Hellanzb.WORKING_DIR, Hellanzb.TEMP_DIR + os.sep + name)

            else:
                debug('ERROR Stray WORKING_DIR!: ' + str(os.listdir(Hellanzb.WORKING_DIR)))
                name = Hellanzb.TEMP_DIR + os.sep + 'stray_WORKING_DIR'
                hellaRename(name)
                move(Hellanzb.WORKING_DIR, name)

        move(d, Hellanzb.WORKING_DIR)

        # unpostpone from the queue
        Hellanzb.queue.nzbFilesLock.acquire()
        arName = archiveName(nzbfilename)
        found = []
        for nzbFile in Hellanzb.queue.postponedNzbFiles:
            if nzbFile.nzb.archiveName == arName:
                found.append(nzbFile)
        for nzbFile in found:
            Hellanzb.queue.postponedNzbFiles.remove(nzbFile)
        Hellanzb.queue.nzbFilesLock.release()

        info('Loaded postponed directory: ' + archiveName(nzbfilename))
        
        return True
    else:
        return False

def handleNZBDone(nzbfilename):
    """ Hand-off from the downloader -- make a dir for the NZB with its contents, then post
    process it in a separate thread"""
    checkShutdown()
    
    # Make our new directory, minus the .nzb
    newdir = Hellanzb.DEST_DIR + archiveName(nzbfilename)
    
    # Grab the message id, we'll store it in the newdir for later use
    msgId = getMsgId(nzbfilename)

    # Move our nzb contents to their new location, clear out the temp dir
    hellaRename(newdir)
        
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

def postProcess(options):
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
    reactor.callInThread(troll.run)

def stop():
    """ stop the currently downloading nzb. move its downloaded files to the postponed
    directory, and queue its nzb to be downloaded next """
    # FIXME: should there only be ONE active nzb ? does hte safe changing the of nzb
    # always take place in the reactor thread?
    pass

def forceNZB(nzbfilename):
    """ interrupt the current download, if necessary, to start the specified nzb """
    if nzbfilename == None or not os.path.isfile(nzbfilename):
        error('Invalid NZB file: ' + str(nzbfilename))
        return
    elif not os.access(nzbfilename, os.R_OK):
        error('Unable to read NZB file: ' + str(nzbfilename))
        return

    if not len(Hellanzb.queue.nzbs):
        # No need to actually 'force'
        return parseNZB(nzbfilename)

    # postpone the current NZB download
    for nzb in Hellanzb.queue.currentNZBs():
        try:
            postponed = Hellanzb.POSTPONED_DIR + nzb.archiveName
            hellaRename(postponed)
            os.mkdir(postponed)
            nzb.destDir = postponed
            info('Interrupting: ' + nzb.archiveName + ' forcing: ' + archiveName(nzbfilename))
            
            move(nzb.nzbFileName, Hellanzb.QUEUE_DIR + os.sep + os.path.basename(nzb.nzbFileName))
            Hellanzb.queued_nzbs.append(os.path.basename(nzb.nzbFileName))

            # Move the postponed files to the new postponed dir
            for file in os.listdir(Hellanzb.WORKING_DIR):
                move(Hellanzb.WORKING_DIR + os.sep + file, postponed + os.sep + file)

            # Copy the specified NZB, unless it's already in the queue dir (move it
            # instead)
            if os.path.dirname(nzbfilename) != Hellanzb.QUEUE_DIR:
                copy(nzbfilename, Hellanzb.CURRENT_DIR + os.sep + os.path.basename(nzbfilename))
            else:
                move(nzbfilename, Hellanzb.CURRENT_DIR + os.sep + os.path.basename(nzbfilename))
            nzbfilename = Hellanzb.CURRENT_DIR + os.sep + os.path.basename(nzbfilename)

            # delete everything from the queue. priority will be reset
            Hellanzb.queue.postpone()

            # load the new file
            reactor.callLater(0, parseNZB, nzbfilename)

        except NameError, ne:
            # GC beat us. that should mean there is either a free spot open, or the next
            # nzb in the queue needs to be interrupted????
            debug('forceNZB: NAME ERROR', ne)
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
