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
import heapq, logging, os, sys, thread, types
try:
    import termios
except ImportError:
    termios = None
from logging import StreamHandler
from logging.handlers import RotatingFileHandler
from threading import Condition, Lock, RLock, Thread
from twisted.internet import reactor
from twisted.python import reflect, util
from twisted.python.log import startLoggingWithObserver, FileLogObserver
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

class RotatingFileHandlerNoLF(RotatingFileHandler, StreamHandlerNoLF):
    """ A RotatingFileHandler that doesn't append \n to every message logged to it """

    def emit(self, record):
        """ Cut/Pastse of RotatingFileHandler's emit to not append messages with \n """
        if self.maxBytes > 0:                   # are we rolling over?
            msg = "%s" % self.format(record)
            self.stream.seek(0, 2)  #due to non-posix-compliant Windows feature
            if self.stream.tell() + len(msg) >= self.maxBytes:
                self.doRollover()
        StreamHandlerNoLF.emit(self, record)

class ScrollableHandler(StreamHandlerNoLF):
    """ ScrollableHandler is a StreamHandler that specially handles scrolling (log
    messages at the SCROLL level). It allows you to temporarily interrupt the constant
    scroll with other log messages of different levels (printed at the top of the scroll
    area) """

    # the SCROLL level (a class var)
    LOGFILE = 11
    SCROLL = 12
    SHUTDOWN = 13
    NOLOGFILE = 14
    
    def __init__(self, *args, **kwargs):
        self.scrollLock = RLock()
        self.scrollFlag = False
        StreamHandlerNoLF.__init__(self, *args, **kwargs)

    def handle(self, record):
        """ The 'scroll' level is a constant scroll that can be interrupted. This interruption is
        done via prepending text to the scroll area """
        rv = self.filter(record)
        if rv:

            if record.levelno == ScrollableHandler.SCROLL:
                self.emitSynchronized(record)
            elif record.levelno == ScrollableHandler.SHUTDOWN:
                record.msg = '\n\n\n%s\n' % record.msg
                self.emitSynchronized(record)
            else:
                self.scrollLock.acquire()
                # If scroll is on, interrupt scroll
                if ScrollableHandler.scrollFlag:
                    self.scrollHeader(record)
                else:
                    # otherwise if scroll isn't on, just log the message normally
                    self.emitSynchronized(record)
                self.scrollLock.release()
                            
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

class RecentLogEntries:
    """ A FIFO queue that maintains the specified size by popping off the least recently added
    item """
    def __init__(self, size):
        self.size = size
        self.logEntries = []

    def append(self, level, logEntry):
        if len(self.logEntries) >= self.size:
            self.logEntries.pop(0)
            
        self.logEntries.append((level, logEntry))

    def __iter__(self):
        entriesLen = len(self.logEntries)
        i = 0
        while i < entriesLen:
            yield self.logEntries[i]
            i += 1

class LogOutputStream:
    """ Provides somewhat of a file-like interface (supporting only the typical writing
    functions) to the specified logging function """
    def __init__(self, logFunction):
        self.write = logFunction

    def flush(self): pass
    def close(self): pass
    def isatty(self): raise NotImplementedError()
    def next(self): raise NotImplementedError()
    def read(self, n = -1): raise NotImplementedError()
    def readline(self, length = None): raise NotImplementedError()
    def readlines(self, sizehint = 0): raise NotImplementedError()
    def seek(self, pos, mode = 0): raise NotImplementedError()
    def tell(self): raise NotImplementedError()
    def truncate(self, size = None): raise NotImplementedError()
    def writelines(self, list): raise NotImplementedError()

class ANSICodes(object):
    # f/b_ = fore/background
    # d/l/b  = dark/light/bright
    map = {
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

    def __init__(self):
        for key, val in self.map.iteritems():
            if Hellanzb.DISABLE_ANSI:
                code = ''
            else:
                code = self.code(key)
            self.__dict__[key] = code
        
    def code(self, name):
        val = self.map[name]
        if name != 'ESCAPE':
            val = '%s[%s' % (self.map['ESCAPE'], val)
            if name != 'KILL_LINE':
                val = '%sm' % val
        return val

class HellaTwistedLogObserver(FileLogObserver):
    """ Custom twisted LogObserver. It emits twisted log entries to the debug log
    function, unless they are failures (Exceptions), which are emited to the error log
    function """
    def __init__(self):
        from Hellanzb.Log import error, debug
        self.error = error
        self.debug = debug

    def emit(self, eventDict):
        isFailure = False
        edm = eventDict['message']
        if not edm:
            if eventDict['isError'] and eventDict.has_key('failure'):
                isFailure = True
                text = ((eventDict.get('why') or 'Unhandled Error')
                        + '\n' + eventDict['failure'].getTraceback())
            elif eventDict.has_key('format'):
                text = self._safeFormat(eventDict['format'], eventDict)
            else:
                # we don't know how to log this
                return
        else:
            text = ' '.join(map(reflect.safe_str, edm))

        fmtDict = {'system': eventDict['system'], 'text': text}
        msgStr = self._safeFormat("[%(system)s] %(text)s\n", fmtDict)

        if isFailure:
            util.untilConcludes(self.error, msgStr, appendLF=False)
        else:
            util.untilConcludes(self.debug, msgStr, appendLF=False)
    __call__ = emit

NEWLINE_RE = re.compile('\n')
class NZBLeecherTicker:
    """ A basic logger for NZBLeecher. It's uh, not what I really want. I'd rather put more
    time into writing a curses interface. Code submissions greatly appreciated. -pjenvey
    """
    def __init__(self):
        self.size = 0
        self.segments = []
        self.connectionCounts = {}
        self.currentLog = None

        self.maxCount = 0 # FIXME: var name

        ACODE = Hellanzb.ACODE
        self.connectionPrefix = ACODE.F_DBLUE + '[' + ACODE.RESET + '%s' + \
                                ACODE.F_DBLUE + ']' + ACODE.RESET

        self.scrollHeaders = []

        self.started = False
        self.killedHistory = False

        from Hellanzb.Log import scroll
        self.logger = scroll

    def addClient(self, segment, color):
        """ Add a client (it's segment) to the ticker, to log with the specified ascii color code """
        heapq.heappush(self.segments, (segment.priority, segment, color))
        
    def removeClient(self, segment, color):
        """ Remove a client (it's segment) from the ticker """
        self.segments.remove((segment.priority, segment, color))

    def setConnectionCount(self, color, count):
        """ Set the number of connections for the particular color """
        if color not in self.connectionCounts:
            self.connectionCounts[color] = count
        else:
            self.connectionCounts[color] += count

    def scrollHeader(self, message):
        # Even if passed multiple lines, ensure all lines are max 80 chars
        lines = message.split('\n')
        for line in lines:
            line = truncateToMultiLine(line, length = 80).expandtabs()
            self.scrollHeaders.append(line)

        if Hellanzb.SHUTDOWN:
            return
        self.updateLog()

    def killHistory(self):
        """ clear scroll off the screen """
        if not self.killedHistory and self.started:
            msg = '\r\033[%iA' % (self.maxCount + 1)
            for i in range(self.maxCount + 1):
                msg = '%s\n\r%s' % (msg, Hellanzb.ACODE.KILL_LINE)
            msg = '%s\r\033[%iA' % (msg, self.maxCount + 1)
            
            if not Hellanzb.DAEMONIZE:
                self.logger(msg)
                
            self.killedHistory = True
            self.started = False
        # segments should be empty at this point anyway
        self.segments = []

    # FIXME: probably doesn't matter much, but should be using StringIO for concatenation
    # here, anyway
    def updateLog(self):
        """ Log ticker """
        if Hellanzb.DAEMONIZE or Hellanzb.DISABLE_SCROLLER:
            return
        
        ACODE = Hellanzb.ACODE
        if self.currentLog != None:
            # Kill previous lines,
            currentLog = '\r\033[%iA' % self.maxCount
        else:
            # unless we have just began logging. and in that case, explicitly log the
            # first message
            currentLog = ''

        # Log information we want to prefix the scroll (so it stays on the screen)
        if len(self.scrollHeaders) > 0:
            scrollHeader = ''
            for message in self.scrollHeaders:
                message = NEWLINE_RE.sub(ACODE.KILL_LINE + '\n', message)
                scrollHeader = '%s%s%s\n' % (scrollHeader, message, ACODE.KILL_LINE)
                
            currentLog = '%s%s' % (currentLog, scrollHeader)

        # listing sorted via heapq
        heap = self.segments[:]
        sortedSegments = []
        colorCount = self.connectionCounts.copy()
        try:
            while True:
                p, segment, color = heapq.heappop(heap)
                colorCount[color] -= 1
                sortedSegments.append((segment, color))
        except IndexError:
            pass

        lastSegment = None
        i = 0
        for segment, color in sortedSegments:
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
                from Hellanzb.Log import debug
                debug('ATTRIBUTE ERROR: ' + str(ae) + ' num: ' + str(segment.number) + \
                      ' duh: ' + str(segment.articleData))
                pass

            connectionPrefix = color + '[' + ACODE.RESET + '%s' + \
                                color + ']' + ACODE.RESET
            prefix = connectionPrefix % prettyId
            if lastSegment != None and lastSegment.nzbFile == segment.nzbFile:
                # 57 line width -- approximately 80 - 5 (prefix) - 18 (max suffix)
                currentLog = '%s%s %s%s' % (currentLog, prefix,
                                                 rtruncate(segment.nzbFile.showFilename,
                                                           length = 57), ACODE.KILL_LINE)
            else:
                currentLog = '%s%s %s - %s%2d%%%s%s @ %s%s%.1fKB/s%s' % \
                    (currentLog, prefix, rtruncate(segment.nzbFile.showFilename,
                                                        length = 57), ACODE.F_DGREEN,
                     segment.nzbFile.downloadPercentage, ACODE.RESET, ACODE.F_DBLUE,
                     ACODE.RESET, ACODE.F_DRED, segment.nzbFile.getCurrentRate(),
                     ACODE.KILL_LINE)

            currentLog = '%s\n\r' % currentLog

            lastSegment = segment

        # Fill in empty lines
        for color, fillCount in colorCount.iteritems():
            for count in range(fillCount):
                i += 1
                fill = i
                if self.maxCount > 9:
                    prettyId = str(fill).zfill(2)
                else:
                    prettyId = str(fill)
                connectionPrefix = color + '[' + ACODE.RESET + '%s' + \
                                    color + ']' + ACODE.RESET
                prefix = connectionPrefix % prettyId
                currentLog = '%s%s%s\n\r' % (currentLog, prefix, ACODE.KILL_LINE)

        paused = ''
        if Hellanzb.downloadPaused:
            paused = '%s [Paused]%s' % (ACODE.F_DCYAN, ACODE.RESET)

        totalSpeed = Hellanzb.getCurrentRate()

        if totalSpeed == 0:
            eta = '00:00:00'
        else:
            eta = prettyEta((Hellanzb.queue.totalQueuedBytes / 1024) / totalSpeed)

        prefix = self.connectionPrefix % 'Total'

        currentLog = '%s%s%s %.1fKB/s%s, %s%i MB%s queued, ETA: %s%s%s%s%s' % \
            (currentLog, prefix, ACODE.F_DRED, totalSpeed, ACODE.RESET,
             ACODE.F_DGREEN, Hellanzb.queue.totalQueuedBytes / 1024 / 1024, ACODE.RESET,
             ACODE.F_YELLOW, eta, ACODE.RESET, paused, ACODE.KILL_LINE)

        self.logger(currentLog)
        self.currentLog = currentLog
        self.scrollHeaders = []

def stdinEchoOff():
    """ ECHO OFF standard input """
    if not termios or Hellanzb.DAEMONIZE or Hellanzb.DISABLE_SCROLLER:
        return
    
    from Hellanzb.Log import debug
    try:
        fd = sys.stdin.fileno()
    except:
        return

    try:
        new = termios.tcgetattr(fd)
    except Exception, e:
        debug('stdinEchoOn error', e)
        return

    new[3] = new[3] & ~termios.ECHO # 3 == 'lflags'
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, new)
        debug('stdinEchoOff - OFF')
    except Exception, e:
        debug('stdinEchoOff error', e)
    
def stdinEchoOn():
    """ ECHO ON standard input """
    if not termios or getattr(Hellanzb, 'DAEMONIZE', False) \
            or getattr(Hellanzb, 'DISABLE_SCROLLER', False):
        return
    
    from Hellanzb.Log import debug
    try:
        fd = sys.stdin.fileno()
    except:
        return

    try:
        new = termios.tcgetattr(fd)
    except Exception, e:
        debug('stdinEchoOn error', e)
        return

    new[3] = new[3] | termios.ECHO # 3 == 'lflags'
    try:
        termios.tcsetattr(fd, termios.TCSAFLUSH, new)
        debug('stdinEchoOn - ON')
    except Exception, e:
        debug('stdinEchoOn error', e)

def prettyException(exception):
    """ Return a pretty rendition of the specified exception, or if no valid exception an
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
                message = '%s\n%s' % (message, stackTrace)
    return message

def lockScrollableHandlers(func, *args, **kwargs):
    """ Call the function with all ScrollableHandlers locked """
    lockedLoggers = []
    for logger in Hellanzb.logger.handlers:
        if isinstance(logger, ScrollableHandler):
            logger.scrollLock.acquire()
            lockedLoggers.append(logger)

    func(*args, **kwargs)

    [logger.scrollLock.release() for logger in lockedLoggers]

def initLogging():
    """ Setup logging """
    logging.addLevelName(ScrollableHandler.LOGFILE, 'LOGFILE')
    logging.addLevelName(ScrollableHandler.SCROLL, 'SCROLL')
    logging.addLevelName(ScrollableHandler.SHUTDOWN, 'SHUTDOWN')
    logging.addLevelName(ScrollableHandler.NOLOGFILE, 'NOLOGFILE')

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
    outHdlr.setLevel(ScrollableHandler.SCROLL)
    outHdlr.addFilter(OutFilter())
    Hellanzb.logger.addHandler(outHdlr)

    errHdlr = ScrollableHandler(sys.stderr)
    errHdlr.setLevel(logging.ERROR)
    Hellanzb.logger.addHandler(errHdlr)

    # Whether or not scroll mode is on
    ScrollableHandler.scrollFlag = False

    # Whether or not the scroller functionality is completely disabled
    Hellanzb.DISABLE_SCROLLER = False
    
    Hellanzb.recentLogs = RecentLogEntries(20)

def initLogFile(logFile = None, debugLogFile = None):
    """ Initialize the log file. This has to be done after the config is loaded """
    # map of ascii colors. for the kids
    # This is initialized here, instead of initLogging, because it requires the config
    # file to be loaded
    Hellanzb.ACODE = ANSICodes()

    maxBytes = backupCount = 0
    if hasattr(Hellanzb, 'LOG_FILE_MAX_BYTES'):
        maxBytes = Hellanzb.LOG_FILE_MAX_BYTES
    if hasattr(Hellanzb, 'LOG_FILE_BACKUP_COUNT'):
        backupCount = Hellanzb.LOG_FILE_BACKUP_COUNT

    class LogFileFilter(logging.Filter):
        def filter(self, record):
            # SCROLL doesn't belong in log files and DEBUG will have it's own log file
            if record.levelno == ScrollableHandler.SCROLL or record.levelno == logging.DEBUG \
                    or record.levelno == ScrollableHandler.NOLOGFILE:
                return False
            return True

    # FIXME: should check if Hellanzb.LOG_FILE is set first
    if logFile is not None:
        Hellanzb.LOG_FILE = os.path.abspath(logFile)
    if debugLogFile is not None:
        Hellanzb.DEBUG_MODE = os.path.abspath(debugLogFile)
        
        # Set this, maybe again, incase the -d option was specified
        Hellanzb.DEBUG_MODE_ENABLED = True

    # Ensure the log file's parent dirs exist and are writable
    dirNames = {}
    if hasattr(Hellanzb, 'LOG_FILE') and Hellanzb.LOG_FILE is not None:
        dirNames['LOG_FILE'] = os.path.dirname(Hellanzb.LOG_FILE)
    if hasattr(Hellanzb, 'DEBUG_MODE') and Hellanzb.DEBUG_MODE is not None:
        dirNames['DEBUG_MODE'] = os.path.dirname(Hellanzb.DEBUG_MODE)
    ensureDirs(dirNames)

    if isPy2App():
        Hellanzb.DISABLE_SCROLLER = True
    
    if Hellanzb.LOG_FILE:
        fileHdlr = RotatingFileHandlerNoLF(Hellanzb.LOG_FILE, maxBytes = maxBytes,
                                           backupCount = backupCount)
        fileHdlr.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        fileHdlr.addFilter(LogFileFilter())
    
        Hellanzb.logger.addHandler(fileHdlr)

    if Hellanzb.DEBUG_MODE_ENABLED:
        class DebugFileFilter(logging.Filter):
            def filter(self, record):
                if record.levelno > logging.DEBUG or record.levelno == ScrollableHandler.NOLOGFILE:
                    return False
                return True
            
        debugFileHdlr = RotatingFileHandlerNoLF(Hellanzb.DEBUG_MODE, maxBytes = maxBytes,
                                                backupCount = backupCount)
        debugFileHdlr.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        debugFileHdlr.setLevel(logging.DEBUG)
        debugFileHdlr.addFilter(DebugFileFilter())
        Hellanzb.logger.addHandler(debugFileHdlr)
    
    # Direct twisted log output via the custom LogObserver
    startLoggingWithObserver(HellaTwistedLogObserver())

"""
Copyright (c) 2005 Philip Jenvey <pjenvey@groovie.org>
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
