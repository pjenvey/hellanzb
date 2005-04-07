"""
HellaReactor - Custom reactor (extends the default SelectReactor). Ties into the twisted
reactor system so it can catch signals, and shutdown hellanzb cleanly

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import Hellanzb, sys
from twisted.internet.default import SelectReactor
from twisted.internet.main import installReactor
from Hellanzb.Logging import *

__id__ = '$Id$'

class HellaReactor(SelectReactor):
    """ Handle taking care of PostProcessors during a SIGINT """

    def sigInt(self, *args):
        """ Core's signal handler will shut the app down appropriately (including the reactor) """
        try:
            from Hellanzb.Core import signalHandler
            signalHandler(*args)
        except SystemExit:
            pass

    def install(klass):
        """ Install custom reactor """
        if sys.modules.has_key('twisted.internet.reactor'):
            del sys.modules['twisted.internet.reactor']
        Hellanzb.reactor = HellaReactor()
        installReactor(Hellanzb.reactor)
    install = classmethod(install)

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
