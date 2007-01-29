"""

NewzbinDownloader - Downloads NZBs directly from v3.newzbin.com via the
DirectNZB API.

(c) Copyright 2007 Dan Borello
[See end of file]
"""
import httplib, os, random, shutil, time, threading, urllib, Hellanzb.NZBQueue
from twisted.internet import reactor
from Hellanzb.Log import *
from Hellanzb.NZBDownloader import NZBDownloader

__id__ = '$Id$'

class NewzbinDownloader(NZBDownloader, threading.Thread):
    """Download the NZB file with the specified msgid from newzbin.com via
    their DirectNZB interface, by instantiating this class and calling
    download()"""

    def __init__(self, msgId):
        threading.Thread.__init__(self)
        self.msgId = msgId

    def download(self):
        self.start()

    def run(self):
        """Fetch an NZB from newzbin.com and add it to the queue."""
        response = self.attemptDownload()
        attempt = 1
        while not response.getheader('X-DNZB-RCode') == '200':
            if response.getheader('X-DNZB-RCode') == '450':
                if attempt >= 5:
                    error('Unable to download newzbin NZB: %s due to rate limiting. Will '
                          'not retry' % (self.msgId))
                    return
                # This is a poor way to do this.  Should actually calculate wait time.
                wait = round(int(response.getheader('X-DNZB-RText').split(' ')[3]) + \
                        random.random()*30,0)
                error('Unable to download newzbin NZB: %s (Attempt: %s) will retry in %i '
                      'seconds' % (self.msgId, attempt, wait))
                time.sleep(wait)
                response = self.attemptDownload()
                attempt += 1            
            else:    
                error('Unable to download newzbin NZB: %s (%s: %s)' % \
                          (self.msgId,
                           response.getheader('X-DNZB-RCode', 'No Code'),
                           response.getheader('X-DNZB-RText', 'No Error Text')))
                return
        cleanName = response.getheader('X-DNZB-Name').replace('/','_').replace('\\','_')
        dest = os.path.join(Hellanzb.TEMP_DIR, '%s_%s.nzb' % (self.msgId, cleanName))
         # Pass category information on
        category = None

        if Hellanzb.CATEGORIZE_DEST:
            category = response.getheader('X-DNZB-Category')

        out = open(dest, 'wb')
        shutil.copyfileobj(response, out)
        out.close()

        reactor.callFromThread(self.enqueue, dest, category)
        return True
    
    def __str__(self):
        return '%s(%s):' % (self.__class__.__name__, self.msgId)

    def enqueue(self, file, category):
        """ Enqueue the file, then delete it when finished. Intended to be called within
        the reactor """
        Hellanzb.NZBQueue.enqueueNZBs(file, category = category)
        os.remove(file)

    def canDownload():
        """ Whether or not the conf file supplied www.newzbin.com login info """
        noInfo = lambda var : not hasattr(Hellanzb, var) or getattr(Hellanzb, var) == None
        if noInfo('NEWZBIN_USERNAME') or noInfo('NEWZBIN_PASSWORD'):
                return False
        return True

    def attemptDownload(self):
        """Attempt to fetch nzb, return headers and nzb"""
        info('Downloading newzbin ID: ' + self.msgId)
        params = urllib.urlencode({'username': Hellanzb.NEWZBIN_USERNAME,
                                   'password': Hellanzb.NEWZBIN_PASSWORD,
                                   'reportid': self.msgId})
        headers = {'User-Agent': self.AGENT,
                   'Content-type': 'application/x-www-form-urlencoded',
                   'Accept': 'text/plain'}
        conn = httplib.HTTPConnection("v3.newzbin.com")
        conn.request("POST", '/dnzb/', params, headers)
        response = conn.getresponse()
        conn.close()
        return response

    canDownload = staticmethod(canDownload)

"""
Copyright (c) 2007 Dan Borello
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
