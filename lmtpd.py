# -*- coding: utf-8 -*-
#
# Parts of this module are taken from Python 2.7.3 Lib/smtpd.py
# Copyright © 2001-2012 Python Software Foundation; All Rights Reserved
# See the file PY-LIC for more details
#

from __future__ import print_function
from smtpd import SMTPServer, DEBUGSTREAM, NEWLINE, EMPTYSTRING

import asyncore
import asynchat
import socket
import time
import errno

__version__ = 'Python LMTP server version 4'

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
        self.__data = ''
        self.__fqdn = socket.getfqdn()

        try:
            self.__peer = conn.getpeername()
        except socket.error as err:
            self.close()
            if err[0] != errno.ENOTCONN:
                raise
            return
        print("Peer:", repr(self.__peer), file=DEBUGSTREAM)
        self.push('220 %s %s' % (self.__fqdn, __version__))
        self.set_terminator('\r\n')

    def push(self, msg):
        asynchat.async_chat.push(self, msg + '\r\n')

    def collect_incoming_data(self, data):
        self.__line.append(data)

    def found_terminator(self):
        line = EMPTYSTRING.join(self.__line)
        print("Data:", repr(line), file=DEBUGSTREAM)
        self.__line = []
        if self.__state == self.COMMAND:
            if not line:
                self.push('500 Error: bad syntax')
                return
            method = None
            i = line.find(' ')
            if i < 0:
                command = line.upper()
                arg = None
            else:
                command = line[:i].upper()
                arg = line[i+1:].strip()
            method = getattr(self, 'lmtp_' + command, None)
            if not method:
                self.push('502 Error: command "%s" not implemented' % command)
                return
            method(arg)
            return
        else:
            if self.__state != self.DATA:
                self.push('451 Internal confusion')
                return
            # copied from smtpd.py without understanding what it does
            data = []
            for text in line.split('\r\n'):
                if text and text[0] == '.':
                    data.append(text[1:])
                else:
                    data.append(text)
            self.__data = NEWLINE.join(data)
            # process each RCPT TO separately
            for rcptto in self.__rcpttos:
                status = self.__server.process_message(self.__peer,
                                                       self.__mailfrom,
                                                       rcptto,
                                                       self.__data)
                if not status:
                    self.push('250 Ok')
                else:
                    self.push(status)

            self.__rcpttos = []
            self.__mailfrom = None
            self.__state = self.COMMAND
            self.set_terminator('\r\n')

    # LMTP commands
    def lmtp_LHLO(self, arg):
        if not arg:
            self.push('501 Syntax: LHLO hostname')
        elif self.__greeting:
            self.push('503 Duplicate LHLO')
        else:
            self.__greeting = arg
            self.push('250 %s' % self.__fqdn)

    def lmtp_NOOP(self, arg):
        if arg:
            self.push('501 Syntax: NOOP')
        else:
            self.push('250 Ok')

    def lmtp_QUIT(self, arg):
        self.push('221 Bye')
        self.close_when_done()

    def __getaddr(self, keyword, arg):
        address = None
        keylen = len(keyword)
        if arg[:keylen].upper() == keyword:
            address = arg[keylen:].strip()
            if not address:
                pass
            elif address[0] == '<' and address[-1] == '>' and address != '<>':
                # Addresses can be in the form <person@dom.com> but watch out
                # for null address, e.g. <>
                address = address[1:-1]
        return address

    def lmtp_MAIL(self, arg):
        print('===> MAIL', arg, file=DEBUGSTREAM)
        address = self.__getaddr('FROM:', arg) if arg else None
        if not address:
            self.push('501 Syntax: MAIL FROM:<address>')
            return
        if self.__mailfrom:
            self.push('503 Error: nested MAIL command')
            return
        self.__mailfrom = address
        print('sender:', self.__mailfrom, file=DEBUGSTREAM)
        self.push('250 Ok')

    def lmtp_RCPT(self, arg):
        print('===> RCPT', arg, file=DEBUGSTREAM)
        if not self.__mailfrom:
            self.push('503 Error: need MAIL command')
            return
        address = self.__getaddr('TO:', arg) if arg else None
        if not address:
            self.push('501 Syntax: RCPT TO: <address>')
            return
        self.__rcpttos.append(address)
        print('recips:', self.__rcpttos, file=DEBUGSTREAM)
        self.push('250 Ok')

    def lmtp_RSET(self, arg):
        if arg:
            self.push('501 Syntax: RSET')
            return
        # Resets the sender, recipients, and data, but not the greeting
        self.__mailfrom = None
        self.__rcpttos = []
        self.__data = ''
        self.__state = self.COMMAND
        self.push('250 Ok')

    def lmtp_DATA(self, arg):
        if not self.__rcpttos:
            self.push('503 Error: need RCPT command')
            return
        if arg:
            self.push('501 Syntax: DATA')
            return
        self.__state = self.DATA
        self.set_terminator('\r\n.\r\n')
        self.push('354 End data with <CR><LF>.<CR><LF>')

class LMTPServer(SMTPServer):
    """Exactly the same interface as smtpd.SMTPServer, override `process_message` to use"""
    def __init__(self, localaddr):
        if type(localaddr) == str:
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
            print('{0} started at {1}\n\tLocal addr: {2}'.format(
                self.__class__.__name__, time.ctime(time.time()),
                localaddr), file=DEBUGSTREAM)

    def handle_accept(self):
        pair = self.accept()
        if pair is not None:
            conn, addr = pair
            print('Incoming connection from', repr(addr), file=DEBUGSTREAM)
            channel = LMTPChannel(self, conn, addr)

class DebuggingServer(LMTPServer):
    # Do something with the gathered message
    def process_message(self, peer, mailfrom, rcpttos, data):
        inheaders = 1
        lines = data.split('\n')
        print('---------- MESSAGE FOLLOWS ----------')
        for line in lines:
            # headers first
            if inheaders and not line:
                print('X-Peer:', repr(peer))
                inheaders = 0
            print(line)
        print('------------ END MESSAGE ------------')
