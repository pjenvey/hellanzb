"""

Logging - hellanzb's logging facility. Ties in with python's logging system, with an added
SCROLL log level.

The NZBLeecherTicker object will constantly print new and kill it's old lines of text on
the screen via the scroll() level. This busys the screen, but the SCROLL level hooks allow
normal logging of non-SCROLL log messages by passing those non-SCROLL messages to
NZBLeecherTicker to be handled specially (printed above the scrolling text). This special
handling is only enabled when SCROLL has been turned on (via scrollBegin())

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import heapq, logging, os, sys, termios, thread, types
from logging import StreamHandler
from logging.handlers import RotatingFileHandler
from threading import Condition, Lock, Thread
from twisted.internet import reactor
from Hellanzb.Util import *

__id__ = '$Id$'

class StreamHandlerNoLF(StreamHandler):
    """ A StreamHandler that doesn't append \n to every message logged to it """

    def emit(self, record):
        """ Cut/Pastse of StreamHandler's emit to not append messages with \n """
        try:
            msg = self.format(record)
            if not hasattr(types, "UnicodeType"): #if no unicode support...
                self.stream.write("%s" % msg)
            else:
                try:
                    self.stream.write("%s" % msg)
                except UnicodeError:
                    self.stream.write("%s" % msg.encode("UTF-8"))
            self.flush()
        except:
            self.handleError(record)

class RotatingFileHandlerNoLF(RotatingFileHandler):
    """ A RotatingFileHandler that doesn't append \n to every message logged to it """

    def emit(self, record):
        """ Cut/Pastse of RotatingFileHandler's emit to not append messages with \n """
        if self.maxBytes > 0:                   # are we rolling over?
            msg = "%s" % self.format(record)
            self.stream.seek(0, 2)  #due to non-posix-compliant Windows feature
            if self.stream.tell() + len(msg) >= self.maxBytes:
                self.doRollover()
        logging.FileHandler.emit(self, record)

class ScrollableHandler(StreamHandlerNoLF):
    """ ScrollableHandler is a StreamHandler that specially handles scrolling (log
    messages at the SCROLL level). It allows you to temporarily interrupt the constant
    scroll with other log messages of different levels (printed at the top of the scroll
    area) """

    # the SCROLL level (a class var)
    SCROLL = 11
    SHUTDOWN = 12

    def handle(self, record):
        """ The 'scroll' level is a constant scroll that can be interrupted. This interruption is
        done via prepending text to the scroll area """
        rv = self.filter(record)
        if rv:

            if record.levelno == ScrollableHandler.SCROLL:
                self.emitSynchronized(record)
            elif record.levelno == ScrollableHandler.SHUTDOWN:
                record.msg = '\n\n\n' + record.msg + '\n'
                self.emitSynchronized(record)
            else:
                # If scroll is on, interrupt scroll
                if ScrollableHandler.scrollFlag:
                    self.scrollHeader(record)
                else:
                    # otherwise if scroll isn't on, just log the message normally
                    self.emitSynchronized(record)
                            
        return rv

    def emitSynchronized(self, record):
        """ Write a log message atomically. Normal python logging Handler behavior """
        self.acquire()
        try:
            self.emit(record)
        finally:
            self.release()

    def scrollHeader(self, record):
        """ Print a log message so that the user can see it during a SCROLL """
        msg = self.format(record).rstrip() # Scroller appends newline for us
        from twisted.internet import reactor
        if inMainThread():
            # FIXME: scrollBegin() should really be creating the scroller instance
            # FIXME: no unicode crap from normal python log emit
            Hellanzb.scroller.scrollHeader(msg)
        else:
            reactor.callFromThread(Hellanzb.scroller.scrollHeader, msg)

class LogOutputStream:
    """ Provides somewhat of a file-like interface (supporting only the typical writing
    functions) to the specified logging function """
    def __init__(self, logFunction):
        self.write = logFunction

    def flush(self):
        pass
    
    def close(self): raise NotImplementedError()
    def isatty(self): raise NotImplementedError()
    def next(self): raise NotImplementedError()
    def read(self, n = -1): raise NotImplementedError()
    def readline(self, length = None): raise NotImplementedError()
    def readlines(self, sizehint = 0): raise NotImplementedError()
    def seek(self, pos, mode = 0): raise NotImplementedError()
    def tell(self): raise NotImplementedError()
    def truncate(self, size = None): raise NotImplementedError()
    def writelines(self, list): raise NotImplementedError()

class ASCIICodes:
    def __init__(self):
        # f/b_ = fore/background
        # d/l/b  = dark/light/bright
        self.map = {
            'ESCAPE': '\033',
            
            'RESET': '0',
            'KILL_LINE': 'K',
            
            'F_DRED': '31',
            'F_LRED': '31;1',
            'F_DGREEN': '32',
            'F_LGREEN': '32;1',
            'F_BROWN': '33',
            'F_YELLOW': '33;1',
            'F_DBLUE': '34',
            'F_LBLUE': '34;1',
            'F_DMAGENTA': '35',
            'F_LMAGENTA': '35;1',
            'F_DCYAN': '36',
            'F_LCYAN': '36;1',
            'F_WHITE': '37',
            'F_BWHITE': '37;1',
            }
        
    def __getattr__(self, name):
        val = self.map[name]
        if name != 'ESCAPE':
            val = self.map['ESCAPE'] + '[' + val
            if name != 'KILL_LINE':
                val += 'm'
        return val

NEWLINE_RE = re.compile('\n')
class NZBLeecherTicker:
    """ A basic logger for NZBLeecher. It's uh, not what I really want. I'd rather put more
    time into writing a curses interface. Code submissions greatly appreciated. -pjenvey
    """
    def __init__(self):
        self.size = 0
        self.segments = []
        self.currentLog = None

        self.maxCount = 0 # FIXME: var name

        # Only bother doing the whole UI update after running updateStats this many times
        self.delay = 3
        self.wait = 0

        ACODE = Hellanzb.ACODE
        self.connectionPrefix = ACODE.F_DBLUE + '[' + ACODE.RESET + '%s' + \
                                ACODE.F_DBLUE + ']' + ACODE.RESET

        self.scrollHeaders = []

        self.started = False
        self.killedHistory = False

        from Hellanzb.Log import scroll
        self.logger = scroll

    def addClient(self, segment):
        """ Add a client (it's segment) to the ticker """
        from Hellanzb.Log import debug
        debug('ADD CLIENT: ' + str(segment.priority) + ' segment: ' + str(segment.getDestination()))
        heapq.heappush(self.segments, (segment.priority, segment))
        
    def removeClient(self, segment):
        """ Remove a client (it's segment) from the ticker """
        from Hellanzb.Log import debug
        if (segment.priority, segment) in self.segments:
            debug('REMOVE CLIENT: ' + str(segment.priority) + ' segment: ' + str(segment.getDestination()))
        else:
            debug('BAD REMOVE CLIENT: ' + str(segment.priority) + ' segment: ' + str(segment.getDestination()))
        self.segments.remove((segment.priority, segment))

    def scrollHeader(self, message):
        # Even if passed multiple lines, ensure all lines are max 80 chars
        lines = message.split('\n')
        for line in lines:
            self.scrollHeaders.append(truncateToMultiLine(line, length = 80))
        self.updateLog(True)

    def killHistory(self):
        """ clear scroll off the screen """
        if not self.killedHistory and self.started:
            msg = '\r\033[' + str(self.maxCount + 1) + 'A'
            for i in range(self.maxCount + 1):
                msg += '\n\r' + Hellanzb.ACODE.KILL_LINE
            msg += '\r\033[' + str(self.maxCount + 1) + 'A'
            self.logger(msg)
            self.killedHistory = True
            self.started = False
        # segments should be empty at this point anyway
        self.segments = []

    # FIXME: probably doesn't matter much, but should be using StringIO for concatenation
    # here, anyway
    def updateLog(self, logNow = False):
        """ Log ticker """
        # Delay the actual log work -- so we don't over-log (too much CPU work in the
        # async loop)
        if not logNow:
            self.wait += 1
            if self.wait < self.delay:
                return
            else:
                self.wait = 0

        ACODE = Hellanzb.ACODE
        currentLog = self.currentLog
        if self.currentLog != None:
            # Kill previous lines,
            self.currentLog = '\r\033[' + str(self.maxCount) + 'A'
        else:
            # unless we have just began logging. and in that case, explicitly log the
            # first message
            self.currentLog = ''
            logNow = True

        # Log information we want to prefix the scroll (so it stays on the screen)
        if len(self.scrollHeaders) > 0:
            scrollHeader = ''
            for message in self.scrollHeaders:
                message = NEWLINE_RE.sub(ACODE.KILL_LINE + '\n', message)
                scrollHeader += message + ACODE.KILL_LINE + '\n'
                
            self.currentLog += scrollHeader

        # listing sorted via heapq
        heap = self.segments[:]
        sortedSegments = []
        try:
            while True:
                p, segment = heapq.heappop(heap)
                sortedSegments.append(segment)
        except IndexError:
            pass

        lastSegment = None
        i = 0
        for segment in sortedSegments:
            i += 1
            if self.maxCount > 9:
                prettyId = str(i).zfill(2)
            else:
                prettyId = str(i)
            
            # Determine when we've just found the real file name, then use that as the
            # show name
            try:
                if segment.nzbFile.showFilenameIsTemp == True and segment.nzbFile.filename != None:
                    segment.nzbFile.showFilename = segment.nzbFile.filename
                    segment.nzbFile.showFilenameIsTemp = False
            except AttributeError, ae:
                debug('ATTRIBUTE ERROR: ' + str(ae) + ' num: ' + str(segment.number) + \
                      'duh: ' + str(segment.articleData))
                pass
                
            if lastSegment != None and lastSegment.nzbFile == segment.nzbFile:
                line = self.connectionPrefix + ' %s (%s)' + ACODE.KILL_LINE
                # 57 line width -- approximately 80 - 5 (prefix) - 18 (max suffix)
                self.currentLog += line % (prettyId,
                                           rtruncate(segment.nzbFile.showFilename, length = 50),
                                           str(segment.number))
            else:
                line = self.connectionPrefix + ' %s (%s) - ' + ACODE.F_DGREEN + '%2d%%' + ACODE.RESET + \
                       ACODE.F_DBLUE + ' @ ' + ACODE.RESET + ACODE.F_DRED + '%.1fKB/s' + ACODE.KILL_LINE
                self.currentLog += line % (prettyId,
                                           rtruncate(segment.nzbFile.showFilename, length = 49),
                                           str(segment.number),
                                           segment.nzbFile.downloadPercentage, segment.nzbFile.speed)
                
            self.currentLog += '\n\r'

            lastSegment = segment
                
        for fill in range(i + 1, self.maxCount + 1):
            if self.maxCount > 9:
                prettyId = str(fill).zfill(2)
            else:
                prettyId = str(fill)
            self.currentLog += (self.connectionPrefix + ACODE.KILL_LINE) % (prettyId)
            self.currentLog += '\n\r'

        # FIXME: FIXME HA-HA-HACK FIXME
        totalSpeed = 0
        for nsf in Hellanzb.nsfs:
            totalSpeed += nsf.sessionSpeed

        line = self.connectionPrefix + ACODE.F_DRED + ' %.1fKB/s' + ACODE.RESET + \
               ', ' + ACODE.F_DGREEN + '%d MB' + ACODE.RESET + ' queued ' + ACODE.KILL_LINE
        self.currentLog += line % ('Total', totalSpeed,
                                   Hellanzb.queue.totalQueuedBytes / 1024 / 1024)

        if logNow or self.currentLog != currentLog:
            self.logger(self.currentLog)
            self.scrollHeaders = []

def stdinEchoOff():
    # Stolen from python's getpass
    try:
        fd = sys.stdin.fileno()
    except:
        pass

    Hellanzb.oldStdin = termios.tcgetattr(fd) # a copy to save
    new = Hellanzb.oldStdin[:]

    new[3] = new[3] & ~termios.ECHO # 3 == 'lflags'
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, new)
    except:
        pass
    
def stdinEchoOn():
    if hasattr(Hellanzb, 'oldStdin'):
        try:
            fd = sys.stdin.fileno()
            termios.tcsetattr(fd, termios.TCSADRAIN, Hellanzb.oldStdin)
            del Hellanzb.oldStdin
        except:
            pass

def prettyException(exception):
    """ return a pretty rendition of the specified exception, or if no valid exception an
    empty string """
    message = ''
    if exception != None:
        if isinstance(exception, Exception):
            message += getLocalClassName(exception.__class__) + ': ' + str(exception)
            
            if not isinstance(exception, FatalError):
                # Unknown/unexpected exception -- also show the stack trace
                stackTrace = StringIO()
                print_exc(file=stackTrace)
                stackTrace = stackTrace.getvalue()
                message += '\n' + stackTrace
    return message

def initLogging():
    """ Setup logging """
    logging.addLevelName(ScrollableHandler.SCROLL, 'SCROLL')
    logging.addLevelName(ScrollableHandler.SHUTDOWN, 'SHUTDOWN')

    Hellanzb.logger = logging.getLogger('hellanzb')
    #Hellanzb.logger.setLevel(ScrollableHandler.SCROLL)
    Hellanzb.logger.setLevel(logging.DEBUG)

    # Filter for stdout -- log warning and below
    class OutFilter(logging.Filter):
        def filter(self, record):
            if record.levelno > logging.WARNING:
                return False
            # DEBUG will only go out to it's log file
            elif record.levelno == logging.DEBUG:
                return False
            return True
    
    outHdlr = ScrollableHandler(sys.stdout)
    #outHdlr.setLevel(ScrollableHandler.SCROLL)
    outHdlr.addFilter(OutFilter())
    Hellanzb.logger.addHandler(outHdlr)

    errHdlr = ScrollableHandler(sys.stderr)
    errHdlr.setLevel(logging.ERROR)
    Hellanzb.logger.addHandler(errHdlr)

    # Whether or not scroll mode is on
    ScrollableHandler.scrollFlag = False

    # map of ascii colors. for the kids
    Hellanzb.ACODE = ASCIICodes()

def initLogFile(logFile = None, debugLogFile = None):
    """ Initialize the log file. This has to be done after the config is loaded """
    maxBytes = backupCount = 0
    if hasattr(Hellanzb, 'LOG_FILE_MAX_BYTES'):
        maxBytes = Hellanzb.LOG_FILE_MAX_BYTES
    if hasattr(Hellanzb, 'LOG_FILE_BACKUP_COUNT'):
        backupCount = Hellanzb.LOG_FILE_BACKUP_COUNT

    class LogFileFilter(logging.Filter):
        def filter(self, record):
            # SCROLL doesn't belong in log files and DEBUG will have it's own log file
            if record.levelno == ScrollableHandler.SCROLL or record.levelno == logging.DEBUG:
                return False
            return True
    
    # FIXME: should check if Hellanzb.LOG_FILE is set first
    if logFile != None:
        Hellanzb.LOG_FILE = os.path.abspath(logFile)
    if debugLogFile != None:
        Hellanzb.DEBUG_MODE = os.path.abspath(debugLogFile)

    if Hellanzb.LOG_FILE:
        fileHdlr = RotatingFileHandlerNoLF(Hellanzb.LOG_FILE, maxBytes = maxBytes,
                                           backupCount = backupCount)
        fileHdlr.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        fileHdlr.addFilter(LogFileFilter())
    
        Hellanzb.logger.addHandler(fileHdlr)

    if Hellanzb.DEBUG_MODE_ENABLED:
        class DebugFileFilter(logging.Filter):
            def filter(self, record):
                if record.levelno > logging.DEBUG:
                    return False
                return True
            
        debugFileHdlr = RotatingFileHandlerNoLF(Hellanzb.DEBUG_MODE, maxBytes = maxBytes,
                                                backupCount = backupCount)
        debugFileHdlr.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        debugFileHdlr.setLevel(logging.DEBUG)
        debugFileHdlr.addFilter(DebugFileFilter())
        Hellanzb.logger.addHandler(debugFileHdlr)

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
