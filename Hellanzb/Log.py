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
import Hellanzb, time
from socket import AF_INET, SOCK_DGRAM, socket, error as socket_error
from threading import Lock
from traceback import print_exc
from Hellanzb.Logging import prettyException, stdinEchoOff, stdinEchoOn, ScrollableHandler
from Hellanzb.Growl import *
from Hellanzb.Util import getLocalClassName, FatalError
from StringIO import StringIO

__id__ = '$Id$'

def warn(message):
    """ Log a message at the warning level """
    Hellanzb.logger.warn(message + '\n')

def error(message, exception = None):
    """ Log a message at the error level. Optionally log exception information """
    prettyEx = prettyException(exception)
    if prettyEx != '':
        message += ': ' + prettyEx
    Hellanzb.logger.error(message + '\n')

def info(message, appendLF = True):
    """ Log a message at the info level """
    if appendLF:
        message += '\n'
    Hellanzb.logger.info(message)

def debug(message, exception = None):
    """ Log a message at the debug level """
    if Hellanzb.DEBUG_MODE_ENABLED:
        prettyEx = prettyException(exception)
        if prettyEx != '':
            message += ': ' + prettyEx
        Hellanzb.logger.debug(message + '\n')

def scroll(message):
    """ Log a message at the scroll level """
    Hellanzb.logger.log(ScrollableHandler.SCROLL, message)

def logShutdown(message):
    """ log messages ocurring just before shutdown, handled specially """
    Hellanzb.logger.log(ScrollableHandler.SHUTDOWN, message)

def growlNotify(type, title, description, sticky = False):
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
    try:
        s.sendto(p.payload(), addr)
    except socket_error, msg:
        s.close()
        debug('Unable to connect to Growl: ' + str(msg))
        return

    # Unicode the message, so the python Growl lib can succesfully UTF-8 it. It can fail
    # to UTF-8 the description if it contains unusual characters. we also have to force
    # latin-1, otherwise converting to unicode can fail too
    # (e.g. 'Secrets_of_SÃÂ£o_Paulo_(Full_DVD5_2003)')
    description = unicode(description, 'latin-1')
    
    p = GrowlNotificationPacket(application="hellanzb",
                                notification=type, title=title,
                                description=description, priority=1,
                                sticky=sticky, password=Hellanzb.GROWL_PASSWORD)
    try:
        s.sendto(p.payload(),addr)
    except socket_error, msg:
        debug('Unable to connect to Growl: ' + str(msg))

    s.close()
    
def scrollBegin():
    """ Let the logger know we're beginning to scroll """
    ScrollableHandler.scrollFlag = True
    stdinEchoOff()

def scrollEnd():
    """ Let the logger know we're done scrolling """
    stdinEchoOn()
    ScrollableHandler.scrollFlag = False

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
