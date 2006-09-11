"""
NZBDownloader - Download and enqueue NZBs at the specified URL.

FIXME: NewzbinDownloader should extend NZBDownloader

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import base64, os, string, urllib, urlparse, Hellanzb.NZBQueue
from twisted.internet import reactor
from twisted.internet.error import ConnectionRefusedError, DNSLookupError, TimeoutError
from twisted.web.client import HTTPDownloader
from urllib import splitattr, splitvalue
from Hellanzb.Log import *
from Hellanzb.Util import tempFilename

__id__ = '$Id$'

class StoreHeadersHTTPDownloader(HTTPDownloader):
    """ Give the headers to the headerListener """
    def __init__(self, url, fileOrName, headerListener = None, *args, **kargs):
        self.headerListener = headerListener
        HTTPDownloader.__init__(self, url, fileOrName, *args, **kargs)
        
    def gotHeaders(self, headers):
        self.headerListener.gotHeaders(headers)
        HTTPDownloader.gotHeaders(self, headers)

class NZBDownloader(object):
    """ Download the NZB file at the specified URL """

    AGENT = 'hellanzb/' + Hellanzb.version
    TEMP_FILENAME_PREFIX = 'hellanzb-newzbin-download'

    def __init__(self, url):
        """ Initialize the downloader with the specified url string """
        # FIXME: support HTTPS
        scheme, host, path, params, query, fragment = urlparse.urlparse(url)
        
        auth, host = urllib.splituser(host)
        self.host, self.port = urllib.splitport(host)
        if not self.port:
            self.port = 80

        self.username = self.password = None
        if auth:
            self.username, self.password = urllib.splitpasswd(auth)

        self.url = urlparse.urlunparse((scheme, host, path, params, query, fragment))

        self.nzbFilename = os.path.basename(path)
        self.tempFilename = os.path.join(Hellanzb.TEMP_DIR,
                                         tempFilename(self.TEMP_FILENAME_PREFIX) + '.nzb')

    def download(self):
        """ Start the NZB download process """
        msg = 'Downloading from %s..' % self.url
        debug('%s %s' % (str(self), msg))
        info(msg)

        self.handleNZBDownload()

    def gotHeaders(self, headers):
        """ The downloader will feeds headers via this function """
        debug(str(self) + ' gotHeaders')
        # Grab the file name of the NZB via content-disposition header
        keys = headers.keys()

        found = None
        for key in keys:
            if key.lower() == 'content-disposition':
                found = key
                break

        if found is None:
            return

        type, attrs = splitattr(headers[found][0])
        key, val = splitvalue(attrs[0].strip())
        val = val.strip().strip('"')
        if val:
            debug(str(self) + ' gotHeaders: found filename: %s' % val)
            self.nzbFilename = val

    def handleNZBDownload(self):
        """ Download the NZB """
        debug(str(self) + ' handleNZBDownload')

        headers = {}

        if self.username:
            authString = self.username + ':'
            if self.password:
                authString += self.password

            auth = base64.encodestring(urllib.unquote(authString))
            auth = string.join(string.split(auth), "") # get rid of whitespace
            headers['Authorization'] = 'Basic ' + auth

        httpd = StoreHeadersHTTPDownloader(self.url, self.tempFilename,
                                           headerListener = self, headers = headers,
                                           agent = self.AGENT)
        httpd.deferred.addCallback(self.handleEnqueueNZB)
        httpd.deferred.addErrback(self.errBack)

        reactor.connectTCP(self.host, self.port, httpd)
    
    def handleEnqueueNZB(self, page):
        """ Add the new NZB to the queue"""
        debug(str(self) + ' handleEnqueueNZB')

        if self.nzbFilename == None:
            debug(str(self) + ' handleEnqueueNZB: no nzbFilename found, aborting!')
            os.rename(self.tempFilename, os.path.join(Hellanzb.TEMP_DIR, 'Newzbin.error'))
            return False

        dest = os.path.join(os.path.dirname(self.tempFilename), self.nzbFilename)
        os.rename(self.tempFilename, dest)
        
        Hellanzb.NZBQueue.enqueueNZBs(dest)

        os.remove(dest)
        return True
        
    def errBack(self, reason):
        if os.path.isfile(self.tempFilename):
            os.remove(self.tempFilename)
            
        if Hellanzb.SHUTDOWN:
           return
       
        if reason.check(TimeoutError):
            error('Unable to connect to %s: Connection timed out' % self.url)
        elif reason.check(ConnectionRefusedError):
            error('Unable to connect to %s: Connection refused' % self.url)
        elif reason.check(DNSLookupError):
            error('Unable to connect to %s: DNS lookup failed' % self.url)
        else:
            error('Unable to download from %s: %s' % (self.url, str(reason)))

    def __str__(self):
        return '%s(%s):' % (self.__class__.__name__, self.url)

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
