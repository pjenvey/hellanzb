"""

NewzbinDownloader - Downloads NZBs directly from www.newzbin.com

I don't particularly like this feature -- it's bound to break the minute newzbin changes
its website around, and I personally don't find it all that useful. Alas I see why some
people might want it so here it is -pjenvey

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import os
from random import randint
from shutil import move
from twisted.internet import reactor
from twisted.internet.error import ConnectionRefusedError, DNSLookupError, TimeoutError
from twisted.web.client import HTTPClientFactory, HTTPDownloader
from urllib import splitattr, splitvalue
from Hellanzb.Log import *

__id__ = '$Id$'

class StoreCookieHTTPClientFactory(HTTPClientFactory):
    """ Extract the cookies from the received page and pass them to the cookieListener """
    
    def __init__(self, url, cookieListener = None, *args, **kargs):
        self.cookieListener = cookieListener
        
        HTTPClientFactory.__init__(self, url, *args, **kargs)

    def gotHeaders(self, headers):
        if headers.has_key('set-cookie'):
            self.cookieListener.gotCookies(self.parseCookies(headers['set-cookie']))
            
        HTTPClientFactory.gotHeaders(self, headers)

    def parseCookies(self, cookieHeader):
        """ Parse the cookies into a dict and return it """
        cookies = {}
        for cookie in cookieHeader:
            cookparts = cookie.split(';')
            cook = cookparts[0]
            cook.lstrip()
            k, v = cook.split('=', 1)
            cookies[k.lstrip()] = v.lstrip()

        return cookies

class StoreHeadersHTTPDownloader(HTTPDownloader):
    """ Give the headers to the headerListener """
    def __init__(self, url, fileOrName, headerListener = None, *args, **kargs):
        self.headerListener = headerListener
        HTTPDownloader.__init__(self, url, fileOrName, *args, **kargs)
        
    def gotHeaders(self, headers):
        self.headerListener.gotHeaders(headers)
        HTTPDownloader.gotHeaders(self, headers)

class NewzbinDownloader:
    """ Download the NZB file with the specified msgid from www.newzbin.com, by instantiating
    this class and calling download() """

    AGENT = 'hellanzb/' + Hellanzb.version
    HEADERS = { 'Content-Type': 'application/x-www-form-urlencoded'}
    GET_NZB_URL = 'http://www.newzbin.com/browse/post/____ID____/msgids/msgidlist_post____ID____.nzb'
    TEMP_FILENAME_PREFIX = Hellanzb.TEMP_DIR + os.sep + 'hellanzb-newzbin-download'
    
    def __init__(self, msgId):
        self.msgId = msgId
        self.cookies = {}
        self.tempFilename = self.TEMP_FILENAME_PREFIX + str(randint(10000000, 99999999)) + '.nzb'

    def gotCookies(self, cookies):
        """ The downloader will feeds cookies via this function """
        # Grab the cookies for the PHPSESSID
        self.cookies = cookies
        debug('NewzbinDownloader: gotCookies: ' + str(self.cookies))

    def gotHeaders(self, headers):
        """ The downloader will feeds headers via this function """
        debug('NewzbinDownloader: gotHeaders')
        # Grab the file name of the NZB via content-disposition header
        keys = headers.keys()

        found = None
        for key in keys:
            if key.lower() == 'content-disposition':
                found = key
                break

        type, attrs = splitattr(headers[found][0])
        key, val = splitvalue(attrs[0].strip())
        self.nzbFilename = val
        debug('NewzbinDownloader: got filename: ' + self.nzbFilename)
        
    def download(self):
        """ Download the NZB. Return a deferred """
        debug('NewzbinDownloader: Downloading from www.newzbin.com..')
        if not NewzbinDownloader.canDownload():
            debug('NewzbinDownloader: download: No www.newzbin.com login information')
            # FIXME: raise here instead?
            return
        
        httpc = StoreCookieHTTPClientFactory('http://www.newzbin.com/account/login/',
                                             cookieListener = self, agent = self.AGENT)
        httpc.deferred.addCallback(self.handleNewzbinLogin)
        httpc.deferred.addErrback(self.errBack)

        reactor.connectTCP('www.newzbin.com', 80, httpc)

    def handleNewzbinLogin(self, page):
        """ Login to newzbin """
        debug('NewzbinDownloader: handleNewzbinLogin')
        if not self.cookies.has_key('PHPSESSID'):
            debug('NewzbinDownloader: handleNewzbinLogin: There was a problem, no PHPSESSID provided')
            return

        postdata = 'username=' + Hellanzb.NEWZBIN_USERNAME
        postdata += '&password=' + Hellanzb.NEWZBIN_PASSWORD
        
        httpc = HTTPClientFactory('http://www.newzbin.com/account/login/', method = 'POST',
                                  headers = self.HEADERS, postdata = postdata,
                                  agent = self.AGENT)
        httpc.cookies = {'PHPSESSID' : self.cookies['PHPSESSID']}
        httpc.deferred.addCallback(self.handleNZBDownloadFromNewzbin)
        httpc.deferred.addErrback(self.errBack)

        reactor.connectTCP('www.newzbin.com', 80, httpc)    
    
    def handleNZBDownloadFromNewzbin(self, page):
        """ Download the NZB after successful login """
        debug('NewzbinDownloader: handleNZBDownloadFromNewzbin')
                         
        httpd = StoreHeadersHTTPDownloader(self.GET_NZB_URL.replace('____ID____', self.msgId),
                                           self.tempFilename, headerListener = self,
                                           agent = self.AGENT)
        httpd.cookies = {'PHPSESSID' : self.cookies['PHPSESSID']}
        httpd.deferred.addCallback(self.handleEnqueueNZB)
        httpd.deferred.addErrback(self.errBack)

        reactor.connectTCP('www.newzbin.com', 80, httpd)
    
    def handleEnqueueNZB(self, page):
        """ Add the new NZB to the queue"""
        debug('NewzbinDownloader: handleEnqueueNZB')

        move(self.tempFilename, Hellanzb.QUEUE_DIR + os.sep + self.nzbFilename)

    def errBack(self, reason):
        if reason.check(TimeoutError):
            error('Unable to connect to www.newzbin.com: Connection timed out')
        elif reason.check(ConnectionRefusedError):
            error('Unable to connect to www.newzbin.com: Connection refused')
        elif reason.check(DNSLookupError):
            error('Unable to connect to www.newzbin.com: DNS lookup failed')
        else:
            error('Unable to download from www.newzbin.com: ' + str(reason))

    def canDownload():
        """ Whether or not the conf file supplied www.newzbin.com login info """
        noInfo = lambda var : not hasattr(Hellanzb, var) or getattr(Hellanzb, var) == None

        if noInfo('NEWZBIN_USERNAME') or noInfo('NEWZBIN_PASSWORD'):
            return False
        return True
    canDownload = staticmethod(canDownload)

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
