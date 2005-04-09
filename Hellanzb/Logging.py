"""
Logging - hellanzb's logging facility. Ties in with python's logging system, with a bunch
of added locks to support interrupting nzbget scroll with other log messages. This is
pretty elaborate for a basic app like hellanzb, but I felt like playing with threads and
looking into python's logging system. Hoho.

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import logging, os.path, sys, time, termios, types, xmlrpclib
from logging import StreamHandler
from logging.handlers import RotatingFileHandler
from threading import Condition, Lock, Thread
from traceback import print_exc
from Growl import *
from StringIO import StringIO
from Util import *

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
    """ ScrollableHandler is a StreamHandler that specially handles scrolling (log messages at the SCROLL level). It allows you to temporarily interrupt the constant scroll with other log messages of different levels. It also slightly pauses the scroll output, giving you time to read the message  """
    # the SCROLL level (a class var)
    SCROLL = 11

    def handle(self, record):
        """ The 'scroll' level is a constant scroll that can be interrupted. This interruption is
done via a lock (ScrollableHandler.scrollLock) -- if this Handler is logging a scroll
record, it will only emit the record if the handler can immediately acquire the scroll
lock. If it fails to acquire the lock it will throw away the scroll record. """
        rv = self.filter(record)
        if rv:

            if record.levelno == ScrollableHandler.SCROLL:
                # Only print scroll if we can immediately acquire the scroll lock
                if ScrollableHandler.scrollLock.acquire(False):

                    # got the lock -- scroll is now on and no longer interrupted
                    ScrollableHandler.scrollInterrupted = False

                    try:
                        self.emitSynchronized(record)
                    finally:
                        ScrollableHandler.scrollLock.release()

                else:
                    # no scroll for you
                    return rv
            else:
                # If scroll is on, queue the message for the ScrollInterrupter
                if ScrollableHandler.scrollFlag:
                    self.queueScrollInterrupt(record)

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

    def queueScrollInterrupt(self, record):
        """ Lock the list of pending interrupt records, then notify the interrupter it has work to
do """
        # Give the interrupter a reference back to where it will actually emit the log
        # record (ourself)
        record.scrollableHandler = self
        
        try:
            ScrollInterrupter.pendingMonitor.acquire()
            ScrollInterrupter.pendingLogRecords.append(record)
            ScrollInterrupter.pendingMonitor.notify()
            ScrollInterrupter.notifiedMonitor = True
        finally:
            ScrollInterrupter.pendingMonitor.release()

class ScrollInterrupter(Thread):
    """ The scroll interrupter handles printing out a message and pausing the scroll for a
short time after those messages are printed. Even though this is only a brief pause, we
don't want logging to block while this pause happens. Thus the pause is handled by this
permanent thread. This is modeled after a logging.Handler, but it does not extend it --
it's more of a child helper handler of ScrollableHandler, than an offical logging Handler
"""
    def acquire(self, record):
        """ Acquire the ScrollableHandler lock (log a message atomically via pythons logging) """ 
        record.scrollableHandler.acquire()
        
    def release(self, record):
        """ Release the ScrollableHandler lock """
        record.scrollableHandler.release()

    def format(self, record):
        """ Add spaces to the scroll interrupting log message, unless we've already interrupted
scroll and already added the spaces """
        if not ScrollableHandler.scrollInterrupted:
            record.msg = '\n\n\n\n' + record.msg + '\n\n'
            ScrollableHandler.scrollInterrupted = True
        else:
            record.msg = record.msg + '\n\n'
        return record

    def handle(self, record):
        """ Handle the locking required to atomically log a message
        @see Handler.handle(self, record) """
        # atomically log the the message.
        self.acquire(record)
        try:
            self.emit(record)
        finally:
            self.release(record)

    def emit(self, record):
        """ Do the actual logging work
        @see Handler.emit(self, record)"""
        record = self.format(record)
        self.emitToParent(record)
        
    def emitToParent(self, record):
        """ Pass the log message back to the ScrollableHandler """
        record.scrollableHandler.emit(record)

    def wait(self, timeout = None):
        """ Wait for notification of new log messages """
        # FIXME: this lock should never really be released by this function, except by
        # wait. does that fly with the temporary wait below?
        ScrollInterrupter.pendingMonitor.acquire()
        
        result = ScrollInterrupter.pendingMonitor.wait(timeout)
        if timeout == None and ScrollInterrupter.notifiedMonitor:
           ScrollInterrupter.notifiedMonitor = False

        ScrollInterrupter.pendingMonitor.release()

        return result

    def checkShutdown(self):
        """ Simply return false causing this thread to die if we're shutting down """
        if Hellanzb.shutdown:
            raise SystemExit(Hellanzb.SHUTDOWN_CODE)
        return False

    def run(self):
        """ do the work and allow the thread to shutdown cleanly under all circumstances """
        try:
            self.waitLoop()
        except (AttributeError, NameError), e:
            # this can occur during shutdown
            pass
        except SystemExit:
            # FIXME: Can I safely raise here instead?
            pass
        except Exception, e:
            # Fatal logging problems should avoid printing via actual Hellanzb.Logging
            # methods
            print 'Error in ScrollInterrupter: ' + str(e)

    def lockScrollOutput(self):
        """ Prevent scroll output """
        ScrollableHandler.scrollLock.acquire()
        
    def releaseScrollOutput(self):
        """ Continue scroll output """
        ScrollableHandler.scrollLock.release()

    # FIXME: change self.wait to self.waitForRecord
    # make the wait(timeout) use the same function. shouldn't i just acquire the pending
    # monitor lock at the beginning and never release it?

    # FIXME: problem with this function is, you can definitely have a case where you were
    # notified and weren't wait()ing. you sort of have to manually look for any pending
    # records at the beginning of the loop or if i can never release the lock
    def waitLoop(self):
        """ wait for scroll interrupts, then break the scroll to print them """
        # hadQuickWait explained below. basically toggles whether or not we release the
        # scroll locks during the loop
        hadQuickWait = False

        # Continue waiting for scroll interrupts until shutdown
        while not self.checkShutdown():

            # See below
            if not hadQuickWait:
                # Wait until we're notified of a new log message
                self.wait()
                
                # We've been notified -- block the scroll output,
                ScrollableHandler.scrollLock.acquire()
                # and lock the data structure containing the new log messages
                ScrollInterrupter.pendingMonitor.acquire()
            else:
                # release the locks next time around unless we hadQuickWait again (see
                # below)
                hadQuickWait = False
            
            # copy all the new log messages and remove them from the pending list
            #records = self.scrollableHandler.scrollInterruptRecords[:]
            records = ScrollInterrupter.pendingLogRecords[:]
            ScrollInterrupter.pendingLogRecords = []

            # Print the new messages.
            for record in records:
                self.handle(record)
                
            self.checkShutdown()
            # Now that we've printed the log messages, we want to continue blocking the
            # scroll output for a few seconds. However if we're notified of a new pending
            # log (scroll interrupt) messages, we want to print it immediately, and
            # restart the 3 second count
            ScrollInterrupter.pendingMonitor.wait(Hellanzb.Logging.SCROLL_INTERRUPT_WAIT)

            # wait() won't tell us whether or not we were actually notified. If we were,
            # this would have been set to true (while notify() acquired the lock during
            # our wait())
            if ScrollInterrupter.notifiedMonitor:
                ScrollInterrupter.notifiedMonitor = False
                # We caught new log messages and want to continue interrutping the
                # scroll. So we won't release the locks the next time around the loop
                hadQuickWait = True
                
            else:
                # We waited a few seconds and weren't notified of new messages. Let the
                # scroll continue
                ScrollInterrupter.pendingMonitor.release()
                
                ScrollableHandler.scrollLock.release()

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

def warn(message):
    """ Log a message at the warning level """
    Hellanzb.logger.warn(message + '\n')

def error(message, exception = None):
    """ Log a message at the error level. Optionally log exception information """
    message = message
    
    if exception != None:
        if isinstance(exception, Exception):
            message += ': ' + getLocalClassName(exception.__class__) + ': ' + str(exception)
            
            if not isinstance(exception, FatalError):
                # Unknown/unexpected exception -- also show the stack trace
                stackTrace = StringIO()
                print_exc(file=stackTrace)
                stackTrace = stackTrace.getvalue()
                message += '\n' + stackTrace
        
    Hellanzb.logger.error(message + '\n')

def info(message, appendLF = True):
    """ Log a message at the info level """
    if appendLF:
        message += '\n'
    Hellanzb.logger.info(message)

def debug(message):
    """ Log a message at the debug level """
    Hellanzb.logger.debug(message + '\n')

def scroll(message):
    """ Log a message at the scroll level """
    Hellanzb.logger.log(ScrollableHandler.SCROLL, message)
    # Somehow the scroll locks end up getting blocked unless their consumers pause as
    # short as around 1/100th of a milli every loop. You might notice this delay when
    # nzbget scrolling looks like a slightly different FPS from within hellanzb than
    # running it directly
    time.sleep(.00001)

def growlNotify(type, title, description, sticky):
    """ send a message to the growl daemon via an xmlrpc proxy """
    # NOTE: growl doesn't tie in with logging yet because all it's sublevels/args makes it
    # not play well with the rest of the logging.py
    
    # FIXME: should validate the server information on startup, and catch connection
    # refused errors here
    if not Hellanzb.GROWL_NOTIFY:
        return

    addr = (Hellanzb.GROWL_SERVER, GROWL_UDP_PORT)
    s = socket(AF_INET,SOCK_DGRAM)

    p = GrowlRegistrationPacket(application="hellanzb", password=Hellanzb.GROWL_PASSWORD)
    p.addNotification("Archive Error", enabled=True)
    p.addNotification("Archive Success", enabled=True)
    p.addNotification("Error", enabled=True)
    p.addNotification("Queue", enabled=True)
    s.sendto(p.payload(), addr)
    
    p = GrowlNotificationPacket(application="hellanzb",
                                notification=type, title=title,
                                description=description, priority=1,
                                sticky=sticky)
    s.sendto(p.payload(),addr)
    s.close()

    return

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
    
def scrollBegin():
    """ Let the logger know we're beginning to scroll """
    ScrollableHandler.scrollFlag = True
    ScrollableHandler.scrollLock = Lock()
    stdinEchoOff()

def scrollEnd():
    """ Let the logger know we're done scrolling """
    stdinEchoOn()
    ScrollableHandler.scrollFlag = False
    del ScrollableHandler.scrollLock

def isDebugEnabled():
    if hasattr(Hellanzb, 'DEBUG_MODE') and Hellanzb.DEBUG_MODE != None and Hellanzb.DEBUG_MODE != False:
        return True
    return False

def initLogging():
    """ Setup logging """
    logging.addLevelName(ScrollableHandler.SCROLL, 'SCROLL')

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

    # FIXME: could move this to config file
    # How many seconds to delay the scroll for
    Hellanzb.Logging.SCROLL_INTERRUPT_WAIT = 5
    # 2 is for testing
    #Hellanzb.Logging.SCROLL_INTERRUPT_WAIT = 2


    # Whether or not scroll mode is on
    ScrollableHandler.scrollFlag = False
    # Whether or not there is currently output interrupting the scroll
    ScrollableHandler.scrollInterrupted = True
    # the lock that allows us interrupt scroll (is initialized via scrollEnd())
    ScrollableHandler.scrollLock = None

    # For communication to the scroll interrupter
    # FIXME: could put these in interrupter cstrctr. interrupter can throw an exception if
    # its instantiated twice
    ScrollInterrupter.pendingMonitor = Condition(Lock())
    ScrollInterrupter.notifiedMonitor = False
    ScrollInterrupter.pendingLogRecords = []

    # Start the thread after initializing all those variables (singleton)
    scrollInterrupter = ScrollInterrupter()
    scrollInterrupter.start()

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

    if isDebugEnabled():
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
