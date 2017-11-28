# -*- coding: utf-8 -*-
#
# Parts of this module are taken from Python 2.7.3 Lib/smtpd.py
# Copyright © 2001-2012 Python Software Foundation; All Rights Reserved
# See the file PY-LIC for more details
#
# See LICENSE for additional copyright notices

from __future__ import print_function, unicode_literals
from smtpd import SMTPServer, DEBUGSTREAM

import asyncore
import asynchat
import socket
import time
import errno

__version__ = 'Python LMTP server version 6.0.0'


class LMTPChannel(asynchat.async_chat):
    COMMAND = 0
    DATA = 1

    def __init__(self, server, conn, addr):
        asynchat.async_chat.__init__(self, conn)
        self.__server = server
        self.__conn = conn
        self.__addr = addr
        self.__line = []
        self.__state = self.COMMAND
        self.__greeting = 0
        self.__mailfrom = None
        self.__rcpttos = []
        self.__data = b''
        self.__fqdn = socket.getfqdn()

        try:
            self.__peer = conn.getpeername()
        except socket.error as err:
            self.close()
            if err[0] != errno.ENOTCONN:
                raise
            return
        print(b"Peer:", repr(self.__peer), file=DEBUGSTREAM)

        # can't format bytes in Py 3.3
        self.push(b' '.join([b'220', self.__fqdn.encode(), __version__.encode()]))
        self.set_terminator(b'\r\n')

    def push(self, msg):
        asynchat.async_chat.push(self, msg + b'\r\n')

    def collect_incoming_data(self, data):
        self.__line.append(data)

    def found_terminator(self):
        line = b"".join(self.__line)
        print(b"Data:", repr(line), file=DEBUGSTREAM)
        self.__line = []
        if self.__state == self.COMMAND:
            if not line:
                self.push(b'500 5.5.2 Error: bad syntax')
                return
            method = None
            i = line.find(b' ')
            if i < 0:
                command = line.upper()
                arg = None
            else:
                command = line[:i].upper()
                arg = line[i+1:].strip()
            method = getattr(self, 'lmtp_' + command.decode(), None)
            if not method:
                self.push(b''.join([b'502 5.5.2 Error: command "', command, b'" not implemented']))
                return
            method(arg)
            return
        else:
            if self.__state != self.DATA:
                self.push(b'451 4.5.1 Internal confusion')
                return
            # replace CRLF with LF
            data = []
            for text in line.split(b'\r\n'):
                if text and text[0] == b'.':
                    data.append(text[1:])
                else:
                    data.append(text)
            self.__data = b"\n".join(data)
            # process each RCPT TO separately
            for rcptto in self.__rcpttos:
                status = self.__server.process_message(self.__peer,
                                                       self.__mailfrom,
                                                       rcptto,
                                                       self.__data)
                if not status:
                    self.push(b'250 2.0.0 Ok')
                else:
                    self.push(status)

            self.__rcpttos = []
            self.__mailfrom = None
            self.__state = self.COMMAND
            self.set_terminator(b'\r\n')

    # LMTP commands
    def lmtp_LHLO(self, arg):
        if not arg:
            self.push(b'501 5.5.4 Syntax: LHLO hostname')
        elif self.__greeting:
            self.push(b'503 5.5.1 Duplicate LHLO')
        else:
            self.__greeting = arg
            # only the last line has a space between the state code and
            # parameter, this is so the client knows we're finished
            self.push(b'250-' + self.__fqdn.encode())
            self.push(b'250-ENHANCEDSTATUSCODES')
            self.push(b'250 PIPELINING')

    def lmtp_NOOP(self, arg):
        if arg:
            self.push(b'501 5.5.4 Syntax: NOOP')
        else:
            self.push(b'250 2.0.0 Ok')

    def lmtp_QUIT(self, arg):
        self.push(b'221 2.0.0 Bye')
        self.close_when_done()

    def __getaddr(self, keyword, arg):
        address = None
        keylen = len(keyword)
        if arg[:keylen].upper() == keyword:
            address = arg[keylen:].strip()
            if not address:
                pass
            elif address[0] == b'<' and address[-1] == b'>' and address != b'<>':
                # Addresses can be in the form <person@dom.com> but watch out
                # for null address, e.g. <>
                address = address[1:-1]
        return address

    def lmtp_MAIL(self, arg):
        print(b'===> MAIL', arg, file=DEBUGSTREAM)
        address = self.__getaddr(b'FROM:', arg) if arg else None
        if not address:
            self.push(b'501 5.5.4 Syntax: MAIL FROM:<address>')
            return
        if self.__mailfrom:
            self.push(b'503 5.5.1 Error: nested MAIL command')
            return
        self.__mailfrom = address
        print(b'sender:', self.__mailfrom, file=DEBUGSTREAM)
        self.push(b'250 2.1.0 Ok')

    def lmtp_RCPT(self, arg):
        print(b'===> RCPT', arg, file=DEBUGSTREAM)
        if not self.__mailfrom:
            self.push(b'503 5.5.1 Error: need MAIL command')
            return
        address = self.__getaddr(b'TO:', arg) if arg else None
        if not address:
            self.push(b'501 5.5.4 Syntax: RCPT TO: <address>')
            return
        self.__rcpttos.append(address)
        print(b'recips:', self.__rcpttos, file=DEBUGSTREAM)
        self.push(b'250 2.1.0 Ok')

    def lmtp_RSET(self, arg):
        if arg:
            self.push(b'501 5.5.4 Syntax: RSET')
            return
        # Resets the sender, recipients, and data, but not the greeting
        self.__mailfrom = None
        self.__rcpttos = []
        self.__data = b''
        self.__state = self.COMMAND
        self.push(b'250 2.0.0 Ok')

    def lmtp_DATA(self, arg):
        if not self.__rcpttos:
            self.push(b'503 5.5.1 Error: need RCPT command')
            return
        if arg:
            self.push(b'501 5.5.4 Syntax: DATA')
            return
        self.__state = self.DATA
        self.set_terminator(b'\r\n.\r\n')
        self.push(b'354 End data with <CR><LF>.<CR><LF>')


class LMTPServer(SMTPServer):
    """Exactly the same interface as smtpd.SMTPServer, override `process_message` to use"""
    def __init__(self, localaddr):
        if type(localaddr) in (type(u""), type(b"")):
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
            print(u'{0} started at {1}\n\tLocal addr: {2}'.format(
                self.__class__.__name__, time.ctime(time.time()),
                localaddr), file=DEBUGSTREAM)

    def handle_accept(self):
        pair = self.accept()
        if pair is not None:
            conn, addr = pair
            print(b'Incoming connection from', repr(addr), file=DEBUGSTREAM)
            channel = LMTPChannel(self, conn, addr)


class DebuggingServer(LMTPServer):
    # Do something with the gathered message
    def process_message(self, peer, mailfrom, rcpttos, data):
        inheaders = 1
        lines = data.split(b'\n')
        print(u'---------- MESSAGE FOLLOWS ----------')
        for line in lines:
            # headers first
            if inheaders and not line:
                print(u'X-Peer:', repr(peer))
                inheaders = 0
            print(line)
        print(u'------------ END MESSAGE ------------')
