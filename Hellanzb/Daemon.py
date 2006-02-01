"""

Daemon (aka Ziplick) - Filesystem queue daemon functions. They're all called from inside
the twisted reactor loop, except for initialization functions

(c) Copyright 2005 Ben Bangert, Philip Jenvey
[See end of file]
"""
import os, time, Hellanzb, PostProcessor, PostProcessorUtil
from shutil import copy, move, rmtree
from twisted.internet import reactor
from twisted.scripts.twistd import daemonize
from Hellanzb.HellaXMLRPC import initXMLRPCServer, HellaXMLRPCServer
from Hellanzb.Log import *
from Hellanzb.Logging import prettyException
from Hellanzb.NZBQueue import dequeueNZBs, loadQueueFromDisk, parseNZB, \
    recoverFromOnDiskQueue, scanQueueDir, syncFromRecovery, writeQueueToDisk
from Hellanzb.Util import archiveName, getMsgId, hellaRename, prettyElapsed, prettySize, \
    touch, validNZB, IDPool

__id__ = '$Id$'

def ensureDaemonDirs():
    """ Ensure that all the required directories exist and are writable, otherwise attempt to
    create them """
    badPermDirs = []
    for arg in dir(Hellanzb):
        if arg.endswith("_DIR") and arg == arg.upper():
            exec 'dirName = Hellanzb.' + arg
            if dirName == None:
                raise FatalError('Required directory not defined in config file: Hellanzb.' + arg)
            elif not os.path.isdir(dirName):
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

    if not hasattr(Hellanzb, 'QUEUE_LIST') or Hellanzb.QUEUE_LIST == None:
        raise FatalError('Hellanzb.QUEUE_LIST not defined in config file')
    elif os.path.isfile(Hellanzb.QUEUE_LIST) and not os.access(Hellanzb.QUEUE_LIST, os.W_OK):
        raise FatalError('hellanzb does not have write access to the Hellanzb.QUEUE_LIST file')

def ensureDownloadTempDir():
    """ This must be called just prior to starting the daemon, thus it's separated from
    ensureDaemonDirs(). We don't want to touch/nuke the download temp dir until we know we
    are the only queue daemon running (if we aren't, initXMLRPCServer will throw an
    exception) """
    # Clear out the old download temp dir (where encoded files are stored) and create a
    # fresh one
    Hellanzb.DOWNLOAD_TEMP_DIR = Hellanzb.TEMP_DIR + os.sep + 'download-tmp'
    if os.path.exists(Hellanzb.DOWNLOAD_TEMP_DIR):
        if not os.access(Hellanzb.DOWNLOAD_TEMP_DIR, os.W_OK):
            dirName = Hellanzb.DOWNLOAD_TEMP_DIR
            # del the var so Core.shutdown() does not attempt to rmtree() the dir
            del Hellanzb.DOWNLOAD_TEMP_DIR
            raise FatalError('Cannot continue: hellanzb needs write access to ' + dirName)
        
        rmtree(Hellanzb.DOWNLOAD_TEMP_DIR)
        
    os.makedirs(Hellanzb.DOWNLOAD_TEMP_DIR)
            
def initDaemon():
    """ Start the daemon """
    Hellanzb.queued_nzbs = []

    try:
        ensureDaemonDirs()
        initXMLRPCServer()
        ensureDownloadTempDir() # needs to be called AFTER initXMLRPCServer
    except FatalError, fe:
        error('Exiting', fe)
        from Hellanzb.Core import shutdownAndExit
        shutdownAndExit(1)

    reactor.callLater(0, info, 'hellanzb - Now monitoring queue...')
    reactor.callLater(0, growlNotify, 'Queue', 'hellanzb', 'Now monitoring queue..', False)
    reactor.callLater(0, loadQueueFromDisk)
    reactor.callLater(0, resumePostProcessors)
    reactor.callLater(0, scanQueueDir, True)

    if Hellanzb.DAEMONIZE:
        daemonize()
    
    from Hellanzb.NZBLeecher import initNZBLeecher
    initNZBLeecher()

def resumePostProcessors():
    """ Pickup left off Post Processors that were cancelled via CTRL-C """
    # FIXME: with the new queue, could kill the processing dir sym links (for windows)
    for resumeArchiveName in os.listdir(Hellanzb.PROCESSING_DIR):
        if resumeArchiveName[0] == '.':
            continue

        archiveDir = Hellanzb.PROCESSING_DIR + os.sep + resumeArchiveName
        # syncFromRecovery should pick up the password
        """
        rarPassword = None
        if os.path.isfile(archiveDir + os.sep + '.hellanzb_rar_password'):
            rarPassword = ''.join(open(archiveDir + os.sep + '.hellanzb_rar_password').readlines())
        """

        recovered = recoverFromOnDiskQueue(resumeArchiveName, 'processing')
        if recovered:
            if recovered.get('nzbFileName') is not None:
                from Hellanzb.NZBLeecher.NZBModel import NZB
                archive = NZB(recovered['nzbFileName'], recovered['id'],
                              archiveDir = archiveDir)
                #id = recovered['id']
            else:
                archive = PostProcessorUtil.Archive(archiveDir, recovered['id'])
        else:
            archive = PostProcessorUtil.Archive(archiveDir, IDPool.getNextId())
            #id = IDPool.getNextId()

        #archive = PostProcessorUtil.Archive(archiveDir, id)
        troll = PostProcessor.PostProcessor(archive)
        syncFromRecovery(troll, recovered)

        info('Resuming post processor: ' + archiveName(resumeArchiveName))
        troll.start()

def beginDownload():
    """ Initialize the download. Notify the downloaders to begin their work, etc """
    # BEGIN
    writeQueueToDisk()
    now = time.time()
    Hellanzb.totalReadBytes = 0
    Hellanzb.totalStartTime = now
    
    # The scroll level will flood the console with constantly updating
    # statistics -- the logging system can interrupt this scroll
    # temporarily (after scrollBegin)
    scrollBegin()

    # Scan the queue dir intermittently during downloading. Reset the scanner delayed call
    # if it's already going
    if Hellanzb.downloadScannerID != None and not Hellanzb.downloadScannerID.cancelled and \
            not Hellanzb.downloadScannerID.called:
        Hellanzb.downloadScannerID.cancel()
    Hellanzb.downloadScannerID = reactor.callLater(5, scanQueueDir, False, True)
    
    for nsf in Hellanzb.nsfs:
        nsf.beginDownload()
                
    Hellanzb.scroller.started = True
    Hellanzb.scroller.killedHistory = False

def endDownload():
    """ Finished downloading """
    elapsed = time.time() - Hellanzb.totalStartTime
    speed = Hellanzb.totalReadBytes / 1024.0 / elapsed
    leeched = prettySize(Hellanzb.totalReadBytes)
    info('Transferred %s in %s at %.1fKB/s' % (leeched, prettyElapsed(elapsed), speed))
    
    Hellanzb.totalReadBytes = 0
    Hellanzb.totalStartTime = None
    Hellanzb.totalSpeed = 0
    Hellanzb.scroller.currentLog = None

    scrollEnd()

    Hellanzb.downloadScannerID.cancel()
    Hellanzb.totalArchivesDownloaded += 1
    writeQueueToDisk()
    # END

def handleNZBDone(nzb):
    """ Hand-off from the downloader -- make a dir for the NZB with its contents, then post
    process it in a separate thread"""
    # Make our new directory, minus the .nzb
    processingDir = Hellanzb.PROCESSING_DIR + nzb.archiveName
    
    # Grab the message id, we'll store it in the processingDir for later use
    msgId = getMsgId(nzb.nzbFileName)

    # Move our nzb contents to their new location for post processing
    hellaRename(processingDir)
        
    move(Hellanzb.WORKING_DIR, processingDir)
    nzb.archiveDir = processingDir
    
    move(nzb.nzbFileName, processingDir)
    nzb.nzbFileName = processingDir + os.sep + nzb.nzbFileName
    
    touch(processingDir + os.sep + '.msgid_' + msgId)
    
    os.mkdir(Hellanzb.WORKING_DIR)

    hasMorePars = False
    for nzbFile in nzb.nzbFileElements:
        if nzbFile.isSkippedPar:
            hasMorePars = True
            break
        
    # Finally unarchive/process the directory in another thread, and continue
    # nzbing
    troll = PostProcessor.PostProcessor(nzb, hasMorePars)

    # Give NZBLeecher some time (another reactor loop) to killHistory() & scrollEnd()
    # without any logging interference from PostProcessor
    reactor.callLater(0, troll.start)
    reactor.callLater(0, writeQueueToDisk)
    reactor.callLater(0, scanQueueDir)

def postProcess(options, isQueueDaemon = False):
    """ Call the post processor via twisted """
    from Hellanzb.Core import shutdown
    if not os.path.isdir(options.postProcessDir):
        error('Unable to process, not a directory: ' + options.postProcessDir)
        shutdown()
        return

    if not os.access(options.postProcessDir, os.R_OK):
        error('Unable to process, no read access to directory: ' + options.postProcessDir)
        shutdown()
        return

    rarPassword = None
    if options.rarPassword:
        rarPassword = options.rarPassword

    # UNIX: realpath
    # FIXME: I don't recall why realpath is even necessary
    dirName = os.path.realpath(options.postProcessDir)
    archive = PostProcessorUtil.Archive(dirName, rarPassword = rarPassword)
    troll = Hellanzb.PostProcessor.PostProcessor(archive, background = False)

    reactor.callLater(0, info, '')
    reactor.callLater(0, info, 'Starting post processor')
    reactor.callLater(0, reactor.callInThread, troll.run)
    if isQueueDaemon:
        reactor.callLater(0, writeQueueToDisk)

def isActive():
    """ Whether or not we're actively downloading """
    activeCount = 0
    for nsf in Hellanzb.nsfs:
        activeCount += len(nsf.activeClients)
    return activeCount > 0

def cancelCurrent():
    """ Cancel the current d/l, remove the nzb. return False if there was nothing to cancel
    """
    if not isActive():
        return True
    
    canceled = False
    for nzb in Hellanzb.queue.currentNZBs():
        canceled = True
        nzb.cancel()
        move(nzb.nzbFileName, Hellanzb.TEMP_DIR + os.sep + os.path.basename(nzb.nzbFileName))
        info('Canceling download: ' + nzb.archiveName)
    Hellanzb.queue.cancel()
    try:
        hellaRename(Hellanzb.TEMP_DIR + os.sep + 'canceled_WORKING_DIR')
        move(Hellanzb.WORKING_DIR, Hellanzb.TEMP_DIR + os.sep + 'canceled_WORKING_DIR')
        os.mkdir(Hellanzb.WORKING_DIR)
        rmtree(Hellanzb.TEMP_DIR + os.sep + 'canceled_WORKING_DIR')
    except Exception, e:
        error('Problem while canceling WORKING_DIR', e)

    if not canceled:
        debug('ERROR: isActive was True but canceled nothing (no active nzbs!??)')

    for nsf in Hellanzb.nsfs:
        clients = nsf.activeClients.copy()
        for client in clients:
            client.transport.loseConnection()
            
            # NOTE: WEIRD: after pool-coop branch, I have to force this to prevent
            # fetchNextNZBSegment from re-calling the fetch loop (it gets called
            # twice. the parseNZB->beginDownload->fetchNext call is made before the client
            # gets to call connectionLost). or has this problem always existed??? See r403
            client.isLoggedIn = False
            
            client.deactivate()
            
    writeQueueToDisk()
    reactor.callLater(0, scanQueueDir)
        
    return canceled

def pauseCurrent():
    """ Pause the current download """
    Hellanzb.downloadPaused = True

    for nsf in Hellanzb.nsfs:
        for client in nsf.clients:
            client.transport.stopReading()

    info('Pausing download')
    return True

def continueCurrent():
    """ Continue an already paused download """
    if not Hellanzb.downloadPaused:
        return True

    resetConnections = 0
    for nsf in Hellanzb.nsfs:
        connectionCount = nsf.connectionCount
        for client in nsf.clients:

            # When we pause a download, we simply stop reading from the socket. That
            # causes the connection to become lost fairly quickly. When that happens a new
            # client is created with the flag pauseReconnected=True. This new client acts
            # normally (anti idles the connection, etc) except it does not enter the
            # fetchNextNZBSegment loop. Thus when we encounter these clients we simply
            # tell them to begin downloading
            if client.pauseReconnected:
                debug(str(client) + ' pauseReconnect')
                client.pauseReconnected = False
                reactor.callLater(0, client.fetchNextNZBSegment)
            else:
                # Otherwise this was a short pause, the connection hasn't been lost, and
                # we can simply continue reading from the socket
                debug(str(client) + ' startReading')
                client.transport.startReading()
                connectionCount -= 1
                
        resetConnections += connectionCount

    Hellanzb.downloadPaused = False
    if resetConnections:
        info('Continuing download (%i connections were reset)' % resetConnections)
    else:
        info('Continuing download')
    return True

def clearCurrent(andCancel):
    """ Clear the queue -- optionally clear what's currently being downloaded (cancel it) """
    info('Clearing queue')
    dequeueNZBs([nzb.id for nzb in Hellanzb.queued_nzbs], quiet = True)
    
    if andCancel:
        cancelCurrent()

    return True

def getRate():
    """ Return the current MAX_RATE value """
    return Hellanzb.ht.readLimit / 1024
    
def maxRate(rate):
    """ Change the MAX_RATE value. Return the new value """
    if rate == 'None' or rate == None:
        rate = 0
    else:
        try:
            rate = int(rate)
        except:
            return getRate()

    if rate < 0:
        rate = 0
        
    info('Resetting MAX_RATE to: ' + str(rate) + 'KB/s')
    
    rate = rate * 1024
        
    restartCheckRead = False
    if rate == 0:
        if Hellanzb.ht.unthrottleReadsID != None and \
                not Hellanzb.ht.unthrottleReadsID.cancelled and \
                not Hellanzb.ht.unthrottleReadsID.called:
            Hellanzb.ht.unthrottleReadsID.cancel()

        if Hellanzb.ht.checkReadBandwidthID != None and \
            not Hellanzb.ht.checkReadBandwidthID.cancelled:
            Hellanzb.ht.checkReadBandwidthID.cancel()
        Hellanzb.ht.unthrottleReads()
    elif Hellanzb.ht.readLimit == 0 and rate > 0:
        restartCheckRead = True
        
    Hellanzb.ht.readLimit = rate

    if restartCheckRead:
        Hellanzb.ht.readThisSecond = 0 # nobody's been resetting this value
        reactor.callLater(1, Hellanzb.ht.checkReadBandwidth)
    return getRate()

def setRarPassword(nzbId, rarPassword):
    """ Set the rarPassword on the specified NZB or NZB archive """
    try:
        nzbId = int(nzbId)
    except:
        debug('Invalid ID: ' + str(nzbId))
        return False
    
    # Find the nzbId in the queued list, processing list, or currently downloading nzb
    found = None
    for collection in (Hellanzb.queue.currentNZBs(), Hellanzb.postProcessors,
                       Hellanzb.queued_nzbs):
        for nzbOrArchive in collection:
            if nzbOrArchive.id == nzbId:
                found = nzbOrArchive
                break

    if found:
        found.rarPassword = rarPassword
        writeQueueToDisk()
        return True
    
    return False
        
def forceNZBId(nzbId):
    """ Interrupt the current download, if necessary, to start the specified nzb in the queue
    """
    try:
        nzbId = int(nzbId)
    except:
        debug('Invalid ID: ' + str(nzbId))
        return False

    foundNZB = None
    for nzb in Hellanzb.queued_nzbs:
        if nzb.id == nzbId:
            foundNZB = nzb
            
    if not foundNZB:
        return False
    
    forceNZB(foundNZB.nzbFileName)

def forceNZB(nzbfilename):
    """ Interrupt the current download, if necessary, to start the specified nzb """
    if not validNZB(nzbfilename):
        return

    if not len(Hellanzb.queue.nzbs):
        # No need to actually 'force'
        return parseNZB(NZB(nzbfilename))

    # postpone the current NZB download
    for nzb in Hellanzb.queue.currentNZBs():
        try:
            postponed = Hellanzb.POSTPONED_DIR + nzb.archiveName
            hellaRename(postponed)
            os.mkdir(postponed)
            nzb.destDir = postponed
            info('Interrupting: ' + nzb.archiveName)
            
            move(nzb.nzbFileName, Hellanzb.QUEUE_DIR + os.sep + os.path.basename(nzb.nzbFileName))
            nzb.nzbFileName = Hellanzb.QUEUE_DIR + os.sep + os.path.basename(nzb.nzbFileName)
            Hellanzb.queued_nzbs.insert(0, nzb)
            writeQueueToDisk()

            # remove what we've forced with from the old queue, if it exists
            nzb = None
            for n in Hellanzb.queued_nzbs:
                if os.path.normpath(n.nzbFileName) == os.path.normpath(nzbfilename):
                    nzb = n
                    
            if nzb == None:
                from Hellanzb.NZBLeecher.NZBModel import NZB
                nzb = NZB(nzbfilename)
            else:
                Hellanzb.queued_nzbs.remove(nzb)
    
            # Move the postponed files to the new postponed dir
            for file in os.listdir(Hellanzb.WORKING_DIR):
                move(Hellanzb.WORKING_DIR + os.sep + file, postponed + os.sep + file)

            # Copy the specified NZB, unless it's already in the queue dir (move it
            # instead)
            if os.path.normpath(os.path.dirname(nzbfilename)) != os.path.normpath(Hellanzb.QUEUE_DIR):
                copy(nzbfilename, Hellanzb.CURRENT_DIR + os.sep + os.path.basename(nzbfilename))
            else:
                move(nzbfilename, Hellanzb.CURRENT_DIR + os.sep + os.path.basename(nzbfilename))
            nzbfilename = Hellanzb.CURRENT_DIR + os.sep + os.path.basename(nzbfilename)
            nzb.nzbFileName = nzbfilename

            # delete everything from the queue. priority will be reset
            Hellanzb.queue.postpone()

            # load the new file
            reactor.callLater(0, parseNZB, nzb, 'Forcing Download')

        except NameError, ne:
            # GC beat us. that should mean there is either a free spot open, or the next
            # nzb in the queue needs to be interrupted????
            debug('forceNZB: NAME ERROR', ne)
            reactor.callLater(0, scanQueueDir)

def forceNZBParRecover(nzb, neededBlocks):
    """ Immediately begin (force) downloading recovery blocks (only the neededBlocks amount)
    for the specified NZB """
    nzb.isParRecovery = True
    forceNZB(nzb.nzbFileName)
    

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
