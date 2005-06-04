"""

Daemon (aka Ziplick) - Filesystem queue daemon functions. They're all called from inside
the twisted reactor loop, except for initialization functions

(c) Copyright 2005 Ben Bangert, Philip Jenvey
[See end of file]
"""
import Hellanzb, os, re, PostProcessor
from sets import Set
from shutil import copy, move, rmtree
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
            
def initDaemon():
    """ Start the daemon """
    Hellanzb.queued_nzbs = []

    try:
        ensureDaemonDirs()
        initXMLRPCServer()
    except FatalError, fe:
        error('Exiting', fe)
        from Hellanzb.Core import shutdownNow
        shutdownNow(1)

    reactor.callLater(0, info, 'hellanzb - Now monitoring queue...')
    reactor.callLater(0, growlNotify, 'Queue', 'hellanzb', 'Now monitoring queue..', False)
    reactor.callLater(0, scanQueueDir, True)

    from Hellanzb.NZBLeecher import initNZBLeecher
    initNZBLeecher()

def scanQueueDir(firstRun = False, justScan = False):
    """ Find new/resume old NZB download sessions """
    import time
    t = time.time()

    from Hellanzb.NZBLeecher.NZBModel import NZB
    current_nzbs = []
    for file in os.listdir(Hellanzb.CURRENT_DIR):
        if re.search(r'\.nzb$', file):
            current_nzbs.append(Hellanzb.CURRENT_DIR + os.sep + file)

    # See if we're resuming a nzb fetch
    resuming = False
    displayNotification = False
    new_nzbs = []
    queuedMap = {}
    for nzb in Hellanzb.queued_nzbs:
        queuedMap[os.path.normpath(nzb.nzbFileName)] = nzb

    for file in os.listdir(Hellanzb.QUEUE_DIR):
        if re.search(r'\.nzb$', file) and \
            os.path.normpath(Hellanzb.QUEUE_DIR + os.sep + file) not in queuedMap:
            new_nzbs.append(Hellanzb.QUEUE_DIR + os.sep + file)

    enqueueNZBs(new_nzbs, writeQueue = not firstRun)
            
    if firstRun:
        sortQueueFromDisk()

    e = time.time() - t
    if justScan:
        # Done scanning -- don't bother loading a new NZB
        debug('scanQueueDir (justScan = True) TOOK: ' + str(e))
        Hellanzb.downloadScannerID = reactor.callLater(7, scanQueueDir, False, True)
        return
    else:
        debug('Ziplick scanQueueDir scanned queue dir')

    if not current_nzbs:
        if not Hellanzb.queued_nzbs:
            # Nothing to do, lets wait 5 seconds and start over
            reactor.callLater(5, scanQueueDir)
            return

        # Start the next download
        nzb = Hellanzb.queued_nzbs[0]
        nzbfilename = os.path.basename(nzb.nzbFileName)
        del Hellanzb.queued_nzbs[0]
    
        # nzbfile will always be a absolute filename 
        nzbfile = Hellanzb.QUEUE_DIR + nzbfilename
        move(nzbfile, Hellanzb.CURRENT_DIR)

        if not (len(new_nzbs) == 1 and len(Hellanzb.queued_nzbs) == 0):
            # Show what's going to be downloaded next, unless the queue was empty, and we
            # only found one nzb (The 'Found new nzb' message is enough in that case)
            displayNotification = True
    else:
        # Resume the NZB in the CURRENT_DIR
        nzbfilename = current_nzbs[0]
        nzb = NZB(nzbfilename)
        nzbfilename = os.path.basename(nzb.nzbFileName)
        displayNotification = True
        del current_nzbs[0]
        resuming = True

    nzbfile = Hellanzb.CURRENT_DIR + nzbfilename
    nzb.nzbFileName = nzbfile

    if resuming:
        parseNZB(nzb, 'Resuming')
    elif displayNotification:
        parseNZB(nzb)
    else:
        parseNZB(nzb, quiet = True)

def sortQueueFromDisk():
    """ sort the queue from what's on disk """
    onDiskQueue = loadQueueFromDisk()
    unsorted = Hellanzb.queued_nzbs[:]
    Hellanzb.queued_nzbs = []
    arranged = []
    for line in onDiskQueue:
        for nzb in unsorted:
            if os.path.basename(nzb.nzbFileName) == line:
                Hellanzb.queued_nzbs.append(nzb)
                arranged.append(nzb)
                break
    for nzb in arranged:
        unsorted.remove(nzb)
    for nzb in unsorted:
        Hellanzb.queued_nzbs.append(nzb)
            
def loadQueueFromDisk():
    """ load the queue from disk """
    queue = []
    if os.path.isfile(Hellanzb.QUEUE_LIST):
        try:
            f = open(Hellanzb.QUEUE_LIST)
        except:
            f.close()
            return queue
        for line in f:
            queue.append(line.strip('\n'))
        f.close()
    return queue

def writeQueueToDisk(queue):
    """ write the queue to disk """
    unique = []
    for item in queue:
        if item not in unique:
            unique.append(item)
    if len(unique) != len(queue):
        warn('Warning: Found duplicates in queue while writing to disk: ' + \
             str([nzb.nzbFileName for nzb in queue]))
    queue = unique
        
    f = open(Hellanzb.QUEUE_LIST, 'w')
    for nzb in queue:
        f.write(os.path.basename(nzb.nzbFileName) + '\n')
    f.close()
    
def parseNZB(nzb, notification = 'Downloading', quiet = False):
    """ Parse the NZB file into the Queue. Unless the NZB file is deemed already fully
    processed at the end of parseNZB, tell the factory to start downloading it """
    writeQueueToDisk(Hellanzb.queued_nzbs)

    if not quiet:
        info(notification + ': ' + nzb.archiveName)
        growlNotify('Queue', 'hellanzb ' + notification + ':', nzb.archiveName,
                    False)

    try:
        findAndLoadPostponedDir(nzb)
        
        info('Parsing: ' + os.path.basename(nzb.nzbFileName) + '...')
        if not Hellanzb.queue.parseNZB(nzb):
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

def findAndLoadPostponedDir(nzb):
    def fixNZBFileName(nzb):
        if os.path.normpath(os.path.dirname(nzb.destDir)) == os.path.normpath(Hellanzb.POSTPONED_DIR):
            nzb.destDir = Hellanzb.WORKING_DIR
        
    nzbfilename = nzb.nzbFileName
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

        fixNZBFileName(nzb)
        return True
    else:
        fixNZBFileName(nzb)
        return False

def handleNZBDone(nzbfilename):
    """ Hand-off from the downloader -- make a dir for the NZB with its contents, then post
    process it in a separate thread"""
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

    # Finally unarchive/process the directory in another thread, and continue
    # nzbing
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

def validNZB(nzbfilename):
    if nzbfilename == None or not os.path.isfile(nzbfilename):
        error('Invalid NZB file: ' + str(nzbfilename))
        return False
    elif not os.access(nzbfilename, os.R_OK):
        error('Unable to read NZB file: ' + str(nzbfilename))
        return False
    return True

def isActive():
    """ whether or not we're actively downloading """
    activeCount = 0
    for nsf in Hellanzb.nsfs:
        activeCount += len(nsf.activeClients)
    return activeCount > 0

def cancelCurrent():
    """ cancel the current d/l, remove the nzb. return False if there was nothing to cancel
    """
    if not isActive():
        return False
    
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
            client.isActive(False)
            
    reactor.callLater(0, scanQueueDir)
        
    return canceled

def pauseCurrent():
    """ pause the current download """
    if not isActive():
        return False

    Hellanzb.downloadPaused = True
    for nsf in Hellanzb.nsfs:
        clients = nsf.activeClients.copy()
        for client in clients:
            client.transport.stopReading()

    info('Pausing download')
    return True

def continueCurrent():
    """ continue an already paused download """
    if not isActive() or not Hellanzb.downloadPaused:
        return False
    
    for nsf in Hellanzb.nsfs:
        clients = nsf.activeClients.copy()
        for client in clients:
            client.transport.startReading()

    Hellanzb.downloadPaused = False
    info('Continuing download')
    return True

def clearCurrent(andCancel):
    """ clear the queue -- optionally clear what's currently being downloaded (cancel it) """
    info('Clearing queue')
    Hellanzb.queued_nzbs = []
    writeQueueToDisk(Hellanzb.queued_nzbs)
    for file in os.listdir(Hellanzb.QUEUE_DIR):
        file = Hellanzb.QUEUE_DIR + os.sep + file
        if os.path.isfile(file):
            os.remove(file)
        elif os.path.isdir(file):
            rmtree(file)

    if andCancel:
        cancelCurrent()

    return True

def moveUp(nzbId, shift = 1, moveDown = False):
    """ move the specified nzb up in the queue """
    try:
        nzbId = int(nzbId)
    except:
        debug('Invalid ID: ' + str(nzbId))
        return False
    try:
        shift = int(shift)
    except:
        debug('Invalid shift: ' + str(shift))
        return False
            
    i = 0
    foundNzb = None
    for nzb in Hellanzb.queued_nzbs:
        if nzb.id == nzbId:
            foundNzb = nzb
            break
        i += 1
        
    if not foundNzb:
        return False

    if i - shift <= -1 and not moveDown:
        # can't go any higher
        return False
    elif i + shift >= len(Hellanzb.queued_nzbs) and moveDown:
        # can't go any lower
        return False

    Hellanzb.queued_nzbs.remove(foundNzb)
    if not moveDown:
        Hellanzb.queued_nzbs.insert(i - shift, foundNzb)
    else:
        Hellanzb.queued_nzbs.insert(i + shift, foundNzb)
    writeQueueToDisk(Hellanzb.queued_nzbs)
    return True

def moveDown(nzbId, shift = 1):
    """ move the specified nzb down in the queue """
    return moveUp(nzbId, shift, moveDown = True)

def dequeueNZBs(nzbIdOrIds):
    """ remove nzbs from the queue """
    if type(nzbIdOrIds) != list:
        newNzbIds = [ nzbIdOrIds ]
    else:
        newNzbIds = nzbIdOrIds

    if len(newNzbIds) == 0:
        return False

    error = False
    found = []
    for nzbId in newNzbIds:
        try:
            nzbId = int(nzbId)
        except Exception:
            error = True
            continue
        
        for nzb in Hellanzb.queued_nzbs:
            if nzb.id == nzbId:
                found.append(nzb)
    for nzb in found:
        info('Dequeueing: ' + nzb.archiveName)
        move(nzb.nzbFileName, Hellanzb.TEMP_DIR + os.sep + os.path.basename(nzb.nzbFileName))
        Hellanzb.queued_nzbs.remove(nzb)
        
    return not error
    
def enqueueNZBs(nzbFileOrFiles, next = False, writeQueue = True):
    """ add one or a list of nzb files to the end of the queue """
    if type(nzbFileOrFiles) != list:
        newNzbFiles = [ nzbFileOrFiles ]
    else:
        newNzbFiles = nzbFileOrFiles

    if len(newNzbFiles) == 0:
        return False
    
    for nzbFile in newNzbFiles:
        if validNZB(nzbFile):
            if os.path.normpath(os.path.dirname(nzbFile)) != os.path.normpath(Hellanzb.QUEUE_DIR):
                copy(nzbFile, Hellanzb.QUEUE_DIR + os.sep + os.path.basename(nzbFile))
            nzbFile = Hellanzb.QUEUE_DIR + os.sep + os.path.basename(nzbFile)

            found = False
            for n in Hellanzb.queued_nzbs:
                if os.path.normpath(n.nzbFileName) == os.path.normpath(nzbFile):
                    found = True
                    error('Cannot add nzb file to queue: ' + os.path.basename(nzbFile) + \
                          ' it already exists!')
            if found:
                continue
                    
            from Hellanzb.NZBLeecher.NZBModel import NZB
            nzb = NZB(nzbFile)
            
            if not next:
                Hellanzb.queued_nzbs.append(nzb)
            else:
                Hellanzb.queued_nzbs.insert(0, nzb)

            msg = 'Found new nzb: '
            info(msg + archiveName(nzbFile))
            growlNotify('Queue', 'hellanzb ' + msg, archiveName(nzbFile), False)
                
    if writeQueue:
        writeQueueToDisk(Hellanzb.queued_nzbs)
            
def enqueueNextNZBs(nzbFileOrFiles):
    """ enqueue one or more nzbs to the beginning of the queue """
    return enqueueNZBs(nzbFileOrFiles, next = True)

def nextNZBId(nzbId):
    """ enqueue the specified nzb to the beginning of the queue """
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

    Hellanzb.queued_nzbs.remove(foundNZB)
    Hellanzb.queued_nzbs.insert(0, foundNZB)

    writeQueueToDisk(Hellanzb.queued_nzbs)

def maxRate(rate):
    """ Switch the MAX RATE setting """
    if rate == 'None':
        rate = 0
    else:
        try:
            rate = int(rate)
        except:
            return False
        
    info('Resetting max download rate to: ' + str(rate))
    if rate == 0:
        rate = None
    else:
        rate = rate * 1024
        
    restartCheckRead = False
    if rate == None:
        Hellanzb.ht.unthrottleReadsID.cancel()
        Hellanzb.ht.checkReadBandwidthID.cancel()
        Hellanzb.ht.unthrottleReads()
    elif Hellanzb.ht.readLimit == None and rate > None:
        restartCheckRead = True
    Hellanzb.ht.readLimit = rate
    if restartCheckRead:
        Hellanzb.ht.checkReadBandwidth()
    return True

"""
# FIXME: returning an xml struct would be nice, but this loses the queue order
def listQueue(includeIds = False):
    #Return a listing of the current queue
    if includeIds:
        queueList = {}
        def add(key, val): queueList[key] = val
    else:
        queueList = []
        add = lambda key, val : queueList.append(val)
        
    for nzb in Hellanzb.queued_nzbs:
        name = os.path.basename(nzb.nzbFileName)
        id = str(nzb.id)
        add(id, name)
        
    return queueList
"""

def listQueue(includeIds = False):
    """ Return a listing of the current queue """
    members = []
    for nzb in Hellanzb.queued_nzbs:
        member = os.path.basename(nzb.nzbFileName)
        if includeIds:
            length = 6
            id = str(nzb.id)
            member = id + ' '*(length - len(id)) + member
        members.append(member)
    return members

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
        return parseNZB(nzbfilename)

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
            Hellanzb.queued_nzbs.append(nzb) # FIXME: use enqueue here?
            writeQueueToDisk(Hellanzb.queued_nzbs)

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
