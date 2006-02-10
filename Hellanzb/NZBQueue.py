"""

NZBQueue - Maintains NZB files queued to be downloaded in the future

These are all module level functions that operate on the main Hellanzb queue, located at
Hellanzb.queued_nzbs

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import os, re, time, Hellanzb, Hellanzb.Daemon
from shutil import copy, move, rmtree
from twisted.internet import reactor
from xml.sax import make_parser, SAXParseException
from xml.sax.handler import ContentHandler, feature_external_ges, feature_namespaces
from Hellanzb.external.elementtree.SimpleXMLWriter import XMLWriter
from Hellanzb.Log import *
from Hellanzb.NewzbinDownloader import NewzbinDownloader
from Hellanzb.Util import IDPool, archiveName, hellaRename, inMainThread, \
    getFileExtension, toUnicode, validNZB

__id__ = '$Id$'

class HellanzbStateXMLParser(ContentHandler):
    """ Loads the on disk STATE_XML_FILE into an RecoveredState object """
    def __init__(self):
        Hellanzb.recoveredState = RecoveredState()

        self.currentTag = None
        self.currentAttrs = None
        self.skippedParContent = ''
        
    def startElement(self, name, attrs):
        self.currentTag = name
        # <hellanzbState newzbinSessId="8f9c7badc62a5d5f776d810f0498cde1" version="0.9-trunk">
        if name == 'hellanzbState':
            Hellanzb.recoveredState.version = attrs.get('version')
            Hellanzb.recoveredState.newzbinSessId = attrs.get('newzbinSessId')

        # <downloading id="10" isParRecovery="true" name="Archive 3"/>
        # <processing id="4" rarPassword="sup" deleteProcessed="true" skipUnrar="true"
        #    overwriteZeroByteFiles="true" keepDupes="true" destSubDir="?"
        #    nzbFile="Archive_0.nzb" name="Archive 0"/>
        #          <skippedPar>Subject Line vol02+01.par2</skippedPar>
        # </processing>
        # <queued id="3" name="Archive 1"/>
        elif name in ('downloading', 'processing', 'queued'):
            currentAttrs = dict(attrs.items())

            # We'll lose the queued order while it's in the recoveredState dict. Tally the
            # order in its attributes and sort by it later
            if name == 'queued':
                currentAttrs['order'] = len(Hellanzb.recoveredState.queued)
                
            archiveName = currentAttrs['name']
            currentAttrs['id'] = int(currentAttrs['id'])
            IDPool.skipIds.append(currentAttrs['id'])
            
            typeDict = getattr(Hellanzb.recoveredState, name)
            if currentAttrs is not None:
                typeDict[archiveName] = currentAttrs

            self.currentAttrs = currentAttrs
                
        elif name == 'skippedPar':
            if self.currentAttrs.has_key('skippedParSubjects'):
                self.skippedParSubjects = self.currentAttrs['skippedParSubjects']
            else:
                self.skippedParSubjects = self.currentAttrs['skippedParSubjects'] = []

    def characters(self, content):
        if self.currentTag == 'skippedPar':
            self.skippedParContent += content

    def endElement(self, name):
        if self.currentTag == 'skippedPar':
            self.skippedParSubjects.append(self.skippedParContent)
            self.skippedParContent = ''
        else:
            self.currentAttrs = None
        self.currentTag = None

class RecoveredState(object):
    """ Data recovered from the on disk STATE_XML_FILE """
    def __init__(self):
        # These are maps of the archive name (the XML tag's content) to their
        # attributes. These will later be resynced to their associated objects
        self.downloading, self.processing, self.queued = {}, {}, {}
        
        self.version = None
        self.newzbinSessId = None

    def getRecoveredDict(self, type, archiveName):
        """ Attempt to recover attributes (dict) from the STATE_XML_FILE read from disk for the
        specified archiveName of the specified type (valid types: downloading, processing,
        queued) """
        typeDict = getattr(self, type)

        archiveName = toUnicode(archiveName)
        recoveredDict = None
        if archiveName in typeDict:
            recoveredDict = typeDict[archiveName]
            typeDict.pop(archiveName) # Done with it

        return recoveredDict

    def __str__(self):
        data = 'RecoveredState: version: %s newzbinSessId %s\ndownloading: %s\n' + \
            'processing: %s\nqueued: %s'
        data = data % (self.version, self.newzbinSessId, str(self.downloading),
             str(self.processing), str(self.queued))
        return data
        
def scanQueueDir(firstRun = False, justScan = False):
    """ Find new/resume old NZB download sessions """
    #t = time.time()

    from Hellanzb.NZBLeecher.NZBModel import NZB
    current_nzbs = []
    for file in os.listdir(Hellanzb.CURRENT_DIR):
        if Hellanzb.NZB_FILE_RE.search(file):
            current_nzbs.append(Hellanzb.CURRENT_DIR + os.sep + file)

    # See if we're resuming a nzb fetch
    resuming = False
    displayNotification = False
    new_nzbs = []
    queuedMap = {}
    for nzb in Hellanzb.queued_nzbs:
        queuedMap[os.path.normpath(nzb.nzbFileName)] = nzb

    for file in os.listdir(Hellanzb.QUEUE_DIR):
        if Hellanzb.NZB_FILE_RE.search(file) and \
            os.path.normpath(Hellanzb.QUEUE_DIR + os.sep + file) not in queuedMap:
            new_nzbs.append(Hellanzb.QUEUE_DIR + os.sep + file)
            
        elif os.path.normpath(Hellanzb.QUEUE_DIR + os.sep + file) in queuedMap:
            queuedMap.pop(os.path.normpath(Hellanzb.QUEUE_DIR + os.sep + file))

    # Remove anything no longer in the queue directory
    for nzb in queuedMap.itervalues():
        Hellanzb.queued_nzbs.remove(nzb)

    if firstRun:
        # enqueueNZBs() will delete the recovered state. Save it beforehand for sorting
        queuedRecoveredState = Hellanzb.recoveredState.queued.copy()

    enqueueNZBs(new_nzbs, writeQueue = not firstRun)
            
    if firstRun:
        sortQueueFromRecoveredState(queuedRecoveredState)

    #e = time.time() - t
    if justScan:
        # Done scanning -- don't bother loading a new NZB
        #debug('Ziplick scanQueueDir (justScan): ' + Hellanzb.QUEUE_DIR + ' TOOK: ' + str(e))
        debug('Ziplick scanQueueDir (justScan): ' + Hellanzb.QUEUE_DIR)
        Hellanzb.downloadScannerID = reactor.callLater(7, scanQueueDir, False, True)
        return
    else:
        debug('Ziplick scanQueueDir: ' + Hellanzb.QUEUE_DIR)

    if not current_nzbs:
        if not Hellanzb.queued_nzbs or Hellanzb.downloadPaused:
            if firstRun:
                writeStateXML()

            # Nothing to do, lets wait 5 seconds and start over
            Hellanzb.downloadScannerID = reactor.callLater(5, scanQueueDir)
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
        nzb = NZB.fromStateXML('downloading', nzbfilename)
        
        nzbfilename = os.path.basename(nzb.nzbFileName)
        displayNotification = True
        del current_nzbs[0]
        resuming = True

    nzbfile = Hellanzb.CURRENT_DIR + os.sep + nzbfilename
    nzb.nzbFileName = nzbfile

    if firstRun:
        writeStateXML()

    if resuming:
        parseNZB(nzb, 'Resuming')
    elif displayNotification:
        parseNZB(nzb)
    else:
        parseNZB(nzb, quiet = True)

def sortQueueFromRecoveredState(queuedRecoveredState):
    """ Sort the queue from the order recovered from the on disk STATE_XML_FILE """
    onDiskQueue = [(archiveEntry['order'], archiveName) for archiveName, archiveEntry in \
                   queuedRecoveredState.iteritems()]
    onDiskQueue.sort()
    
    unsorted = Hellanzb.queued_nzbs[:]
    Hellanzb.queued_nzbs = []
    arranged = []
    for order, archiveName in onDiskQueue:
        for nzb in unsorted:
            if nzb.archiveName == archiveName:
                Hellanzb.queued_nzbs.append(nzb)
                arranged.append(nzb)
                break
    for nzb in arranged:
        unsorted.remove(nzb)
    for nzb in unsorted:
        Hellanzb.queued_nzbs.append(nzb)
            
def recoverStateFromDisk():
    """ Load hellanzb state from the on disk XML """
    Hellanzb.recoveredState = RecoveredState()
    if os.path.isfile(Hellanzb.STATE_XML_FILE):
        # Create a parser
        parser = make_parser()

        # No XML namespaces here
        parser.setFeature(feature_namespaces, 0)
        parser.setFeature(feature_external_ges, 0)

        # Tell the parser to use it
        parser.setContentHandler(HellanzbStateXMLParser())

        # Parse the input
        try:
            parser.parse(Hellanzb.STATE_XML_FILE)
        except SAXParseException, saxpe:
            debug('Unable to parse Invalid NZB QUEUE LIST: ' + Hellanzb.STATE_XML_FILE)
            return None
        
        debug('recoverStateFromDisk recovered: %s' % str(Hellanzb.recoveredState))

        if Hellanzb.recoveredState.newzbinSessId is not None and \
                not NewzbinDownloader.cookies.get('PHPSESSID'):
            NewzbinDownloader.cookies['PHPSESSID'] = Hellanzb.recoveredState.newzbinSessId

def _writeStateXML(outFile):
    """ Write portions of hellanzb's state to an XML file on disk. This includes queued NZBs
    and their order in the queue, and smart par recovery information """
    writer = XMLWriter(outFile, 'utf-8', indent = 8)
    writer.declaration()
    
    hAttribs = {'version': Hellanzb.version}
    if NewzbinDownloader.cookies.get('PHPSESSID') is not None:
        hAttribs['newzbinSessId'] = NewzbinDownloader.cookies['PHPSESSID']
        
    h = writer.start('hellanzbState', hAttribs)
    
    for container in (Hellanzb.queue.currentNZBs(), Hellanzb.postProcessors,
                      Hellanzb.queued_nzbs):
        for item in container:
            item.toStateXML(writer)

    writer.close(h)
    #writer.comment('Generated @ %s' % time.strftime("%a, %d %b %Y %H:%M:%S %Z",
    #                                                time.localtime()))

    # Delete the recoveredState data -- done with it
    Hellanzb.recoveredState = RecoveredState() 
Hellanzb._writeStateXML = _writeStateXML

def writeStateXML():
    """ Write hellanzb's state to the STATE_XML_FILE atomically """
    file = Hellanzb.STATE_XML_FILE
    def backupThenWrite():
        if os.path.exists(file):
            move(file, file + '.bak')
            outFile = open(file, 'w')
            _writeStateXML(outFile)
            outFile.close()

    if inMainThread():
        backupThenWrite()
    else:
        reactor.callFromThread(backupThenWrite)
Hellanzb.writeStateXML = writeStateXML
    
def parseNZB(nzb, notification = 'Downloading', quiet = False):
    """ Parse the NZB file into the Queue. Unless the NZB file is deemed already fully
    processed at the end of parseNZB, tell the factory to start downloading it """
    if not quiet:
        info(notification + ': ' + nzb.archiveName)
        growlNotify('Queue', 'hellanzb ' + notification + ':', nzb.archiveName,
                    False)

    try:
        findAndLoadPostponedDir(nzb)
        
        info('Parsing: ' + os.path.basename(nzb.nzbFileName) + '...')
        if not Hellanzb.queue.parseNZB(nzb):
            Hellanzb.Daemon.beginDownload()

    except FatalError, fe:
        error('Problem while parsing the NZB', fe)
        growlNotify('Error', 'hellanzb', 'Problem while parsing the NZB: ' + prettyException(fe),
                    True)
        error('Moving bad NZB out of queue into TEMP_DIR: ' + Hellanzb.TEMP_DIR)
        move(nzb.nzbFileName, Hellanzb.TEMP_DIR + os.sep)
        reactor.callLater(5, scanQueueDir)

def ensureSafePostponedLoad(nzbFileName):
    """ Force doesn't immediately abort the download of the forced out NZB -- it lets the
    NZBLeechers currently working on them finish. We need to be careful of forced NZBs
    that are so small, that they finish downloading before these 'slower' NZBLeechers are
    even done with the previous, forced out NZB. The parseNZB function could end up
    colliding with the leechers, while parseNZB looks for segments on disk/to be skipped
    """
    # Look for any NZBLeechers downloading files for the specified unpostponed NZB. They
    # are most likely left over from a force call, using a very small NZB.
    shouldCancel = False
    cancelledClients = []
    for nsf in Hellanzb.nsfs:
        for nzbl in nsf.clients:
            if nzbl.currentSegment != None and os.path.basename(nzbl.currentSegment.nzbFile.nzb.nzbFileName) == \
                    os.path.basename(nzbFileName):
                # the easiest way to prevent weird things from happening (such as the
                # parser getting confused about what needs to be downloaded/skipped) is to
                # just pull the trigger on those slow NZBLeechers connections --
                # disconnect them and ensure the segments they were trying to download
                # aren't requeued
                debug('%s Aborting/Disconnecting to ensure safe postponed NZB load' % str(nzbl))
                shouldCancel = True
                nzbl.currentSegment.dontRequeue = True
                cancelledClients.append(nzbl)

                # Can't recall the details of why we should manually loseConnection(), do
                # isLoggedIn and also deactivate() below -- but this is was
                # cancelCurrent() does
                nzbl.transport.loseConnection()
                nzbl.isLoggedIn = False
                
                if nzbl.currentSegment is not None and \
                        nzbl.currentSegment.encodedData is not None:
                    try:
                        name = nzbl.currentSegment.getTempFileName() + '_ENC'
                        debug('%s Closing encodedData file: %s' % (str(nzbl), name))
                        nzbl.currentSegment.encodedData.close()
                        debug('%s Closed encodedData file' % str(nzbl))
                    except Exception, e:
                        debug('%s Error while closing encodedData file' % str(nzbl), e)
                        pass

    if shouldCancel:
        # Also reset the state of the queue if we had to do any cleanup
        Hellanzb.queue.cancel()

        for nzbl in cancelledClients:
            nzbl.deactivate()
        
def findAndLoadPostponedDir(nzb):
    """ Move a postponed working directory for the specified nzb, if one is found, to the
    WORKING_DIR """
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

        ensureSafePostponedLoad(nzb.nzbFileName)
        
        info('Loaded postponed directory: ' + archiveName(nzbfilename))

        fixNZBFileName(nzb)
        return True
    else:
        fixNZBFileName(nzb)
        return False

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
    writeStateXML()
    return True

def moveDown(nzbId, shift = 1):
    """ move the specified nzb down in the queue """
    return moveUp(nzbId, shift, moveDown = True)

def dequeueNZBs(nzbIdOrIds, quiet = False):
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
        msg = 'Dequeueing: %s' % (nzb.archiveName)
        if os.path.isdir(Hellanzb.POSTPONED_DIR + os.sep + nzb.archiveName):
            msg = '%s%s' % (msg, ' (archive has a postponed dir)')
            warn(msg)
        elif not quiet:
            info(msg)
        move(nzb.nzbFileName, Hellanzb.TEMP_DIR + os.sep + os.path.basename(nzb.nzbFileName))
        Hellanzb.queued_nzbs.remove(nzb)
        
    writeStateXML()
    return not error

def enqueueNZBStr(nzbFilename, nzbStr):
    """ Write the specified NZB file (in string format) to disk and enqueue it """
    # FIXME: could use a tempfile.TempFile here (NewzbinDownloader could use it also)
    tempLocation = Hellanzb.TEMP_DIR + os.sep + os.path.basename(nzbFilename)
    if os.path.exists(tempLocation):
        if not os.access(tempLocation, os.W_OK):
            error('Unable to write NZB to temp location: ' + tempLocation)
            return
        
        rmtree(tempLocation)

    f = open(tempLocation, 'w')
    f.writelines(nzbStr)
    f.close()

    enqueueNZBs(tempLocation)
    os.remove(tempLocation)
    
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
                    error('Unable to add nzb file to queue: ' + os.path.basename(nzbFile) + \
                          ' it already exists!')
            if found:
                continue

            from Hellanzb.NZBLeecher.NZBModel import NZB
            name = os.path.basename(nzbFile)
            nzb = NZB.fromStateXML('queued', nzbFile)
            
            if not next:
                Hellanzb.queued_nzbs.append(nzb)
            else:
                Hellanzb.queued_nzbs.insert(0, nzb)

            msg = 'Found new nzb: '
            info(msg + archiveName(nzbFile))
            growlNotify('Queue', 'hellanzb ' + msg, archiveName(nzbFile), False)
                
    if writeQueue:
        writeStateXML()
            
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
        return True

    Hellanzb.queued_nzbs.remove(foundNZB)
    Hellanzb.queued_nzbs.insert(0, foundNZB)

    writeStateXML()
    return True

def lastNZB(nzbId):
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
        return True
    
    Hellanzb.queued_nzbs.remove(foundNZB)
    Hellanzb.queued_nzbs.append(foundNZB)

    writeStateXML()
    return True

def moveNZB(nzbId, index):
    try:
        nzbId = int(nzbId)
    except:
        debug('Invalid ID: ' + str(nzbId))
        return False
    try:
        index = int(index)
    except:
        debug('Invalid INDEX: ' + str(index))
        return False

    foundNZB = None
    for nzb in Hellanzb.queued_nzbs:
        if nzb.id == nzbId:
            foundNZB = nzb
            
    if not foundNZB:
        return True
    
    Hellanzb.queued_nzbs.remove(foundNZB)
    Hellanzb.queued_nzbs.insert(index - 1, foundNZB)

    writeStateXML()
    return True

def listQueue(includeIds = True, convertToUnicode = True):
    """ Return a listing of the current queue. By default this function will convert all
    strings to unicode, as it's only used right now for the return of XMLRPC calls """
    members = []
    for nzb in Hellanzb.queued_nzbs:
        if includeIds:
            name = archiveName(os.path.basename(nzb.nzbFileName))
            rarPassword = nzb.rarPassword
            
            if convertToUnicode:
                name = toUnicode(name)
                rarPassword = toUnicode(rarPassword)
                
            member = {'id': nzb.id,
                      'nzbName': name}
            
            if rarPassword != None:
                member['rarPassword'] = rarPassword
        else:
            member = os.path.basename(nzb.nzbFileName)
        members.append(member)
    return members
    
"""
/*
 * Copyright (c) 2005 Philip Jenvey <pjenvey@groovie.org>
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
