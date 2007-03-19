"""
UnPrettyBytesTestCase

(c) Copyright 2007 Philip Jenvey
[See end of file]
"""
from Hellanzb.test import HellanzbTestCase
from Hellanzb.Log import *
from Hellanzb.Util import unPrettyBytes

__id__ = '$Id: DupeNameTestCase.py 832 2006-09-11 05:22:00Z pjenvey $'

class UnPrettyBytesTestCase(HellanzbTestCase):

    def testUnPrettyBytes(self):
        self.assertEqual(-1, unPrettyBytes(-1))
        self.assertEqual(102034934, unPrettyBytes(102034934))
        self.assertEqual(1024, unPrettyBytes('1KB'))
        self.assertEqual(1024, unPrettyBytes('1K'))
        self.assertEqual(104857600, unPrettyBytes('100MB'))
        self.assertEqual(104857600, unPrettyBytes('100M'))
        self.assertEqual(131072000, unPrettyBytes(131072000))
        self.assertEqual(131072000, unPrettyBytes('125MB'))
        self.assertEqual(131072000, unPrettyBytes('125M'))
        self.assertEqual(21474836480, unPrettyBytes('20GB'))
        self.assertEqual(21474836480, unPrettyBytes('20G'))
        
"""
Copyright (c) 2007 Philip Jenvey <pjenvey@groovie.org>
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

$Id: DupeNameTestCase.py 832 2006-09-11 05:22:00Z pjenvey $
"""
