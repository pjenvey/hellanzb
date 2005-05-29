"""
HTPasswdAuth - Originally from Andrew Bennets htpasswdauth.py w/ modifications
(http://twistedmatrix.com/pipermail/twisted-python/2003-July/005118.html)

Provides a twisted Resource wrapper to shield it from requests via typical 
HTTP auth

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import md5
from twisted.web import static
from twisted.web.resource import Resource
from twisted.protocols import http
from Hellanzb.Log import debug

__id__ = '$Id$'

__all__ = ['HtPasswdWrapper']

class UnauthorizedResource(Resource):
    isLeaf = 1
    def __init__(self, realm, errorPage):
        Resource.__init__(self)
        self.realm = realm
        self.errorPage = errorPage

    def render(self, request):
        request.setResponseCode(http.UNAUTHORIZED)
        # FIXME: Does realm need to be quoted?
        request.setHeader('WWW-authenticate', 'basic realm="%s"' % self.realm)
        return self.errorPage.render(request)

class HtPasswdWrapper(Resource):
    """Apache-style htpasswd protection for a resource.

    Requires a client to authenticate (using HTTP basic auth) to access a
    resource.  If they fail to authenticate, or their username and password
    aren't accepted, they receive an error page.

    The username and password are checked against the specified values using
    md5.

    @cvar unauthorizedPage: L{Resource} that will be used to render the error
        page given when a user is unauthorized.
    """

    unauthorizedPage = static.Data(
        '<html><body>Access Denied.</body></html>', 'text/html'
    )

    def __init__(self, resource, user, password, realm):
        """Constructor.
        
        @param resource: resource to protect with authentication.
        @param user: the htpasswd user
        @param password: the htpasswd pass
        @param realm: HTTP auth realm.
        """
        Resource.__init__(self)
        
        self.resource = resource
        self.realm = realm
        
        self.user = user
        
        m = md5.new()
        m.update(password)
        del password
        self.passwordDigest = m.digest()

    def getChildWithDefault(self, path, request):
        if self.authenticateUser(request):
            return self.resource.getChildWithDefault(path, request)
        else:
            return self.unauthorized()

    def render(self, request):
        if self.authenticateUser(request):
            return self.resource.render(request)
        else:
            return self.unauthorized().render(request)

    def authenticateUser(self, request):
        username, password = request.getUser(), request.getPassword()
        
        m = md5.new()
        m.update(password)
        
        authenticated = username == self.user and self.passwordDigest == m.digest()
        if authenticated:
            debug('Successful HTTP Basic auth, user: ' + self.user)
        else:
            debug('Failed HTTP Basic auth, user: ' + self.user)
        return authenticated

    def unauthorized(self):
        return UnauthorizedResource(self.realm, self.unauthorizedPage)


if __name__ == '__main__':
    # Quick & dirty testing...
    
    # create the intarweb
    from twisted.web.server import Site
    root = Resource()
    sit = Site(HtPasswdWrapper(root, 'butt', 'head', 'test site'))
    #sit = Site(root)

    root.putChild('', static.Data('If you can see this, you are authorized!  Congrats!', 'text/plain'))
    root.putChild('blah', static.Data('Bring me a child!!', 'text/plain'))

    # and finally talk to the internat
    from twisted.internet import reactor
    reactor.listenTCP(18080, sit)
    reactor.run()
    
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
 * $Id: HellaReactor.py 248 2005-05-03 07:58:12Z pjenvey $
 */
"""
