import asyncore, nntplib, socket


class nntp_client(asyncore.dispatcher,nntplib.NNTP):
    def __init__(self, host, port=nntplib.NNTP_PORT, user=None, password=None,
                 readermode=None, bindto=None):
        asyncore.dispatcher.__init__(self)
        nntplib.NNTP.__init__(self,host=host,port=port,user=user,password=password,readermode=readermode)
