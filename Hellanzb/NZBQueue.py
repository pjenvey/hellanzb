"""

NZBQueue - Maintains NZB files queued to be downloaded in the future

These are all module level functions that operate on the main Hellanzb queue, which is at
Hellanzb.queued_nzbs (FIXME)

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
from Hellanzb.Util import IDPool, archiveName, hellaRename, getFileExtension, toUnicode, \
    validNZB

__id__ = '$Id$'

class NZBQueueParser(ContentHandler):
    """ Loads the on disk QUEUE_LIST into an NZBQueueRecovered object """
    def __init__(self):
        Hellanzb.nzbQueueRecovered = NZBQueueRecovered()

        self.currentTag = None
        self.currentAttrs = None
        self.extraParContent = ''
        
    def startElement(self, name, attrs):
        self.currentTag = name
        # <hellanzb newzbinSessId="8f9c7badc62a5d5f776d810f0498cde1" version="0.9-trunk">
        if name == 'hellanzb':
            Hellanzb.nzbQueueRecovered.version = attrs.get('version')
            Hellanzb.nzbQueueRecovered.newzbinSessId = attrs.get('newzbinSessId')

        # <downloading id="10" isParRecovery="true">Archive 3</downloading>
        # <processing id="4" rarPassword="sup" deleteProcessed="true" skipUnrar="true"
        #    overwriteZeroByteFiles="true" keepDupes="true" destSubDir="?"
        #    nzbFile="Archive_0.nzb">Archive 0</processing>
        # <queued id="3" order="1">Archive 1</queued>
        elif name in ('downloading', 'processing', 'queued'):
            #self.currentAttrs = dict(attrs.items())
            currentAttrs = dict(attrs.items())
            archiveName = currentAttrs['name']
            currentAttrs['id'] = int(currentAttrs['id'])
            IDPool.skipIds.append(currentAttrs['id'])
            
            typeDict = getattr(Hellanzb.nzbQueueRecovered, name)
            if currentAttrs is not None:
                typeDict[archiveName] = currentAttrs

            self.currentAttrs = currentAttrs
                
        elif name == 'extraPar':
            if self.currentAttrs.has_key('extraPars'):
                self.extraPars = self.currentAttrs['extraPars']
            else:
                self.extraPars = self.currentAttrs['extraPars'] = []

    def characters(self, content):
        """
        if self.currentTag in ('downloading', 'processing', 'queued'):
            typeDict = getattr(Hellanzb.nzbQueueRecovered, self.currentTag)
            if self.currentAttrs is not None:
                typeDict[content] = self.currentAttrs
                self.currentAttrs = None
                """
        if self.currentTag == 'extraPar':
            self.extraParContent += content

    def endElement(self, name):
        if self.currentTag == 'extraPar':
            self.extraPars.append(self.extraParContent)
            self.extraParContent = ''
        self.currentTag = None
        self.currentAttrs = None

class NZBQueueRecovered(object):
    """ Data recovered from the on disk QUEUE_LIST """
    def __init__(self):
        # These are maps of the archive name (the XML tag's content) to their
        # attributes. These will later be resynced to their associated objects
        self.downloading, self.processing, self.queued = {}, {}, {}
        
        self.version = None
        self.newzbinSessId = None

    def __str__(self):
        data = 'NZBQueueRecovered: version: %s newzbinSessId %s\ndownloading: %s\n' + \
            'processing: %s\nqueued: %s'
        data = data % (self.version, self.newzbinSessId, str(self.downloading),
             str(self.processing), str(self.queued))
        return data
        
def scanQueueDir(firstRun = False, justScan = False):
    """ Find new/resume old NZB download sessions """
    t = time.time()

    from Hellanzb.NZBLeecher.NZBModel import NZB
    current_nzbs = []
    for file in os.listdir(Hellanzb.CURRENT_DIR):
        if re.search(r'(?i)\.(nzb|xml)$', file):
            current_nzbs.append(Hellanzb.CURRENT_DIR + os.sep + file)

    # See if we're resuming a nzb fetch
    resuming = False
    displayNotification = False
    new_nzbs = []
    queuedMap = {}
    for nzb in Hellanzb.queued_nzbs:
        queuedMap[os.path.normpath(nzb.nzbFileName)] = nzb

    for file in os.listdir(Hellanzb.QUEUE_DIR):
        if re.search(r'(?i)\.(nzb|xml)$', file) and \
            os.path.normpath(Hellanzb.QUEUE_DIR + os.sep + file) not in queuedMap:
            new_nzbs.append(Hellanzb.QUEUE_DIR + os.sep + file)
            
        elif os.path.normpath(Hellanzb.QUEUE_DIR + os.sep + file) in queuedMap:
            queuedMap.pop(os.path.normpath(Hellanzb.QUEUE_DIR + os.sep + file))

    # Remove anything no longer in the queue directory
    for nzb in queuedMap.itervalues():
        Hellanzb.queued_nzbs.remove(nzb)

    enqueueNZBs(new_nzbs, writeQueue = not firstRun)
            
    if firstRun:
        sortQueueFromDisk()

    e = time.time() - t
    if justScan:
        # Done scanning -- don't bother loading a new NZB
        debug('Ziplick scanQueueDir (justScan): ' + Hellanzb.QUEUE_DIR + ' TOOK: ' + str(e))
        Hellanzb.downloadScannerID = reactor.callLater(7, scanQueueDir, False, True)
        return
    else:
        debug('Ziplick scanQueueDir: ' + Hellanzb.QUEUE_DIR)

    if not current_nzbs:
        if not Hellanzb.queued_nzbs or Hellanzb.downloadPaused:
            if firstRun:
                writeQueueToDisk()

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
        
        nzbId = None
        #recovered = recoverFromOnDiskQueue(os.path.basename(nzbfilename), 'downloading')
        recovered = recoverFromOnDiskQueue(archiveName(nzbfilename), 'downloading')
        extraPars = None
        if recovered:
            nzbId = recovered['id']
            extraPars = recovered.get('extraPars') 
        nzb = NZB(nzbfilename, nzbId)
        syncFromRecovery(nzb, recovered)
        if extraPars:
            nzb.extraParNamesList = extraPars
        
        nzbfilename = os.path.basename(nzb.nzbFileName)
        displayNotification = True
        del current_nzbs[0]
        resuming = True

    nzbfile = Hellanzb.CURRENT_DIR + os.sep + nzbfilename
    nzb.nzbFileName = nzbfile

    if firstRun:
        writeQueueToDisk()

    if resuming:
        parseNZB(nzb, 'Resuming')
    elif displayNotification:
        parseNZB(nzb)
    else:
        parseNZB(nzb, quiet = True)

def sortQueueFromDisk():
    """ Sort the queue from the order recovered from the on disk QUEUE_LIST """
    onDiskQueue = [(archiveEntry['order'], archiveName) for archiveName, archiveEntry in \
                   Hellanzb.nzbQueueRecovered.queued.iteritems()]
    onDiskQueue.sort()
    
    unsorted = Hellanzb.queued_nzbs[:]
    Hellanzb.queued_nzbs = []
    arranged = []
    for order, archiveName in onDiskQueue:
        for nzb in unsorted:
            if os.path.basename(nzb.nzbFileName) == archiveName:
                Hellanzb.queued_nzbs.append(nzb)
                arranged.append(nzb)
                break
    for nzb in arranged:
        unsorted.remove(nzb)
    for nzb in unsorted:
        Hellanzb.queued_nzbs.append(nzb)
            
def loadQueueFromDisk():
    """ Load the queue from disk """
    Hellanzb.nzbQueueRecovered = NZBQueueRecovered()
    if os.path.isfile(Hellanzb.QUEUE_LIST):
        # Create a parser
        parser = make_parser()

        # No XML namespaces here
        parser.setFeature(feature_namespaces, 0)
        parser.setFeature(feature_external_ges, 0)

        # Tell the parser to use it
        parser.setContentHandler(NZBQueueParser())

        # Parse the input
        try:
            parser.parse(Hellanzb.QUEUE_LIST)
        except SAXParseException, saxpe:
            debug('Unable to parse Invalid NZB QUEUE LIST: ' + Hellanzb.QUEUE_LIST)
            return None
        
        debug('loadQueueFromDisk recovered: %s' % str(Hellanzb.nzbQueueRecovered))

        if Hellanzb.nzbQueueRecovered.newzbinSessId is not None and \
                not NewzbinDownloader.cookies.get('PHPSESSID'):
            NewzbinDownloader.cookies['PHPSESSID'] = Hellanzb.nzbQueueRecovered.newzbinSessId

def writeQueueToDisk():
    """ Write the queue to disk """
    # FIXME: rename either use of 'attrs' or 'attribs' to the other one
    def itemAttribs(item, extraAttribs = ()):
        attribs = getQueueAttribs(item)
        for extraAttrib in extraAttribs:
            extraAttribVal = getattr(item, extraAttrib)
            if extraAttribVal is not None:
                attribs[extraAttrib] = unicode(extraAttribVal)
        return attribs

    # FIXME: don't need extraTtribs
    """
    def itemsToXML(xmlWriter, items, type, extraAttribs = ()):
        for item in items:
            attribs = itemAttribs(item, extraAttribs)
            #d = xmlWriter.element(type, item.getName(), attribs)
            xmlWriter.element(type, None, attribs)
            """
    
    queueListFile = open(Hellanzb.QUEUE_LIST, 'w')

    writer = XMLWriter(queueListFile, 'utf-8', indent = 8)
    writer.declaration()
    
    hAttribs = {'version': Hellanzb.version}
    if NewzbinDownloader.cookies.get('PHPSESSID') != None:
        hAttribs['newzbinSessId'] = NewzbinDownloader.cookies['PHPSESSID']
    h = writer.start('hellanzb', hAttribs)

    #itemsToXML(writer, Hellanzb.queue.currentNZBs(), 'downloading', ('isParRecovery',))
    for currentNZB in Hellanzb.queue.currentNZBs():
        attribs = itemAttribs(currentNZB)
        if currentNZB.isParRecovery:
            attribs['isParRecovery'] = 'True'
            for attrib in ('neededBlocks', 'parType', 'parPrefix'):
                attribs[attrib] = getattr(currentNZB, attrib)
        writer.start('downloading', attribs)
        if currentNZB.isParRecovery:
            if currentNZB.extraParNamesList is not None:
                for nzbFileName in currentNZB.extraParNamesList:
                    writer.element('extraPar', nzbFileName)
            else:
                for nzbFile in currentNZB.nzbFileElements:
                    if nzbFile.isExtraParFile:
                        writer.element('extraPar', nzbFile.subject)
        #xmlWriter.element('downloading', None, attribs)
        writer.end('downloading')
        
    #itemsToXML(writer, Hellanzb.postProcessors, 'processing',
    #           extraAttribs = ('nzbFileName',))
    for processor in Hellanzb.postProcessors:
        #attribs = itemAttribs(processor, extraAttribs = ('nzbFileName',))
        attribs = itemAttribs(processor)
        if processor.isNZBArchive():
            attribs['nzbFileName'] = archiveName(processor.archive.nzbFileName,
                                                 unformatNewzbinNZB = False)
        writer.start('processing', attribs)
        #writer.data
        #xmlWriter.element('processing', item.getName(), attribs)
        ##writer.element('processing', None, attribs)
        if processor.isNZBArchive():
            if processor.archive.extraParNamesList is not None:
                for nzbFileName in processor.archive.extraParNamesList:
                    writer.element('extraPar', nzbFileName)
            else:
                for nzbFile in processor.archive.nzbFileElements:
                    if nzbFile.isExtraParFile:
                        writer.element('extraPar', nzbFile.subject)
                    
        #writer.element('extra-par', )
        writer.end('processing')

    i = 0
    for queued in Hellanzb.queued_nzbs:
        i += 1
        attribs = getQueueAttribs(queued)
        # FIXME: order isn't needed, is it?
        #attribs['order'] = str(i)
        attribs['order'] = unicode(i)
        #d = writer.element('queued', queued.getName(), attribs)
        writer.element('queued', None, attribs)

    writer.comment('Generated @ %s FIXME: rename hellanzb tag to something else' % 'time')
    writer.close(h)
    queueListFile.close()

    # We should be done with the NZBQueueRecovered data -- clean it out
    Hellanzb.nzbQueueRecovered = NZBQueueRecovered() 

def getQueueAttribs(item):
    """ Return a dict of attributes to be written to the on disk XML queue. Takes into account
    the attribute defaults """
    class Required: pass
    # All queue attributes and their defaults
    QUEUE_ATTRIBS = {'rarPassword': None,
                     'id': Required}
    
    attribs = {}
    for attribName, default in QUEUE_ATTRIBS.iteritems():
        val = getattr(item, attribName)
        # Only write to XML required values and values that do not match their defaults
        if default == Required or val != default:
            #attribs[attribName] = str(val)
            attribs[attribName] = unicode(val)
    attribs['name'] = item.getName()
    return attribs

def recoverFromOnDiskQueue(archiveName, type):
    """ Attempt to recover attributes (dict) from the QUEUE_LIST read from disk for the
    specified archiveName of the specified type (valid types: downloading, processing,
    queued) """
    typeDict = getattr(Hellanzb.nzbQueueRecovered, type)
    
    recovered = None
    if archiveName in typeDict:
        recovered = typeDict[archiveName]
        typeDict.pop(archiveName) # Done with it

    return recovered

def syncFromRecovery(obj, recovered):
    """ Copy the attributes from the specified recovered dict to the specified object """
    if recovered:
        for key, value in recovered.iteritems():
            if key == 'id':
                value = int(value)
            setattr(obj, key, value)
        
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
            writeQueueToDisk()
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
     colliding with the leechers, while pareseNZB looks for segments on disk/to be skipped
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
                debug('Aborting/Disconnecting %s to ensure safe postponed NZB load' % str(nzbl))
                shouldCancel = True
                nzbl.currentSegment.dontRequeue = True
                cancelledClients.append(nzbl)

                # Can't recall the details of why we should manually loseConnection(), do
                # isLoggedIn and also deactivate() below -- but this is was
                # cancelCurrent() does
                nzbl.transport.loseConnection()
                nzbl.isLoggedIn = False

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
    writeQueueToDisk()
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
        if not quiet:
            info('Dequeueing: ' + nzb.archiveName)
        move(nzb.nzbFileName, Hellanzb.TEMP_DIR + os.sep + os.path.basename(nzb.nzbFileName))
        Hellanzb.queued_nzbs.remove(nzb)
        
    writeQueueToDisk()
    return not error

def enqueueNZBStr(nzbFilename, nzbStr):
    """ Write the specified NZB file (in string format) to disk and enqueue it """
    tempLocation = Hellanzb.TEMP_DIR + os.sep + nzbFilename
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
            nzbId = None
            
            #recovered = recoverFromOnDiskQueue(name, 'queued')
            recovered = recoverFromOnDiskQueue(archiveName(name), 'queued')
            if recovered:
                nzbId = recovered['id']
            nzb = NZB(nzbFile, nzbId)
            syncFromRecovery(nzb, recovered)
            
            if not next:
                Hellanzb.queued_nzbs.append(nzb)
            else:
                Hellanzb.queued_nzbs.insert(0, nzb)

            msg = 'Found new nzb: '
            info(msg + archiveName(nzbFile))
            growlNotify('Queue', 'hellanzb ' + msg, archiveName(nzbFile), False)
                
    if writeQueue:
        writeQueueToDisk()
            
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

    writeQueueToDisk()
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

    writeQueueToDisk()
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

    writeQueueToDisk()
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
