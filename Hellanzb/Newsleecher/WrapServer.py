"""Wraps a bunch of news connections for a server."""

import getpass
import nntplib
import sys

from WrapNews import WrapNews

# ---------------------------------------------------------------------------

class WrapServer:
        def __init__(self, serverInfo):
                self.serverInfo = serverInfo
                self.name = self.serverInfo['id']
                
                self.Conns = {}
                
                self.Table = ''
        
        # ---------------------------------------------------------------------------
        # Open our connections
        def connect(self):
                # Get the info we need to connect
                _servers = self.serverInfo['hosts']
                _user = self.serverInfo['username']
                _pass = self.serverInfo['password']
                _bindto = self.serverInfo['bindto']
                
                if _bindto:
                        _bindto = _bindto.split(' ')
                else:
                        _bindto = (None,)
                
                # Ask for a password if we have to
                if _user and not _pass:
                        import getpass
                        prompt = "Password for '%s': " % (self.name)
                        _pass = getpass.getpass(prompt)
                
                print '(%s) Connecting...' % (self.name),
                sys.stdout.flush()
                
                # We only support 1-10 connections per server
                self.num_connects = max(1, min(10, self.serverInfo['connections']))
                
                # Build our connections
                success = 0
                
                for _server in _servers:
                        for _bind in _bindto:
                                for i in range(self.num_connects):
                                        try:
                                                _host, _port = _server.split(':')
                                                nwrap = WrapNews(self, _host, int(_port), _user, _pass, _bind)
                                        except Exception, msg:
                                                print 'WARNING: unable to connect: %s' % (msg)
                                        else:
                                                self.Conns[nwrap.nntp.sock.fileno()] = nwrap
                                                success += 1
                
                # We connected!
                if success == 1:
                        print 'opened %d connection.' % (success)
                else:
                        print 'opened %d connections.' % (success)
        
        # ---------------------------------------------------------------------------
        # Set a group to be active
        def set_group(self, newsgroup):
                # Naughty chars need to be changed
                table = newsgroup
                for char in '.-':
                        table = table.replace(char, '_')
                
                self.Table = '%s_%s' % (self.name, table)
                
                # Select the newsgroup
                for nwrap in self.Conns.values():
                        try:
                                groupdata = nwrap.nntp.group(newsgroup)
                        except nntplib.NNTPTemporaryError:
                                print "(%s) Group '%s' probably doesn't exist" % (self.name, newsgroup)
                                return None
                
                return groupdata
