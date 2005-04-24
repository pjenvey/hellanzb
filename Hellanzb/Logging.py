"""

Logging - hellanzb's logging facility. Ties in with python's logging system, with a bunch
of added locks to support interrupting nzbget scroll with other log messages. This is
pretty elaborate for a basic app like hellanzb, but I felt like playing with threads and
looking into python's logging system. Hoho.

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import logging, os, sys, termios, thread, types
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
    scroll with other log messages of different levels. It also slightly pauses the scroll
    output, giving you time to read the message"""
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
                    self.scrollInterrupt(record)
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

    def inMainThread(self):
        if Hellanzb.MAIN_THREAD_IDENT == thread.get_ident():
            return True
        return False

    def scrollInterrupt(self, record):
        """ Print a log message so that the user can see it during a SCROLL """
        msg = self.format(record)
        if self.inMainThread():
            # FIXME: scrollBegin() should really be creating the scroller instance
            # FIXME: no unicode crap from normal python log emit
            Hellanzb.scroller.prefixScroll(msg)
        else:
            reactor.callFromThread(Hellanzb.scroller.prefixScroll, msg)

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
    def read(self, n=-1): raise NotImplementedError()
    def readline(self, length=None): raise NotImplementedError()
    def readlines(self, sizehint=0): raise NotImplementedError()
    def seek(self, pos, mode=0): raise NotImplementedError()
    def tell(self): raise NotImplementedError()
    def truncate(self, size=None): raise NotImplementedError()
    def writelines(self, list): raise NotImplementedError()

def stdinEchoOff():
    # Stolen from python's getpass
    try:
        fd = sys.stdin.fileno()
    except:
        pass

    Hellanzb.oldStdin = termios.tcgetattr(fd)     # a copy to save
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
        except:
            pass

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

    #errHdlr = ScrollableHandler(sys.stderr)
    errHdlr = StreamHandlerNoLF(sys.stderr)
    errHdlr.setLevel(logging.ERROR)
    
    Hellanzb.logger.addHandler(outHdlr)
    Hellanzb.logger.addHandler(errHdlr)

    # Whether or not scroll mode is on
    ScrollableHandler.scrollFlag = False

def initLogFile(logFile = None):
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
        
    fileHdlr = RotatingFileHandlerNoLF(Hellanzb.LOG_FILE, maxBytes = maxBytes, backupCount = backupCount)
    fileHdlr.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    fileHdlr.addFilter(LogFileFilter())
    
    Hellanzb.logger.addHandler(fileHdlr)

    if Hellanzb.DEBUG_MODE_ENABLED:
        class DebugFileFilter(logging.Filter):
            def filter(self, record):
                if record.levelno > logging.DEBUG:
                    return False
                return True
        debugFileHdlr = RotatingFileHandlerNoLF(Hellanzb.DEBUG_MODE, maxBytes = maxBytes, backupCount = backupCount)
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
