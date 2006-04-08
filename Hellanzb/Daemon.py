"""

Daemon (aka Ziplick) - Filesystem queue daemon functions. They're all called from inside
the twisted reactor loop, except for initialization functions

(c) Copyright 2005 Ben Bangert, Philip Jenvey
[See end of file]
"""
import os, re, sys, time, Hellanzb, PostProcessor, PostProcessorUtil
from shutil import copy, move, rmtree
from twisted.internet import reactor
from twisted.scripts.twistd import daemonize
from Hellanzb.HellaXMLRPC import initXMLRPCServer, HellaXMLRPCServer
from Hellanzb.Log import *
from Hellanzb.Logging import prettyException, LogOutputStream
from Hellanzb.NZBQueue import dequeueNZBs, recoverStateFromDisk, parseNZB, \
    scanQueueDir, writeStateXML
from Hellanzb.Util import archiveName, ensureDirs, getMsgId, hellaRename, prettyElapsed, \
    prettySize, touch, validNZB, IDPool

__id__ = '$Id$'

def ensureDaemonDirs():
    """ Ensure that all the required directories exist and are writable, otherwise attempt to
    create them """
    dirNames = {}
    for arg in dir(Hellanzb):
        if arg.endswith("_DIR") and arg == arg.upper():
            exec 'dirName = Hellanzb.' + arg
            if dirName is None:
                raise FatalError('Required directory not defined in config file: Hellanzb.' + arg)
            dirNames[arg] = dirName
            
    ensureDirs(dirNames)

    if hasattr(Hellanzb, 'QUEUE_LIST'):
        if not hasattr(Hellanzb, 'STATE_XML_FILE'):
            Hellanzb.STATE_XML_FILE = Hellanzb.QUEUE_LIST
    if not hasattr(Hellanzb, 'STATE_XML_FILE'):
        raise FatalError('Hellanzb.STATE_XML_FILE not defined in config file')
    elif os.path.isfile(Hellanzb.STATE_XML_FILE) and not os.access(Hellanzb.STATE_XML_FILE, os.W_OK):
        raise FatalError('hellanzb does not have write access to the Hellanzb.STATE_XML_FILE file')

def ensureCleanDir(dirName):
    """ Nuke and recreate the specified directory """
    # Clear out the old dir and create a fresh one
    if os.path.exists(dirName):
        if not os.access(dirName, os.W_OK):
            raise FatalError('Cannot continue: hellanzb needs write access to ' + dirName)
        
        rmtree(dirName)

    # ensureDaemonDirs already guaranteed us write access to the parent TEMP_DIR
    os.makedirs(dirName)

def ensureCleanDirs():
    """ This must be called just after the XMLRPCServer initialization, thus it's separated
    from ensureDaemonDirs(). We don't want to touch/nuke these kinds of dirs until we know
    we are the only queue daemon running (if we aren't, initXMLRPCServer will throw an
    exception) """
    for var, dirName in {'DOWNLOAD_TEMP_DIR': 'download-tmp',
                         'DEQUEUED_NZBS_DIR': 'dequeued-nzbs'}.iteritems():
        fullPath = Hellanzb.TEMP_DIR + os.sep + dirName
        setattr(Hellanzb, var, fullPath)
        try:
            ensureCleanDir(fullPath)
        except FatalError:
            # del the var so Core.shutdown() does not attempt to rmtree() the dir
            delattr(Hellanzb, var)
            raise

def initDaemon():
    """ Start the daemon """
    Hellanzb.isDaemon = True
    Hellanzb.nzbQueue = []
    Hellanzb.loggedIdleMessage = True

    try:
        ensureDaemonDirs()
        initXMLRPCServer()
        ensureCleanDirs() # needs to be called AFTER initXMLRPCServer
    except FatalError, fe:
        error('Exiting', fe)
        from Hellanzb.Core import shutdownAndExit
        shutdownAndExit(1)

    reactor.callLater(0, info, 'hellanzb - Now monitoring queue...')
    reactor.callLater(0, growlNotify, 'Queue', 'hellanzb', 'Now monitoring queue..', False)
    reactor.callLater(0, recoverStateFromDisk)
    reactor.callLater(0, resumePostProcessors)
    reactor.callLater(0, scanQueueDir, True)

    if Hellanzb.DAEMONIZE:
        daemonize()

    if hasattr(Hellanzb, 'UMASK'):
        # umask here, as daemonize() might have just reset the value
        os.umask(Hellanzb.UMASK)

    if hasattr(Hellanzb, 'HELLAHELLA_CONFIG'):
        initHellaHella(Hellanzb.HELLAHELLA_CONFIG)
    
    from Hellanzb.NZBLeecher import initNZBLeecher, startNZBLeecher
    initNZBLeecher()
    startNZBLeecher()

def initHellaHella(configFile, verbose = False):
    """ Initialize hellahella, the web UI """
    Hellanzb.HELLAHELLA_PORT = 8750
    try:
        from paste.deploy import loadapp
        from twisted.web2.server import Request
        def _parseURL(self):
            if self.uri[0] == '/':
                # Can't use urlparse for request_uri because urlparse
                # wants to be given an absolute or relative URI, not just
                # an abs_path, and thus gets '//foo' wrong.
                self.scheme = self.host = self.path = self.params = self.querystring = ''
                if '?' in self.uri:
                    self.path, self.querystring = self.uri.split('?', 1)
                else:
                    self.path = self.uri
                if ';' in self.path:
                    self.path, self.params = self.path.split(';', 1)
            else:
                # It is an absolute uri, use standard urlparse
                (self.scheme, self.host, self.path,
                 self.params, self.querystring, fragment) = urlparse.urlparse(self.uri)

            if self.querystring:
                self.args = cgi.parse_qs(self.querystring, True)
            else:
                self.args = {}

            ####path = map(unquote, self.path[1:].split('/'))
            path = self.path[1:].split('/')
            if self._initialprepath:
                # We were given an initial prepath -- this is for supporting
                # CGI-ish applications where part of the path has already
                # been processed
                ####prepath = map(unquote, self._initialprepath[1:].split('/'))
                prepath = self._initialprepath[1:].split('/')

                if path[:len(prepath)] == prepath:
                    self.prepath = prepath
                    self.postpath = path[len(prepath):]
                else:
                    self.prepath = []
                    self.postpath = path
            else:
                self.prepath = []
                self.postpath = path

        Request._parseURL = _parseURL
        
        from twisted.application.service import Application
        from twisted.web2.http import HTTPFactory
        from twisted.web2.log import LogWrapperResource, DefaultCommonAccessLoggingObserver
        from twisted.web2.server import Site
        from twisted.web2.wsgi import FileWrapper, InputStream, ErrorStream, WSGIHandler, \
            WSGIResource

        # Munge the SCRIPT_NAME to '' when web2 makes it '/'
        from twisted.web2.twcgi import createCGIEnvironment
        def setupEnvironment(self, ctx, request):
            # Called in IO thread
            env = createCGIEnvironment(ctx, request)
            if re.compile('\/+').search(env['SCRIPT_NAME']):
                env['SCRIPT_NAME'] = ''
            env['wsgi.version']      = (1, 0)
            env['wsgi.url_scheme']   = env['REQUEST_SCHEME']
            env['wsgi.input']        = InputStream(request.stream)
            env['wsgi.errors']       = ErrorStream()
            env['wsgi.multithread']  = True
            env['wsgi.multiprocess'] = True
            env['wsgi.run_once']     = False
            env['wsgi.file_wrapper'] = FileWrapper
            self.environment = env

        WSGIHandler.setupEnvironment = setupEnvironment

        # incase pylons raises deprecation warnings during loadapp, redirect them to the
        # debug log
        oldStderr = sys.stderr
        sys.stderr = LogOutputStream(debug)

        # Load the wsgi app via paste
        wsgiApp = loadapp('config:' + configFile)

        sys.stderr = oldStderr

        if verbose:
            lwr = LogWrapperResource(WSGIResource(wsgiApp))
            DefaultCommonAccessLoggingObserver().start()
            Hellanzb.hhHTTPFactory = HTTPFactory(Site(lwr))
        else:
            Hellanzb.hhHTTPFactory = HTTPFactory(Site(WSGIResource(wsgiApp)))

        reactor.listenTCP(Hellanzb.HELLAHELLA_PORT, Hellanzb.hhHTTPFactory)
    except Exception, e:
        error('Unable to load hellahella', e)

def resumePostProcessors():
    """ Pickup left off Post Processors that were cancelled via CTRL-C """
    # FIXME: with the new queue, could kill the processing dir sym links (for windows)
    from Hellanzb.NZBLeecher.NZBModel import NZB
    for archiveDirName in os.listdir(Hellanzb.PROCESSING_DIR):
        if archiveDirName[0] == '.':
            continue
        
        archive = NZB.fromStateXML('processing', archiveDirName)
        troll = PostProcessor.PostProcessor(archive)

        info('Resuming post processor: ' + archiveName(archiveDirName))
        troll.start()

def beginDownload(nzb = None):
    """ Initialize the download. Notify the downloaders to begin their work, etc """
    # BEGIN
    Hellanzb.loggedIdleMessage = False
    writeStateXML()
    now = time.time()
    if nzb:
        nzb.downloadStartTime = now
    
    # The scroll level will flood the console with constantly updating
    # statistics -- the logging system can interrupt this scroll
    # temporarily (after scrollBegin)
    scrollBegin()

    # Scan the queue dir intermittently during downloading. Reset the scanner delayed call
    # if it's already going
    if Hellanzb.downloadScannerID is not None and \
            not Hellanzb.downloadScannerID.cancelled and \
            not Hellanzb.downloadScannerID.called:
        Hellanzb.downloadScannerID.cancel()
    Hellanzb.downloadScannerID = reactor.callLater(5, scanQueueDir, False, True)
    
    for nsf in Hellanzb.nsfs:
        nsf.beginDownload()
                
    Hellanzb.scroller.started = True
    Hellanzb.scroller.killedHistory = False

def endDownload():
    """ Finished downloading """
    Hellanzb.totalSpeed = 0
    Hellanzb.scroller.currentLog = None

    scrollEnd()

    Hellanzb.downloadScannerID.cancel()
    Hellanzb.totalArchivesDownloaded += 1
    writeStateXML()
    # END

def handleNZBDone(nzb):
    """ Hand-off from the downloader -- make a dir for the NZB with its contents, then post
    process it in a separate thread"""
    downloadTime = 0
    # Print download statistics when something was downloaded (have an
    # nzb.downloadStartTime). Otherwise we might have simply parsed the NZB and found the
    # archive was assembled (required no downloading)
    if nzb.downloadStartTime:
        downloadTime = time.time() - nzb.downloadStartTime
        speed = nzb.totalReadBytes / 1024.0 / downloadTime
        
        # NOTE: This is now the total time to transfer & fully decode the archive, as
        # opposed to how long to just transfer (which this used to be)
        info('Transferred %s in %s at %.1fKB/s (%s)' % \
             (prettySize(nzb.totalReadBytes), prettyElapsed(downloadTime), speed,
              nzb.archiveName))

    if not nzb.isParRecovery:
        nzb.downloadTime = downloadTime
    else:
        nzb.downloadTime += downloadTime
    
    # Make our new directory, minus the .nzb
    processingDir = Hellanzb.PROCESSING_DIR + nzb.archiveName
    
    # Grab the message id, we'll store it in the processingDir for later use
    msgId = getMsgId(nzb.nzbFileName)

    # Move our nzb contents to their new location for post processing
    hellaRename(processingDir)
        
    move(Hellanzb.WORKING_DIR, processingDir)
    nzb.destDir = processingDir
    nzb.archiveDir = processingDir
    
    move(nzb.nzbFileName, processingDir)
    nzb.nzbFileName = processingDir + os.sep + nzb.nzbFileName
    
    touch(processingDir + os.sep + '.msgid_' + msgId)
    
    os.mkdir(Hellanzb.WORKING_DIR)

    # The list of skipped pars is maintained in the state XML as only the subjects of the
    # nzbFiles. PostProcessor only knows to look at the NZB.skippedParSubjects list,
    # created here
    nzb.skippedParSubjects = nzb.getSkippedParSubjects()

    # Finally unarchive/process the directory in another thread, and continue
    # nzbing
    troll = PostProcessor.PostProcessor(nzb)

    # Give NZBLeecher some time (another reactor loop) to killHistory() & scrollEnd()
    # without any logging interference from PostProcessor
    reactor.callLater(0, troll.start)
    reactor.callLater(0, writeStateXML)
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
        reactor.callLater(0, writeStateXML)

def isActive():
    """ Whether or not we're actively downloading """
    return len(Hellanzb.queue.currentNZBs()) > 0
    
def cancelCurrent():
    """ Cancel the current d/l, remove the nzb. return False if there was nothing to cancel
    """
    if not isActive():
        return True
    
    canceled = False
    for nzb in Hellanzb.queue.currentNZBs():
        # FIXME: should GC here
        canceled = True
        nzb.cancel()
        os.remove(nzb.nzbFileName)
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
            
    writeStateXML()
    reactor.callLater(0, scanQueueDir)
    
    return canceled

def pauseCurrent():
    """ Pause the current download """
    Hellanzb.downloadPaused = True

    for nsf in Hellanzb.nsfs:
        for client in nsf.clients:
            client.transport.stopReading()

    info('Pausing downloader')
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
        info('Continuing downloader (%i connections were reset)' % resetConnections)
    else:
        info('Continuing downloader')

    def redoAssembly(nzbFile):
        nzbFile.tryAssemble()
        nzbFile.interruptedAssembly = False
        
    for nzb in Hellanzb.queue.currentNZBs():
        for nzbFile in nzb.nzbFiles:
            if nzbFile.interruptedAssembly:
                reactor.callInThread(redoAssembly, nzbFile)
    return True

def clearCurrent(andCancel):
    """ Clear the queue -- optionally clear what's currently being downloaded (cancel it) """
    info('Clearing queue')
    dequeueNZBs([nzb.id for nzb in Hellanzb.nzbQueue], quiet = True)
    
    if andCancel:
        cancelCurrent()

    return True

def getRate():
    """ Return the current MAX_RATE value """
    return Hellanzb.ht.readLimit / 1024
    
def maxRate(rate):
    """ Change the MAX_RATE value. Return the new value """
    if rate == 'None' or rate is None:
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
        if Hellanzb.ht.unthrottleReadsID is not None and \
                not Hellanzb.ht.unthrottleReadsID.cancelled and \
                not Hellanzb.ht.unthrottleReadsID.called:
            Hellanzb.ht.unthrottleReadsID.cancel()

        if Hellanzb.ht.checkReadBandwidthID is not None and \
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
                       Hellanzb.nzbQueue):
        for nzbOrArchive in collection:
            if nzbOrArchive.id == nzbId:
                found = nzbOrArchive
                break

    if found:
        found.rarPassword = rarPassword
        writeStateXML()
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
    for nzb in Hellanzb.nzbQueue:
        if nzb.id == nzbId:
            foundNZB = nzb
            
    if not foundNZB:
        return False
    
    forceNZB(foundNZB.nzbFileName)

def forceNZB(nzbfilename, notification = 'Forcing download'):
    """ Interrupt the current download, if necessary, to start the specified nzb """
    if not validNZB(nzbfilename):
        return

    if not len(Hellanzb.queue.nzbs):
        # No need to actually 'force'
        from Hellanzb.NZBLeecher.NZBModel import NZB
        return parseNZB(NZB(nzbfilename))

    # postpone the current NZB download
    for nzb in Hellanzb.queue.currentNZBs():
        try:
            postponed = Hellanzb.POSTPONED_DIR + os.sep + nzb.archiveName
            hellaRename(postponed)
            os.mkdir(postponed)
            nzb.destDir = postponed
            info('Interrupting: ' + nzb.archiveName)
            
            move(nzb.nzbFileName, Hellanzb.QUEUE_DIR + os.sep + os.path.basename(nzb.nzbFileName))
            nzb.nzbFileName = Hellanzb.QUEUE_DIR + os.sep + os.path.basename(nzb.nzbFileName)
            Hellanzb.nzbQueue.insert(0, nzb)
            writeStateXML()

            # remove what we've forced with from the old queue, if it exists
            nzb = None
            for n in Hellanzb.nzbQueue:
                if os.path.normpath(n.nzbFileName) == os.path.normpath(nzbfilename):
                    nzb = n
                    
            if nzb is None:
                from Hellanzb.NZBLeecher.NZBModel import NZB
                nzb = NZB(nzbfilename)
            else:
                Hellanzb.nzbQueue.remove(nzb)
    
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
            reactor.callLater(0, parseNZB, nzb, notification)

        except NameError, ne:
            # GC beat us. that should mean there is either a free spot open, or the next
            # nzb in the queue needs to be interrupted????
            debug('forceNZB: NAME ERROR', ne)
            reactor.callLater(0, scanQueueDir)

def forceNZBParRecover(nzb):
    """ Immediately begin (force) downloading recovery blocks (only the nzb.neededBlocks
    amount) for the specified NZB """
    nzb.isParRecovery = True

    if not len(Hellanzb.nzbQueue) and not len(Hellanzb.queue.currentNZBs()):
        new = Hellanzb.CURRENT_DIR + os.sep + os.path.basename(nzb.nzbFileName)
        move(nzb.nzbFileName, new)
        nzb.nzbFileName = new

        # FIXME: Would be nice to include the number of needed recovery blocks in the
        # growl notification this triggers
        if Hellanzb.downloadScannerID is not None and \
                not Hellanzb.downloadScannerID.cancelled and \
                not Hellanzb.downloadScannerID.called:
            Hellanzb.downloadScannerID.cancel()

        nzb.destDir = Hellanzb.WORKING_DIR
        parseNZB(nzb, 'Downloading recovery pars')
    else:
        Hellanzb.nzbQueue.insert(0, nzb)
        forceNZB(nzb.nzbFileName, 'Forcing par recovery download')

"""
Copyright (c) 2005 Ben Bangert <bbangert@groovie.org>
                   Philip Jenvey <pjenvey@groovie.org>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:
1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.
3. The name of the author or contributors may not be used to endorse or
   promote products derived from this software without specific prior
   written permission.

THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
SUCH DAMAGE.

$Id$
"""
