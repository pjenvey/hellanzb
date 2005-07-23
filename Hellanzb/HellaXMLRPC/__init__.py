"""

HellaXMLRPC - The hellanzb XML RPC server and client

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import os, sys, textwrap, time, Hellanzb
from datetime import datetime
from time import strftime
from twisted.internet import reactor
from twisted.internet.error import CannotListenError, ConnectionRefusedError, DNSLookupError
from twisted.python import log
from twisted.web import xmlrpc, server
from twisted.web.server import Site
from xmlrpclib import DateTime, Fault
from Hellanzb.HellaXMLRPC.xmlrpc import Proxy, XMLRPC # was twisted.web.xmlrpc
from Hellanzb.HellaXMLRPC.HtPasswdAuth import HtPasswdWrapper
from Hellanzb.Logging import LogOutputStream
from Hellanzb.Log import *
from Hellanzb.PostProcessor import PostProcessor
from Hellanzb.Util import archiveName, cmHella, dupeName, flattenDoc, prettyEta, truncateToMultiLine

__id__ = '$Id$'

class HellaXMLRPCServer(XMLRPC):
    """ the hellanzb xml rpc server """
    
    def getChild(self, path, request):
        """ This object generates 404s (Default resource.Resource getChild) with HTTP auth turned
        on, so this was needed. not exactly sure why """
        return self

    def xmlrpc_asciiart(self):
        """ Return a random ascii art """
        from Hellanzb.Elite import C
        return C.asciiArt()

    def xmlrpc_aolsay(self):
        """ Return a random aolsay (from Da5id's aolsay.scr) """
        from Hellanzb.Elite import C
        return C.aolSay()
        
    def xmlrpc_cancel(self):
        """ Cancel the current download and move the current NZB to Hellanzb.TEMP_DIR """
        from Hellanzb.Daemon import cancelCurrent
        return cancelCurrent()

    def xmlrpc_clear(self, andCancel = False):
        """ Clear the current nzb queue. Specify True as the second argument to clear anything
        currently downloading as well (like the cancel call) """
        from Hellanzb.Daemon import clearCurrent
        return clearCurrent(andCancel)

    def xmlrpc_continue(self):
        """ Continue downloading after being paused """
        from Hellanzb.Daemon import continueCurrent
        return continueCurrent()

    def xmlrpc_dequeue(self, nzbId):
        """ Remove the NZB with specified ID from the queue """
        from Hellanzb.Daemon import dequeueNZBs
        return dequeueNZBs(nzbId)
    
    def xmlrpc_down(self, nzbId, shift = 1):
        """ Move the NZB with the specified ID down in the queue. The optional second argument
        specifies the number of spaces to shift by (Default: 1) """
        from Hellanzb.Daemon import moveDown
        return moveDown(nzbId, shift)

    def xmlrpc_enqueue(self, nzbFilename):
        """ Add the specified NZB file to the end of the queue """
        from Hellanzb.Daemon import enqueueNZBs
        reactor.callLater(0, enqueueNZBs, nzbFilename)
        return True

    #def xmlrpc_enqueuedl(self, newzbinId):
    #    """ """

    def xmlrpc_last(self, nzbId):
        """ Move the NZB with the specified ID to the end of the queue """
        from Hellanzb.Daemon import lastNZB
        return lastNZB(nzbId)

    def xmlrpc_list(self, includeIds = False):
        """ List the current queue. Specify True as the second argument to include the NZB ID in
        the listing """
        from Hellanzb.Daemon import listQueue
        return listQueue(includeIds)

    def xmlrpc_force(self, nzbId):
        """ Force hellanzb to begin downloading the NZB with the specified ID immediately,
        interrupting the current download """
        from Hellanzb.Daemon import forceNZBId
        reactor.callLater(0, forceNZBId, nzbId)
        return True

    def xmlrpc_maxrate(self, rate = None):
        """ Return the Hellanzb.MAX_RATE (maximum download rate) value. Specify a second argument
        to change the value -- a value of zero denotes no maximum rate """
        if rate == None:
            if Hellanzb.ht.readLimit == None:
                return str(None)
            return str(Hellanzb.ht.readLimit / 1024)
        
        from Hellanzb.Daemon import maxRate
        return maxRate(rate)

    def xmlrpc_move(self, nzbId, index):
        """ Move the NZB with the specified ID to the specified index in the queue """
        from Hellanzb.Daemon import move
        return move(nzbId, index)
    
    def xmlrpc_next(self, nzbFilename):
        """ Move the NZB with the specified ID to the beginning of the queue """
        from Hellanzb.Daemon import nextNZBId
        reactor.callLater(0, nextNZBId, nzbFilename)
        return True

    def xmlrpc_pause(self):
        """ Pause downloading """
        from Hellanzb.Daemon import pauseCurrent
        return pauseCurrent()

    def xmlrpc_process(self, archiveDir, rarPassword = None):
        """ Post process the specified directory. The -p option is preferable -- it will do this
        for you, or use the current process if this XML-RPC call fails """
        # FIXME: merge this with Daemon.postProcess
        if not os.path.isdir(archiveDir):
            error('Unable to process, not a directory: ' + archiveDir)
            return False

        if not os.access(archiveDir, os.R_OK):
            error('Unable to process, no read access to directory: ' + archiveDir)
            return False
        
        dirName = os.path.dirname(archiveDir.rstrip(os.sep))
        # We are the queue daemon -- Symlink to the archiveDir. If we are ctrl-ced, we'll
        # pick up the post processing afterward restart
        if os.path.normpath(dirName) != os.path.normpath(Hellanzb.PROCESSING_DIR):
            destDir = dupeName(Hellanzb.PROCESSING_DIR + os.sep + os.path.basename(archiveDir.rstrip(os.sep)))
            # UNIX: symlink, windows =[
            os.symlink(archiveDir, destDir)
            archiveDir = destDir

        troll = PostProcessor(archiveDir, rarPassword = rarPassword)
        troll.start()
        return True

    def xmlrpc_shutdown(self):
        """ Shutdown hellanzb. Will quietly kill any post processing threads that may exist """
        # Shutdown the reactor/alert the ui
        reactor.addSystemEventTrigger('after', 'shutdown', logShutdown, 'RPC shutdown call, exiting..')
        from Hellanzb.Core import shutdown
        reactor.callLater(1, shutdown, True)
        
        return True
        
    def xmlrpc_status(self, aolsay = False):
        """ Return hellanzb's current status text """
        s = {}
    
        totalSpeed = 0
        activeClients = 0
        # FIXME: rename nsfs. call it factories
        for nsf in Hellanzb.nsfs:
            totalSpeed += nsf.sessionSpeed
            activeClients += len(nsf.activeClients)

        s['time'] = DateTime()
        s['uptime'] = secondsToUptime(time.time() - Hellanzb.BEGIN_TIME)
        s['is_paused'] = Hellanzb.downloadPaused
        s['rate'] = totalSpeed
        s['queued_mb'] = Hellanzb.queue.totalQueuedBytes / 1024 / 1024
        
        if totalSpeed == 0:
            s['eta'] = 0
        else:
            s['eta'] = int((Hellanzb.queue.totalQueuedBytes / 1024) / totalSpeed)
            
        if Hellanzb.ht.readLimit == None or Hellanzb.ht.readLimit == 0:
            s['maxrate'] = 0
        else:
            s['maxrate'] = Hellanzb.ht.readLimit / 1024
            
        s['total_dl_nzbs'] = Hellanzb.totalArchivesDownloaded
        s['total_dl_files'] = Hellanzb.totalFilesDownloaded
        s['total_dl_segments'] = Hellanzb.totalSegmentsDownloaded
        s['total_dl_mb'] = Hellanzb.totalBytesDownloaded / 1024 / 1024
        s['version'] = Hellanzb.version
        s['currently_downloading'] = [nzb.archiveName for nzb in Hellanzb.queue.currentNZBs()]
        Hellanzb.postProcessorLock.acquire()
        s['currently_processing'] = [archiveName(processor.dirName) for processor in Hellanzb.postProcessors]
        Hellanzb.postProcessorLock.release()
        s['queued'] = [nzb.archiveName for nzb in Hellanzb.queued_nzbs]

        return s

    def xmlrpc_up(self, nzbId, shift = 1):
        """ Move the NZB with the specified ID up in the queue. The optional second argument
        specifies the number of spaces to shift by (Default: 1) """
        from Hellanzb.Daemon import moveUp
        return moveUp(nzbId, shift)

def printResultAndExit(remoteCall, result):
    """ generic xml rpc client call back -- simply print the result as a string and exit """
    if isinstance(result, unicode):
        result = result.encode('utf-8')
    noLogFile(str(result))
    reactor.stop()

def printListAndExit(remoteCall, result):
    if isinstance(result, list):
        [noLogFile(line) for line in result]
    elif isinstance(result, dict):
        length = 6
        [noLogFile(id + ' '*(length - len(id)) + name) for id, name in result.iteritems()]
    else:
        return printResultAndExit()
    reactor.stop()

def resultMadeItBoolAndExit(remoteCall, result):
    """ generic xml rpc call back for a boolean result """
    if type(result) == bool:
        if result:
            info('Successfully made remote call to hellanzb queue daemon')
        else:
            info('Remote call to hellanzb queue daemon returned False! (there was a problem, see logs for details)')
        reactor.stop()
    else:
        noLogFile(str(result))
        reactor.stop()

def errHandler(remoteCall, failure):
    """ generic xml rpc client err back -- handle errors, and possibly spawn a post processor
    thread """
    debug('errHandler, class: ' + str(failure.value.__class__) + ' args: ' + \
          str(failure.value.args), failure)

    err = failure.value
    if isinstance(err, ConnectionRefusedError):

        error('Unable to connect to XMLRPC server,\nerror: ' + str(err) + '\n' + \
             'The hellanzb queue daemon @ ' + Hellanzb.serverUrl + ' probably isn\'t running')

        # By default, post process in the already running hellanzb. otherwise do the work
        # in this current process, and exit
        if remoteCall.funcName == 'process':
            info('\nProcessing locally (-L) instead..')
            if RemoteCall.options.postProcessDir != None:
                from Hellanzb.Daemon import postProcess
                return postProcess(RemoteCall.options)
            else:
                error(sys.argv[0] + ': error: process option requires a value')
        
    elif isinstance(err, ValueError):
        if len(err.args) == 2 and err.args[0] == '401':
            error('Incorrect Hellanzb.XMLRPC_PASSWORD: ' + err.args[1] + ' (XMLRPC server: ' + \
                 Hellanzb.serverUrl + ')')
        elif len(err.args) == 2 and err.args[0] == '405':
            error('XMLRPC server: ' + Hellanzb.serverUrl + ' did not understand command: ' + \
                 remoteCall.funcName + \
                 ' -- this server is probably not the hellanzb XML RPC server!')
        else:
            error('Unexpected XMLRPC problem: ' + str(err))
            
    elif isinstance(err, Fault):
        if err.faultCode == 8001:
            error('Invalid command: ' + remoteCall.funcName + ' (XMLRPC server: ' + Hellanzb.serverUrl + \
                 ') faultString: ' + err.faultString)
        elif err.faultCode == 8002:
            error('Invalid arguments? for call: ' + remoteCall.funcName + ' (XMLRPC server: ' + \
                 Hellanzb.serverUrl + ') faultString: ' + err.faultString)
        else:
            error('Unexpected XMLRPC response: ' + str(err) + ' : ' + getStack(err))

    elif isinstance(err, DNSLookupError):
        error('No address associated with hostname (dns lookup failed)\nurl: ' + Hellanzb.serverUrl)
        pass
            
    reactor.stop()

class RemoteCallArg:
    REQUIRED, OPTIONAL = range(2)

    def __init__(self, name, type):
        self.name = name
        self.type = type
        
class RemoteCall:
    """ XMLRPC client calls, and their callback info """
    callIndex = {}
    # Calling getattr() on the HellaXMLRPCServer class throws a __provides__ error in
    # python2.4 on OS X (the problem is with zope interface). We need to do this to gather
    # our XMLRPC call doc Strings -- this instance has no use other than allowing us
    # access to those doc strings
    serverInstance = HellaXMLRPCServer()

    def __init__(self, funcName, callback, errback = errHandler, published = True):
        self.funcName = funcName
        self.callbackFunc = callback
        self.errbackFunc = errHandler
        self.published = published
        self.args = []

        RemoteCall.callIndex[funcName] = self

    def addRequiredArg(self, argname):
        """ denote this remote call as having the specified required arg. order is determined by
        this or addOptionalArg calls are made """
        self.args.append(RemoteCallArg(argname, RemoteCallArg.REQUIRED))

    def addOptionalArg(self, argname):
        """ denote this remote call as having the specified optional arg. order is determined by
        this or addRequiredArg calls are made """
        self.args.append(RemoteCallArg(argname, RemoteCallArg.OPTIONAL))

    def usage(self):
        """ Return the usage string for this rpc call. This is stolen from the xmlrpc Server's
        function doc string """
        for attrName in dir(HellaXMLRPCServer):
            #attr = getattr(HellaXMLRPCServer, attrName) # dies on python2.4 osx
            attr = getattr(RemoteCall.serverInstance, attrName)
            if callable(attr) and attr.__name__ == 'xmlrpc_' + self.funcName:
                return attr.__doc__
        return None

    def callRemote(self, serverUrl = None, *args):
        """ make the remote function call """
        proxy = Proxy(serverUrl)
        if args == None:
            proxy.callRemote(self.funcName).addCallbacks(self.callback, self.errback)
        else:
            proxy.callRemote(self.funcName, *args).addCallbacks(self.callback, self.errback)

    def callback(self, result):
        """ callback from a successful xml rpc call """
        self.callbackFunc(self, result)
        
    def errback(self, failure):
        """ callback from a failed xml rpc call """
        self.errbackFunc(self, failure)

    def call(serverUrl, funcName, args):
        """ lookup the specified function in our pool of known commands, and call it """
        # FIXME:
        pass 

    def callLater(serverUrl, funcName, args):
        try:
            rc = RemoteCall.callIndex[funcName]
        except KeyError:
            raise FatalError('Invalid remote call: ' + funcName)
        if rc == None:
            raise FatalError('Invalid remote call: ' + funcName)

        reactor.callLater(0, rc.callRemote, serverUrl, *args)
    callLater = staticmethod(callLater)

    def argsUsage(self):
        """ generate a usage output for all known args """
        msg = ''
        for arg in self.args:
            if arg.type == RemoteCallArg.REQUIRED:
                msg += ' ' + arg.name
            elif arg.type == RemoteCallArg.OPTIONAL:
                msg += ' [' + arg.name + ']'
        return msg

    def allUsage(indent = '  '):
        """ generate a usage output for all known xml rpc commands """
        msg = ''
        calls = RemoteCall.callIndex.keys()
        calls.sort()
        for name in calls:
            call = RemoteCall.callIndex[name]
            if not call.published:
                continue
            
            prefix = indent + name + call.argsUsage()
            nextIndent = ' '*(24 - len(prefix))
            prefix += nextIndent
            msg += textwrap.fill(prefix + flattenDoc(call.usage()), 79,
                                 subsequent_indent = ' '*len(prefix))
            msg += '\n'
        return msg
    allUsage = staticmethod(allUsage)

def ensureXMLRPCOptions(isClient = False):
    """ Ensure all the config file options are set for the XMLRPC server & client """
    DEFAULT_PORT = 8760
    if not hasattr(Hellanzb, 'XMLRPC_PORT') or (isClient and Hellanzb.XMLRPC_PORT == None):
        Hellanzb.XMLRPC_PORT = DEFAULT_PORT

    elif not isClient and Hellanzb.XMLRPC_PORT == None:
        # explicitly do not initialize an xml rpc server when the port is set to none
        pass
        
    elif isinstance(Hellanzb.XMLRPC_PORT, str):
        try:
            Hellanzb.XMLRPC_PORT = int(Hellanzb.XMLRPC_PORT)
        except ValueError, ve:
            raise FatalError('Invalid Hellanzb.XMLRPC_PORT value: ' + str(Hellanzb.XMLRPC_PORT))

    elif not isinstance(Hellanzb.XMLRPC_PORT, int):
        raise FatalError('Invalid Hellanzb.XMLRPC_PORT value: ' + str(Hellanzb.XMLRPC_PORT))


    if not hasattr(Hellanzb, 'XMLRPC_SERVER') or Hellanzb.XMLRPC_SERVER == None:
        Hellanzb.XMLRPC_SERVER = 'localhost'
    elif not isinstance(Hellanzb.XMLRPC_SERVER, str):
        raise FatalError('Invalid Hellanzb.XMLRPC_SERVER value: ' + str(Hellanzb.XMLRPC_SERVER))

        
    if not hasattr(Hellanzb, 'XMLRPC_PASSWORD'):
        raise FatalError('Required option Hellanzb.XMLRPC_PASSWORD not defined in config file')
    elif Hellanzb.XMLRPC_PASSWORD == None:
        Hellanzb.XMLRPC_PASSWORD == ''
    elif not isinstance(Hellanzb.XMLRPC_PASSWORD, str):
        raise FatalError('Invalid Hellanzb.XMLRPC_PASSWORD value: ' + str(Hellanzb.XMLRPC_PASSWORD))
        
def initXMLRPCServer():
    """ Start the XML RPC server """
    ensureXMLRPCOptions()

    if Hellanzb.XMLRPC_PORT == None:
        warn('Hellanzb.XMLRPC_PORT = None, not starting the XML-RPC server')
        return
        
    hxmlrpcs = HellaXMLRPCServer()
    
    SECURE = True
    try:
        if SECURE:
            secure = HtPasswdWrapper(hxmlrpcs, 'hellanzb', Hellanzb.XMLRPC_PASSWORD, 'hellanzb XML RPC')
            reactor.listenTCP(Hellanzb.XMLRPC_PORT, Site(secure))
        else:
            reactor.listenTCP(Hellanzb.XMLRPC_PORT, Site(hxmlrpcs))
    except CannotListenError, cle:
        error(str(cle))
        raise FatalError('Cannot bind to XML RPC port, is another hellanzb queue daemon already running?')

def initXMLRPCClient():
    """ initialize the xml rpc client """
    # Aliases to these calls would be nice
    r = RemoteCall('aolsay', printResultAndExit, published = False)
    r = RemoteCall('asciiart', printResultAndExit, published = False)
    r = RemoteCall('cancel', resultMadeItBoolAndExit)
    r = RemoteCall('clear', resultMadeItBoolAndExit)
    r = RemoteCall('continue', resultMadeItBoolAndExit)
    r = RemoteCall('dequeue', resultMadeItBoolAndExit)
    r.addRequiredArg('nzbid')
    r = RemoteCall('down', resultMadeItBoolAndExit)
    r.addRequiredArg('nzbid')
    r.addOptionalArg('shift')
    r = RemoteCall('enqueue', resultMadeItBoolAndExit)
    r.addRequiredArg('nzbfile')
    r = RemoteCall('force', resultMadeItBoolAndExit)
    r.addRequiredArg('nzbid')
    r = RemoteCall('last', resultMadeItBoolAndExit)
    r.addRequiredArg('nzbid')
    r = RemoteCall('list', printListAndExit)
    r.addOptionalArg('showids')
    r = RemoteCall('maxrate', resultMadeItBoolAndExit)
    r.addOptionalArg('newrate')
    r = RemoteCall('move', resultMadeItBoolAndExit)
    r.addRequiredArg('nzbid')
    r.addRequiredArg('index')
    r = RemoteCall('next', resultMadeItBoolAndExit)
    r.addRequiredArg('nzbid')
    r = RemoteCall('pause', resultMadeItBoolAndExit)
    r = RemoteCall('process', resultMadeItBoolAndExit)
    r.addRequiredArg('archivedir')
    r = RemoteCall('shutdown', resultMadeItBoolAndExit)
    r = RemoteCall('status', statusString)
    r = RemoteCall('up', resultMadeItBoolAndExit)
    r.addRequiredArg('nzbid')
    r.addOptionalArg('shift')

def hellaRemote(options, args):
    """ execute the remote RPC call with the specified cmd line args. args can be None """
    ensureXMLRPCOptions(isClient = True)
    
    if options.postProcessDir and options.rarPassword:
        args = ['process', options.postProcessDir, options.rarPassword]
    elif options.postProcessDir:
        args = ['process', options.postProcessDir]

    if args[0] in ('process', 'enqueue'):
        if len(args) > 1:
            # UNIX: os.path.realpath only available on UNIX
            args[1] = os.path.realpath(args[1])

    Hellanzb.serverUrl = 'http://hellanzb:%s@%s:%i' % (Hellanzb.XMLRPC_PASSWORD, Hellanzb.XMLRPC_SERVER,
                                                       Hellanzb.XMLRPC_PORT)

    fileStream = LogOutputStream(debug)
    log.startLogging(fileStream)
    
    funcName = args[0]
    args.remove(funcName)
    RemoteCall.options = options
    RemoteCall.callLater(Hellanzb.serverUrl, funcName, args)
    reactor.run()


def statusString(remoteCall, result):
    """ Generate and print status txt to stdout from the result of an xml rpc status call """
    s = result

    # yyyymmddThh:mm:ss
    t = s['time'].value
    y = int(t[0:4])
    m = int(t[4:6])
    d = int(t[6:8])
    #z = int(t[8:1])
    h = int(t[9:11])
    min = int(t[12:14])
    sec = int(t[15:17])
    
    currentTime = datetime(y, m, d, h, min, sec)
    # NOTE: Could try: getting values from the result dict, and default to a None for
    # each, for the case of possible later versions of hellanzb expecting more/different
    # arguments -- they won't necessarily fail (not a big deal)
    uptime = s['uptime']
    isPaused = s['is_paused']
    totalSpeed = s['rate']
    totalNZBs = s['total_dl_nzbs']
    totalFiles = s['total_dl_files']
    totalSegments = s['total_dl_segments']
    totalMb = s['total_dl_mb']
    version = s['version']
    currentNZBs = s['currently_downloading']
    processingNZBs = s['currently_processing']
    queuedNZBs = s['queued']
    queuedMB = s['queued_mb']
    eta = s['eta']

    if isPaused:
        totalSpeed = 'Paused'
    elif totalSpeed == 0:
        totalSpeed = 'Idle'
    else:
        totalSpeed = '%.1fKB/s' % (totalSpeed)
    
    downloading = 'Downloading: '
    processing = 'Processing: '
    failedProcessing = 'Failed Processing: '
    queued = 'Queued: '
    downloadingSpacer = ' '*len(downloading)

    downloading += statusFromList(currentNZBs, len(downloading))
    processing += statusFromList(processingNZBs, len(processing))
    queued += statusFromList(queuedNZBs, len(queued))

    # FIXME: show if any archives failed during processing?
    #f = failedProcessing

    now = currentTime.strftime('%I:%M%p')

    # FIXME: optionally don't show ascii
    # hellanzb version %s

    firstLine = """%s  up %s  """
    firstLine = firstLine % (now,
                             uptime)
    two =  """downloaded %i nzbs, %i files, %i segments""" % (totalNZBs, totalFiles,
                                                              totalSegments)
    three = '\n' + ' '*len(firstLine) + """(%i MB)\n""" % \
        (totalMb)
    
    msg = firstLine + two + three
    msg += cmHella(version)
    msg += \
"""
%s
%s%s, %s MB queued, ETA: %s

%s
%s
    """.strip() % (downloading, downloadingSpacer, totalSpeed, queuedMB, prettyEta(eta),
                   processing, queued)

    if isinstance(msg, unicode):
        msg = msg.encode('utf-8')
    noLogFile(str(msg))
    
    reactor.stop()

def secondsToUptime(seconds):
    """ convert seconds to a pretty uptime output: 2 days, 19:45 """
    days = int(seconds / (60 * 60 * 24))
    hours = int((seconds - (days * 60 * 60 * 24)) / (60 * 60))
    minutes = int((seconds - (days * 60 * 60 * 24) - (hours * 60 * 60)) / 60)
    msg = ''
    if days == 1:
        msg = '%i day, ' % (days)
    elif days > 1:
        msg = '%i days, ' % (days)
    msg += '%.2i:%.2i' % (hours, minutes)
    return msg

def statusFromList(alist, indent):
    """ generate a status message from the list of objects, using the specified function for
    formatting """
    status = ''
    if len(alist):
        i = 0
        for item in alist:
            if i:
                status += ' '*indent
            status += item
            if i < len(alist) - 1:
                status += '\n'
            i += 1
    else:
        status += 'None'
    return status

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
 * $Id: HellaReactor.py 248 2005-05-03 07:58:12Z pjenvey $
 */
"""
