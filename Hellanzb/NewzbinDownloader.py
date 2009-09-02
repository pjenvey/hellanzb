"""
NewzbinDownloader - Downloads NZBs directly from v3.newzbin.com via the
DirectNZB API: http://docs.newzbin.com/Newzbin::DirectNZB

(c) Copyright 2005-2007 Philip Jenvey
                        Thomas Hurst <freaky@newzbin.com>
                        Dan Borello
[See end of file]
"""
import os, random, Hellanzb.NZBQueue
from twisted.internet import reactor
from twisted.internet.error import ConnectionRefusedError, DNSLookupError, TimeoutError
from twisted.web.client import HTTPClientFactory
from twisted.web.error import Error
from Hellanzb.Log import *
from Hellanzb.NZBDownloader import NZBDownloader, StoreHeadersHTTPDownloader
from Hellanzb.Util import tempFilename

__id__ = '$Id$'

class NewzbinDownloader(NZBDownloader):
    """ Download the NZB file with the specified msgid from www.newzbin.com, by instantiating
    this class and calling download() """

    HEADERS = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept-Encoding': 'gzip',
        'Accept': 'text/plain'
        }
    url = 'http://www.newzbin.com/api/dnzb/'
    
    def __init__(self, msgId):
        """ Initialize the downloader with the specified msgId string """
        self.msgId = msgId

        # The HTTPDownloader
        self.downloader = None

        # Write the downloaded NZB here temporarily
        self.tempFilename = os.path.join(Hellanzb.TEMP_DIR,
                                         tempFilename(self.TEMP_FILENAME_PREFIX) + '.nzb')

        # The real NZB filename determined from HTTP headers
        self.nzbFilename = None

        # Whether or not it appears that this NZB with the msgId does not exist on newzbin
        self.nonExistantNZB = False

        # DNZB error message
        self.errMessage = False

        # Number of attempts to download this NZB
        self.attempt = 0

    def gotHeaders(self, headers):
        """ The downloader will feeds headers via this function """
        super(self.__class__, self).gotHeaders(headers)
        if headers.has_key('x-dnzb-name'):
            name = headers.get('x-dnzb-name')[0]
            # XXX may want to sanitize a little more
            cleanName = name.replace('/', '_').replace('\\','_')
            self.nzbFilename = '%s_%s.nzb' % (self.msgId, cleanName)
        else:
            # The failure case will go to the generic error handler atm, so this is most likely unused
            if headers.has_key('x-dnzb-rtext'):
                self.errMessage = headers.get('x-dnzb-rtext')[0]
            else:
                self.errMessage = 'DNZB service error'

            info('DNZB request failed: %s' % self.errMessage)
            self.nzbFilename = None
            if headers.has_key('x-dnzb-rcode') and headers.get('x-dnzb-rcode')[0] == '404':
                self.nonExistantNZB = True
        self.nzbCategory = headers.get('x-dnzb-category')[0]

    def download(self):
        """ Start the NZB download process """
        debug(str(self) + ' Downloading from newzbin.com..')
        if not NewzbinDownloader.canDownload():
            debug(str(self) + ' download: No www.newzbin.com login information')
            return

        info('Downloading newzbin NZB: %s ' % self.msgId)
        self.handleNZBDownloadFromNewzbin()

    def handleNZBDownloadFromNewzbin(self):
        """ Download the NZB """
        debug(str(self) + ' handleNZBDownloadFromNewzbin')

        # XXX erm, URL encoding needed?
        postdata = 'username=' + Hellanzb.NEWZBIN_USERNAME
        postdata += '&password=' + Hellanzb.NEWZBIN_PASSWORD
        postdata += '&reportid=' + self.msgId

        # This will be www.newzbin.com eventually
        self.downloader = StoreHeadersHTTPDownloader(self.url, self.tempFilename, method = 'POST',
                                                     headers = self.HEADERS, postdata = postdata,
                                                     agent = self.AGENT)
        self.downloader.deferred.addCallback(self.handleEnqueueNZB)
        self.downloader.deferred.addErrback(self.errBack)

        reactor.connectTCP('v3.newzbin.com', 80, self.downloader)

    def handleEnqueueNZB(self, page):
        """ Add the new NZB to the queue"""
        if super(self.__class__, self).handleEnqueueNZB(page):
            Hellanzb.NZBQueue.writeStateXML()
        else:
            msg = 'Unable to download newzbin NZB: %s' % self.msgId
            if self.errMessage:
                error('%s (%s)' % [msg, self.errMessage])
            elif self.nonExistantNZB:
                error('%s (This appears to be an invalid msgid)' % msg)
            else:
                error('%s (Incorrect NEWZBIN_USERNAME/PASSWORD?)' % msg)
                # Invalidate the cached cookies
                Hellanzb.NZBQueue.writeStateXML()

    def errBack(self, reason):
        if not reason.check(Error):
            return super(self.__class__, self).errBack(reason)

        headers = self.downloader.response_headers
        rcode = headers.get('x-dnzb-rcode', [None])[0]
        if rcode == '450':
            self.attempt += 1
            if self.attempt >= 5:
                error('Unable to download newzbin NZB: %s due to rate limiting. Will '
                      'not retry' % (self.msgId))
                return

            rtext = headers.get('x-dnzb-rtext', [''])[0]
            try:
                newzbinWait = int(rtext.split(' ')[3])
            except IndexError, ValueError:
                # Invalid DNZB-RText
                newzbinWait = 60
            wait = round(newzbinWait + random.random() * 15, 0)

            if not rtext:
                rtext = "'no error message'"
            error('Unable to download newzbin NZB: %s (newzbin said: %s) will '
                  'retry in %i seconds (attempt: %i)' % \
                      (self.msgId, rtext, wait, self.attempt))
            reactor.callLater(wait, self.download)
            return
        elif rcode != '200':
            error('Unable to download newzbin NZB: %s (%s: %s)' % \
                      (self.msgId,
                       headers.get('x-dnzb-rcode', ['No Code'])[0],
                       headers.get('x-dnzb-rtext', ['No Error Text'])[0]))
            return
    
    def __str__(self):
        return '%s(%s):' % (self.__class__.__name__, self.msgId)

    def canDownload():
        """ Whether or not the conf file supplied www.newzbin.com login info """
        noInfo = lambda var : not hasattr(Hellanzb, var) or getattr(Hellanzb, var) == None

        if noInfo('NEWZBIN_USERNAME') or noInfo('NEWZBIN_PASSWORD'):
            return False
        return True
    canDownload = staticmethod(canDownload)

"""
Copyright (c) 2005-2007 Philip Jenvey <pjenvey@groovie.org>
                        Thomas Hurst <freaky@newzbin.com>
                        Dan Borello
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
