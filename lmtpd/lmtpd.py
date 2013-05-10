
#
# Parts of this module are taken from Python 2.7.3 Lib/smtpd.py
# Copyright © 2001-2012 Python Software Foundation; All Rights Reserved
# See the file PY-LIC for more details
#

from smtpd import SMTPChannel, SMTPServer, DEBUGSTREAM
from types import StringType
import socket

class LMTPChannel(SMTPChannel):
    pass

class LMTPServer(SMTPServer):
    def __init__(self, localaddr):
        if type(localaddr) == StringType:
            inet_or_unix = socket.AF_UNIX
        else:
            inet_or_unix = socket.AF_INET

        self._localaddr = localaddr
        asyncore.dispatcher.__init__(self)
        try:
            self.create_socket(inet_or_unix, socket.SOCK_STREAM)
            # try to re-use a server port if possible
            self.set_reuse_addr()
            self.bind(localaddr)
            self.listen(5)
        except:
            # cleanup asyncore.socket_map before raising
            self.close()
            raise
        else:
            print >> DEBUGSTREAM, \
                  '%s started at %s\n\tLocal addr: %s' % (
                self.__class__.__name__, time.ctime(time.time()),
                localaddr)

    def handle_accept(self):
        pair = self.accept()
        if pair is not None:
            conn, addr = pair
            print >> DEBUGSTREAM, 'Incoming connection from %s' % repr(addr)
            channel = LMTPChannel(self, conn, addr)

class DebuggingServer(LMTPServer):
    # Do something with the gathered message
    def process_message(self, peer, mailfrom, rcpttos, data):
        inheaders = 1
        lines = data.split('\n')
        print '---------- MESSAGE FOLLOWS ----------'
        for line in lines:
            # headers first
            if inheaders and not line:
                print 'X-Peer:', peer[0]
                inheaders = 0
            print line
        print '------------ END MESSAGE ------------'
