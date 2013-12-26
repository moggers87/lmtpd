import asyncore
import lmtpd
import os
import socket
from time import time
import threading
import unittest

SOCKET = "/tmp/lmtpd-socket-test" 

TO = "mrs.smoker@example.com"
FROM = "mrs.non-smoker@example.com"
MSG = """Subject: I keep falling off!

Oh! Well I never!
"""

class LMTPTestServer(lmtpd.LMTPServer):
    def process_message(*args, **kwargs):
        """Do nothing, server will return 250 OK"""
        pass

class LMTPTester(unittest.TestCase):
    """Test cases that connect to a server over a socket"""
    def setUp(self):
        self.socket_name = SOCKET + str(time())
        self.server = LMTPTestServer(self.socket_name)
        self.loop = threading.Thread(target=asyncore.loop, kwargs={'timeout':1})
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
        os.remove(self.socket_name)

    def reply(self):
        line = self.file.readline()

        if len(line) == 0:
            return (0, '')

        try:
            code = int(line[:3])
            reply = line[4:]
        except IndexError:
            code = None
            reply = None

        return (code, reply)

    def do_cmd(self, cmd, flush=False):
        if flush:
            self.reply()

        self.conn.send(cmd)
        self.conn.send("\r\n")
        return self.reply()

    def test_conversation(self):
        """Test a basic conversation between client and server"""
        code, reply = self.reply()
        self.assertEqual(code, 220, "Greeting was not 220")

        code, reply = self.do_cmd("LHLO localhost")
        self.assertEqual(code, 250, "LHLO command not OK")

        code, reply = self.do_cmd("MAIL FROM:<%s>" % FROM)
        self.assertEqual(code, 250, "MAIL command not OK")

        code, reply = self.do_cmd("RCPT TO:<%s>" % TO)
        self.assertEqual(code, 250, "RCPT command not OK")

        code, reply = self.do_cmd("DATA")
        self.assertEqual(code, 354, "DATA command not OK")

        self.conn.send(MSG)
        self.conn.send("\r\n.\r\n")
        code, reply = self.reply()
        self.assertEqual(code, 250, "Message not received OK")

    def test_MAIL_RCPT_order(self):
        """Test that RCPT can't be used before MAIL"""
        code, reply = self.do_cmd("RCPT TO:<%s>" % TO, flush=True)

        self.assertNotEqual(code, 250)
        self.assertEqual(code, 503)

    def test_address(self):
        """Test accepting of addresses with and without <>"""
        code, reply = self.do_cmd("MAIL FROM:<%s>" % FROM, flush=True)
        self.assertEqual(code, 250)

        self.do_cmd("RSET")

        code, reply = self.do_cmd("MAIL FROM:%s" % FROM)
        self.assertEqual(code, 250)

    def test_DATA_after(self):
        """Test DATA can't be used before MAIL and RCPT"""
        code, reply = self.do_cmd("DATA", flush=True)
        self.assertNotEqual(code, 354, "DATA command accepted before MAIL")

        self.do_cmd("MAIL FROM:<%s>" % FROM)
        code, reply = self.do_cmd("DATA")
        self.assertNotEqual(code, 354, "DATA command accepted before RCPT")

    def test_RSET(self):
        """Test resetting the state of the connection"""
        self.do_cmd("MAIL FROM:<%s>" % FROM, flush=True)
        code, reply = self.do_cmd("RSET")
        self.assertEqual(code, 250)

        code, reply = self.do_cmd("RCPT TO:<%s>" % TO)

        self.assertNotEqual(code, 250)
        self.assertEqual(code, 503)

    def test_not_implemented(self):
        """Test that unknown commands get rejected"""
        code, reply = self.do_cmd("HELO", flush=True)
        self.assertEqual(code, 502)
