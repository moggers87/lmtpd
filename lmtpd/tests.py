# -*- coding: utf-8 -*-
#
# See LICENSE for copyright notices

from __future__ import print_function, unicode_literals

import asyncore
import lmtpd
import os
import shutil
import socket
import tempfile
import threading
import unittest

TO = b"mrs.smoker@example.com"
FROM = b"mrs.non-smoker@example.com"
MSG = b"""Subject: I keep falling off!

Oh! Well I never!
"""


class LMTPTestServer(lmtpd.LMTPServer):
    def process_message(*args, **kwargs):
        """Do nothing, server will return 250 OK"""
        pass


class LMTPTester(unittest.TestCase):
    """Test cases that connect to a server over a socket"""
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.socket_name = os.path.join(self.tempdir, "lmtp")
        self.server = LMTPTestServer(self.socket_name)
        self.loop = threading.Thread(target=asyncore.loop, kwargs={'timeout': 1})
        self.loop.start()

        # connect to server
        self.conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.conn.connect(self.socket_name)
        self.file = self.conn.makefile('rb')

    def tearDown(self):
        self.conn.close()
        self.file.close()
        self.server.close()
        self.loop.join()
        shutil.rmtree(self.tempdir)

    def reply(self):
        line = self.file.readline()

        if len(line) == 0:
            return (0, b'')

        try:
            code = int(line[:3])
            reply = line[4:]
        except (IndexError, ValueError):
            code = None
            reply = None

        return (code, reply)

    def do_cmd(self, cmd, flush=False):
        if flush:
            self.reply()

        self.conn.send(cmd)
        self.conn.send(b"\r\n")
        return self.reply()

    def test_conversation(self):
        """Test a basic conversation between client and server"""
        code, reply = self.reply()
        self.assertEqual(code, 220, reply)

        code, reply = self.do_cmd(b"LHLO localhost")
        self.assertEqual(code, 250, reply)
        code, reply = self.reply()
        self.assertEqual(code, 250)
        self.assertEqual(reply, b"ENHANCEDSTATUSCODES\r\n")
        code, reply = self.reply()
        self.assertEqual(reply, b"PIPELINING\r\n")
        self.assertEqual(code, 250)

        code, reply = self.do_cmd(b"MAIL FROM:<" + FROM + b">")
        self.assertEqual(code, 250, reply)

        code, reply = self.do_cmd(b"RCPT TO:<" + TO + b">")
        self.assertEqual(code, 250, reply)

        code, reply = self.do_cmd(b"DATA")
        self.assertEqual(code, 354, reply)

        self.conn.send(MSG)
        self.conn.send(b"\r\n.\r\n")
        code, reply = self.reply()
        self.assertEqual(code, 250, reply)

    def test_MAIL_RCPT_order(self):
        """Test that RCPT can't be used before MAIL"""
        code, reply = self.do_cmd(b"RCPT TO:<" + TO + b">", flush=True)

        self.assertNotEqual(code, 250)
        self.assertEqual(code, 503)

    def test_address(self):
        """Test accepting of addresses with and without <>"""
        code, reply = self.do_cmd(b"MAIL FROM:<" + FROM + b">", flush=True)
        self.assertEqual(code, 250, reply)

        self.do_cmd(b"RSET")

        code, reply = self.do_cmd(b"MAIL FROM:" + FROM)
        self.assertEqual(code, 250)

    def test_DATA_after(self):
        """Test DATA can't be used before MAIL and RCPT"""
        code, reply = self.do_cmd(b"DATA", flush=True)
        self.assertNotEqual(code, 354, b"DATA command accepted before MAIL")

        self.do_cmd(b"MAIL FROM:<" + FROM + b">")
        code, reply = self.do_cmd(b"DATA")
        self.assertNotEqual(code, 354, b"DATA command accepted before RCPT")

    def test_RSET(self):
        """Test resetting the state of the connection"""
        self.do_cmd(b"MAIL FROM:<" + FROM + b">", flush=True)
        code, reply = self.do_cmd(b"RSET")
        self.assertEqual(code, 250)

        code, reply = self.do_cmd(b"RCPT TO:<" + TO + b">")
        self.assertEqual(code, 503, reply)

    def test_not_implemented(self):
        """Test that unknown commands get rejected"""
        code, reply = self.do_cmd(b"HELO", flush=True)
        self.assertEqual(code, 502, reply)

    def test_pipeline(self):
        """Test command pipelining works"""
        self.reply()  # manaully flush message on connect

        self.conn.send(b"MAIL FROM:<" + FROM + b">\r\nRCPT TO:<" + TO + b">\r\nDATA\r\n")

        # MAIL FROM reply
        code, reply = self.reply()
        self.assertEqual(code, 250, reply)

        # RCPT TO reply
        code, reply = self.reply()
        self.assertEqual(code, 250, reply)

        # DATA reply
        code, reply = self.reply()
        self.assertEqual(code, 354, reply)
