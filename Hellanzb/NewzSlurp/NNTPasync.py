import asyncore, nntplib, socket


class nntp_client(asyncore.dispatcher,nntplib.NNTP):
    def __init__(self, host, port=nntplib.NNTP_PORT, user=None, password=None,
                 readermode=None, bindto=None):
        asyncore.dispatcher.__init__(self)
        self.host, self.port, self.user, self.password  = [host, port, user, password]
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connect((self.host,self.port))
        self.setblocking(0)

#        self.file = self.makefile('rb')
        
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

    def handle_connect(self):
        pass
