# ---------------------------------------------------------------------------
# $Id: WrapNews.py,v 1.10 2004/10/09 07:28:57 freddie Exp $
# ---------------------------------------------------------------------------
# A class to wrap an nntplib connection into something useful, yeargh!

import nntplib
import socket

# ---------------------------------------------------------------------------
# Need to override __init__ to allow us to bind(), ugh :(
class EvilNNTP(nntplib.NNTP):
        def __init__(self, host, port=nntplib.NNTP_PORT, user=None, password=None,
                                readermode=None, bindto=None):
                self.host = host
                self.port = port
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                if bindto:
                        self.sock.bind((bindto, 0))
                self.sock.connect((self.host, self.port))
                self.file = self.sock.makefile('rb')
                self.debugging = 0
                self.welcome = self.getresp()
                
                # 'mode reader' is sometimes necessary to enable 'reader' mode.
                # However, the order in which 'mode reader' and 'authinfo' need to
                # arrive differs between some NNTP servers. Try to send
                # 'mode reader', and if it fails with an authorization failed
                # error, try again after sending authinfo.
                readermode_afterauth = 0
                if readermode:
                        try:
                                self.welcome = self.shortcmd('mode reader')
                        except nntplib.NNTPPermanentError:
                                # error 500, probably 'not implemented'
                                pass
                        except nntplib.NNTPTemporaryError, e:
                                if user and e.response[:3] == '480':
                                        # Need authorization before 'mode reader'
                                        readermode_afterauth = 1
                                else:
                                        raise
                # Perform NNRP authentication if needed.
                if user:
                        resp = self.shortcmd('authinfo user '+user)
                        if resp[:3] == '381':
                                if not password:
                                        raise nntplib.NNTPReplyError(resp)
                                else:
                                        resp = self.shortcmd('authinfo pass '+password)
                                        if resp[:3] != '281':
                                                raise nntplib.NNTPPermanentError(resp)
                        if readermode_afterauth:
                                try:
                                        self.welcome = self.shortcmd('mode reader')
                                except nntplib.NNTPPermanentError:
                                        # error 500, probably 'not implemented'
                                        pass

# ---------------------------------------------------------------------------

class WrapNews:
        "A class to wrap an nntp connection into something useful, yeargh!"
        
        # Set up!
        def __init__(self, swrap, host, port, username, password, bindto):
                self.swrap = swrap
                self.host, self.port, self.username, self.password, self.bindto = [host, port, username, password, bindto]
                
                self.nntp = EvilNNTP(host=host, port=port, user=username, password=password, readermode=1, bindto=bindto)
                # Shortcut some stuff
                self.setblocking = self.nntp.sock.setblocking
                self.recv = self.nntp.sock.recv
                
                self.data = ''
                self.lines = []

        def reconnect(self):
                host, port, username, password, bindto = [self.host, self.port, self.username, self.password, self.bindto]
                self.nntp = EvilNNTP(host=host, port=port, user=username, password=password, readermode=1, bindto=bindto)
                # Shortcut some stuff
                self.setblocking = self.nntp.sock.setblocking
                self.recv = self.nntp.sock.recv
                
        # Send a useless command to avoid idle timeouts
        def anti_idle(self):
                command = 'MODE READER\r\n'
                self.nntp.sock.send(command)
        
        # Send a BODY command
        def body(self, article):
                command = 'BODY %s\r\n' % (article)
                self.nntp.sock.send(command)
        
        # Send a XOVER command
        def xover(self, start, finish):
                command = 'XOVER %s-%s\r\n' % (start, finish)
                self.nntp.sock.send(command)
        
        # recv() a chunk of data and split it into lines. Returns 0 if there's
        # probably some more data coming, and 1 if we got a dot line.
        def recv_chunk(self):
                attempts = 0
                while attempts < 5:
                        try:
                                chunk = self.recv(4096)
                        except:
                                atempts += 1
                                self.reconnect()
                        else:
                                break
                if attempts >= 5:
                        raise nntplib.NNTPPermanentError("Couldn't re-establish connection.")
                
                # Split the data into lines now
                self.data += chunk
                new_lines = self.data.split('\r\n')
                
                # Last line is leftover junk, keep it for later
                self.data = new_lines.pop()
                self.lines.extend(new_lines)
                
                # If we got a dot line, we're finished
                if self.lines and self.lines[-1] == '.':
                        # The first line is the response, and the last line is '.'
                        self.lines = self.lines[1:-1]
                        return (len(chunk), 1)
                # Or not
                else:
                        return (len(chunk), 0)
        
        def reset(self):
                self.data = ''
                self.lines = []
