"""

NewzbinDownloader - Downloads NZBs directly from www.newzbin.com

I don't particularly like this feature -- it's bound to break the minute newzbin changes
its website around, and I personally don't find it all that useful. Alas I see why some
people might want it so here it is -pjenvey

(c) Copyright 2007 Dan Bordello
[See end of file]
"""
import os, httplib, urllib, Hellanzb.NZBQueue
from Hellanzb.Log import *
from Hellanzb.NZBDownloader import NZBDownloader

__id__ = '$Id$'

class NewzbinDownloader(object):

        def download(self, msgId):
                """Fetch an NZB from newzbin.com and add it to the queue."""
                info('Downloading newzbin ID: ' + msgId)
                params = urllib.urlencode({'username': Hellanzb.NEWZBIN_USERNAME,
                                           'password': Hellanzb.NEWZBIN_PASSWORD,
                                           'reportid': msgId})
                headers = {"Content-type": "application/x-www-form-urlencoded",
                           "Accept": "text/plain"}
                conn = httplib.HTTPConnection("v3.newzbin.com")
                conn.request("POST", "/dnzb/", params, headers)
                response = conn.getresponse()
                if not response.getheader('X-DNZB-RCode') == '200':             
                        error('Unable to download newzbin NZB: %s (%s: %s)' % \
                                      (msgId, response.getheader('X-DNZB-RCode', 'No Code'),
                                       response.getheader('X-DNZB-RText', 'No Error Text')))
                                                                 
                        return
                cleanName = response.getheader('X-DNZB-Name').replace('/','').replace('\\','')
                dest = os.path.join(Hellanzb.QUEUE_DIR, '%s_%s.nzb' % (msgId, cleanName))

                # Pass category information on
                category = None
                if Hellanzb.CATEGORIZE_DEST:
                        category = response.getheader('X-DNZB-Category')                
                
                out = open(dest, 'wb')
                out.write(response.read())
                out.close
                conn.close()
                
                Hellanzb.NZBQueue.enqueueNZBs(dest, category = category)
                return True

        def canDownload():
                """ Whether or not the conf file supplied www.newzbin.com login info """
                noInfo = lambda var : not hasattr(Hellanzb, var) or getattr(Hellanzb, var) == None
                if noInfo('NEWZBIN_USERNAME') or noInfo('NEWZBIN_PASSWORD'):
                        return False
                return True

        canDownload = staticmethod(canDownload)

"""
Copyright (c) 2007 Dan Bordello
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
