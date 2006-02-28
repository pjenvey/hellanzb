# -*- coding: iso-8859-1 -*-
"""

HellanzbTestCase - All hellanzb tests should derive from this class

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import unittest
import Hellanzb.Core

__id__ = '$Id$'

# Strings requiring special handling. Mostly involves casting to/from unicode when writing
# them out to the screen, xml, or the filesystem
EVIL_STRINGS = ('SÃÂ£o_Paulo', 'Zappa_–_', '_Les_Rivières_Pourpres',
                '_SkandalÃ¶s_-_Ficken_Auf_Der_Strasse', 'test\xb4s  file.test',
                'é composed char', '\u00e9 escaped composed', '\u0065\u0301 escaped decomposed')
                
class HellanzbTestCase(unittest.TestCase):
    skip = False
    verbose = False
    
    def setUp(self):
        """ Initialize hellanzb core """
        #Hellanzb.Core.init()

    def tearDown(self):
        """ Take it down """
        #Hellanzb.Core.shutdown()

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
