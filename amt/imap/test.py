#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import unittest
import os
import sys

amt_root = os.path.dirname(os.path.dirname(sys.path[0]))
sys.path.insert(0, amt_root)

from amt import imap


class CmdCallback:
    def __init__(self, test):
        self.commands = []
        self.test = test

    def on_cmd(self, cmd):
        self.commands.append(cmd)

    def pop_cmd(self):
        self.test.assertTrue(self.commands)
        return self.commands.pop(0)

    def assert_cmd(self, expected):
        self.test.assertTrue(self.commands)
        actual = self.commands.pop(0)
        self.test.assertEqual(actual, expected)

    def assert_no_cmd(self):
        self.test.assertFalse(self.commands)


class CommandSplitterTests(unittest.TestCase):
    def setUp(self):
        self.callback = CmdCallback(self)
        self.splitter = imap.CommandSplitter(self.callback.on_cmd)

    def feed_byte_at_once(self, data):
        for char_value in data:
            char = bytearray(1)
            char[0] = char_value
            self.splitter.feed(char)

    def test_simple_cmd(self):
        cmd = b'A001 OK foo bar'
        self.splitter.feed(cmd + b'\r\n')
        self.callback.assert_cmd([cmd])

    def test_simple_cmd_byte_at_once(self):
        cmd = b'A001 OK foo bar'
        self.feed_byte_at_once(cmd)
        self.splitter.feed(b'\r')
        self.callback.assert_no_cmd()
        self.splitter.feed(b'\n')
        self.callback.assert_cmd([cmd])

    def test_literal_byte_at_once(self):
        cmd = b'* FETCH this is not really valid{12}\r\nabcdefghijklend\r'
        self.feed_byte_at_once(cmd)
        self.callback.assert_no_cmd()
        self.splitter.feed(b'\n')

        expected = [
            b'* FETCH this is not really valid',
            b'abcdefghijkl',
            b'end',
        ]
        self.callback.assert_cmd(expected)

    def test_multiple_cmds(self):
        data = b'A001 OK foo bar\r\n* EXISTS 5\r\n* FETCH whatever{10'
        self.splitter.feed(data)
        self.callback.assert_cmd([b'A001 OK foo bar'])
        self.callback.assert_cmd([b'* EXISTS 5'])
        self.callback.assert_no_cmd()

        data = (b'}\r\n0123456789yet more{5}\r\nabcde\r\n'
                b'A002 BAD some failure\r\n')
        self.splitter.feed(data)
        self.callback.assert_cmd([
            b'* FETCH whatever',
            b'0123456789',
            b'yet more',
            b'abcde',
            b'',
        ])
        self.callback.assert_cmd([b'A002 BAD some failure'])
        self.callback.assert_no_cmd()

        self.splitter.feed(b'A003 OK success\r\n')
        self.callback.assert_cmd([b'A003 OK success'])
        self.callback.assert_no_cmd()


class ResponseStreamTests(unittest.TestCase):
    def setUp(self):
        self.callback = CmdCallback(self)
        self.stream = imap.ResponseStream(self.callback.on_cmd)

    def pop_cmd(self):
        return self.callback.pop_cmd()

    def test_continuation_cmd(self):
        self.stream.feed(b'+ some stuff here\r\n')
        cmd = self.pop_cmd()
        self.assertIsInstance(cmd, imap.ContinuationResponse)
        self.assertEqual(cmd.tag, b'+')
        self.assertEqual(cmd.resp_type, None)
        self.assertEqual(cmd.resp_text, b'some stuff here')

    def test_state_cmd(self):
        self.stream.feed(b'A001 OK foo bar\r\n')
        cmd = self.pop_cmd()
        self.assertIsInstance(cmd, imap.StateResponse)
        self.assertEqual(cmd.tag, b'A001')
        self.assertEqual(cmd.resp_type, b'OK')
        self.assertEqual(cmd.resp_text, b'foo bar')

    def test_capability_cmd(self):
        self.stream.feed(b'* CAPABILITY AUTH=PLAIN IMAP4 IMAP4rev1 '
                         b'FOO BAR\r\n')
        cmd = self.pop_cmd()
        self.assertIsInstance(cmd, imap.CapabilityResponse)
        self.assertEqual(cmd.tag, b'*')
        self.assertEqual(cmd.resp_type, b'CAPABILITY')
        expected_caps = [
            b'AUTH=PLAIN',
            b'IMAP4',
            b'IMAP4rev1',
            b'FOO',
            b'BAR',
        ]
        self.assertEqual(cmd.capabilities, expected_caps)

    def test_unknown_cmd(self):
        self.stream.feed(b'* FOOBAR asdf\r\n')
        cmd = self.pop_cmd()
        self.assertIsInstance(cmd, imap.UnknownResponse)
        self.assertEqual(cmd.tag, b'*')
        self.assertEqual(cmd.resp_type, b'FOOBAR')
        self.assertEqual(cmd.cmd_parts, [b'* FOOBAR asdf'])


if __name__ == '__main__':
    unittest.main()
