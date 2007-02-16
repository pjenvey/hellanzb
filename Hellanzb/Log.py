# -*- coding: iso-8859-1 -*-
"""

Log - The basic log API functions, only -- to discourage polluting namespaces, e.g.:

      Bad: 
      from Hellanzb.Logging import *
      
      Better:
      from Hellanzb.Log import *

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import logging, time, Hellanzb
try:
    import pynotify
except ImportError:
    pynotify = None
from socket import AF_INET, SOCK_DGRAM, socket, error as socket_error
from threading import Lock
from traceback import print_exc
from Hellanzb.Logging import LogOutputStream, lockScrollableHandlers, prettyException, \
    stdinEchoOff, stdinEchoOn, ScrollableHandler
from Hellanzb.Growl import *
from Hellanzb.Util import getLocalClassName, toUnicode, FatalError
from StringIO import StringIO

__id__ = '$Id$'

def warn(message):
    """ Log a message at the warning level """
    Hellanzb.recentLogs.append(logging.WARN, message)
    
    Hellanzb.logger.warn('%s\n' % message)

def error(message, exception = None, appendLF = True):
    """ Log a message at the error level. Optionally log exception information """
    prettyEx = prettyException(exception)
    if prettyEx != '':
        message = '%s: %s' % (message, prettyEx)
        
    Hellanzb.recentLogs.append(logging.ERROR, message)
    
    if appendLF:
        message = '%s\n' % message
    Hellanzb.logger.error(message)

def info(message, appendLF = True, saveRecent = True):
    """ Log a message at the info level """
    if saveRecent:
        Hellanzb.recentLogs.append(logging.INFO, message)
    
    if appendLF:
        message = '%s\n' % message
    Hellanzb.logger.info(message)

def debug(message, exception = None, appendLF = True):
    """ Log a message at the debug level """
    if Hellanzb.DEBUG_MODE_ENABLED:
        if exception != None:
            prettyEx = prettyException(exception)
            if prettyEx != '':
                message = '%s: %s' % (message, prettyEx)
        if appendLF:
            message = '%s\n' % message
        Hellanzb.logger.debug(message)

def scroll(message):
    """ Log a message at the scroll level """
    Hellanzb.logger.log(ScrollableHandler.SCROLL, message)

def logShutdown(message):
    """ log messages ocurring just before shutdown, handled specially """
    Hellanzb.recentLogs.append(logging.WARN, message)
    
    Hellanzb.logger.log(ScrollableHandler.SHUTDOWN, message)

def logFile(message, exception = None, appendLF = True):
    """ Log a message to only the log file (and not the console) """
    prettyEx = prettyException(exception)
    if prettyEx != '':
        message = '%s: %s' % (message, prettyEx)
    if appendLF:
        message = '%s\n' % message
    Hellanzb.logger.log(ScrollableHandler.LOGFILE, message)

def noLogFile(message, appendLF = True):
    """ Send a message to stdout, avoiding both log files"""
    Hellanzb.recentLogs.append(logging.INFO, message)
    
    if appendLF:
        message = '%s\n' % message
    Hellanzb.logger.log(ScrollableHandler.NOLOGFILE, message)

def notify(type, title, description, sticky = False):
    """ send the notification message to both Growl and LibNotify Daemon """
    growlNotify(type, title, description, sticky)
    libnotifyNotify(type, title, description, sticky)

def libnotifyNotify(type, title, description, sticky = False):
    """ send a message to libnotify daemon """
    if not Hellanzb.LIBNOTIFY_NOTIFY:
        return

    n = pynotify.Notification(title, description)
    n.set_category(type)
    if not sticky:
        n.set_timeout(10000) # 10 Seconds

    if not n.show():
        debug('Failed to send libnotify notification')

def growlNotify(type, title, description, sticky = False):
    """ send a message to the remote growl daemon via udp """
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
    try:
        s.sendto(p.payload(), addr)
    except socket_error, msg:
        s.close()
        debug('Unable to connect to Growl: ' + str(msg))
        return

    # Unicode the message, so the python Growl lib can succesfully UTF-8 it. It can fail
    # to UTF-8 the description if it contains unusual characters. we also have to force
    # latin-1, otherwise converting to unicode can fail too
    # (e.g. 'SÃÂ£o_Paulo')
    description = toUnicode(description)
    
    p = GrowlNotificationPacket(application="hellanzb",
                                notification=type, title=title,
                                description=description, priority=1,
                                sticky=sticky, password=Hellanzb.GROWL_PASSWORD)
    try:
        s.sendto(p.payload(),addr)
    except socket_error, msg:
        debug('Unable to connect to Growl: ' + str(msg))

    s.close()
    
def _scrollBegin():
    """ Let the logger know we're beginning to scroll """
    ScrollableHandler.scrollFlag = True
    if not Hellanzb.SHUTDOWN:
        stdinEchoOff()

def scrollBegin():
    """ Let the logger know we're beginning to scroll """
    lockScrollableHandlers(_scrollBegin)

def _scrollEnd():
    """ Let the logger know we're done scrolling """
    # FIXME: what happens if we are CTRL-Ced in the middle of this?
    Hellanzb.scroller.killHistory()
    
    stdinEchoOn()
    ScrollableHandler.scrollFlag = False

    info('', saveRecent = False)
    
def scrollEnd():
    """ Let the logger know we're done scrolling """
    lockScrollableHandlers(_scrollEnd)

def logStateXML(logFunction, showHeader = True):
    """ Print hellanzb's state xml via the specified log function """
    buf = StringIO()
    Hellanzb._writeStateXML(buf)
    header = ''
    if showHeader:
        header = 'hellanzb state xml:\n'
    logFunction('%s%s' % (header, buf.getvalue()))

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
