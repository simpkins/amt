#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import base64
import math
import os
import random
import tempfile
import time
import unittest

from amt.maildb import MailDB
import amt.message


SAMPLE_ADDRESSES = [
    ('Alice', 'alice@example.com'),
    ('Bob', 'bob@example.com'),
    ('Carl', 'carl@example.com'),
    ('David', 'david@example.com'),
    ('Eugene', 'eugene@example.com'),
    ('Frank', 'frank@example.com'),
    ('Harry', 'harry@example.com'),
]


class MailDBTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = None
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.dbdir = os.path.join(cls.tmpdir.name, 'maildb')
        cls.db = MailDB.create_db(cls.dbdir)

    @classmethod
    def tearDownClass(cls):
        if cls.tmpdir is not None:
            cls.tmpdir.cleanup()

    def random_string(self, length=16):
        bytes_needed = 3 * math.ceil(length / 4)
        data = os.urandom(bytes_needed)
        b64data = base64.b64encode(data)[:length]
        return b64data.decode('ASCII')

    def new_message(self, subject=None, body=None, from_addr=None, to=None,
                    **kwargs):
        if subject is None:
            subject = 'Sample subject ' + self.random_string()
        if body is None:
            lines = []
            for n in range(random.randint(1, 15)):
                line = 'Line %d: %s\n' % (n, self.random_string())
            body = ''.join(lines)
        if from_addr is None:
            from_addr = random.choice(SAMPLE_ADDRESSES)
        if to is None:
            to = []
            for n in range(random.randint(1, 5)):
                addr = random.choice(SAMPLE_ADDRESSES)
                to.append(addr)

        return amt.message.new_message(subject=subject, body=body,
                                       from_addr=from_addr, to=to,
                                       **kwargs)


class MailDBTests(MailDBTestCase):
    def test_get_muid_dup(self):
        params = {
            'subject': 'test_get_muid_dup()',
            'body': 'This is a test.\n',
            'from_addr': [('Alice', 'alice@example.com')],
            'to': [('Bob', 'bob@example.com'), ('Carl', 'carl@example.com')],
            'timestamp': time.time(),
            'message_id': '<msg1234@example.com>',
        }
        msg1 = amt.message.new_message(**params)
        msg2 = amt.message.new_message(**params)
        msg3 = amt.message.new_message(**params)
        msg4 = amt.message.new_message(**params)
        msg5 = amt.message.new_message(**params)

        muid = self.db.get_muid(msg1, update_header=True, commit=False)
        self.assertEqual(msg1.get('X-AMT-MUID'), muid.value)

        muid2 = self.db.get_muid(msg2, update_header=False, dup_check=True,
                                 commit=False)
        self.assertEqual(msg2.get('X-AMT-MUID'), None)
        self.assertEqual(muid, muid2)

        muid3 = self.db.get_muid(msg3, update_header=True, dup_check=False,
                                 commit=False)
        self.assertEqual(msg3.get('X-AMT-MUID'), muid3.value)
        self.assertNotEqual(muid, muid3)

        muid4 = self.db.get_muid(msg4, update_header=True, dup_check=True,
                                 commit=False)
        self.assertEqual(msg4.get('X-AMT-MUID'), muid4.value)
        # muid4 should match either muid or muid3
        if muid4 != muid:
            self.assertEqual(muid4, muid3)

        # Change the Message-ID in msg5.
        # The dup_check code should treat it as a different message
        msg5.remove_header('Message-ID')
        msg5.add_header('Message-ID', '<another_id@example.com>')
        muid5 = self.db.get_muid(msg5, update_header=True, dup_check=True,
                                 commit=False)
        self.assertEqual(msg5.get('X-AMT-MUID'), muid5.value)
        self.assertNotEqual(muid5, muid)
        self.assertNotEqual(muid5, muid3)

    def test_get_muid_dup_no_message_id(self):
        params = {
            'subject': 'test_get_muid_dup_no_message_id()',
            'body': 'This is a test.\n',
            'from_addr': [('Alice', 'alice@example.com')],
            'to': [('Bob', 'bob@example.com'), ('Carl', 'carl@example.com')],
            'timestamp': time.time(),
        }
        msg1 = amt.message.new_message(**params)
        msg2 = amt.message.new_message(**params)
        msg3 = amt.message.new_message(**params)
        msg4 = amt.message.new_message(**params)

        # Delete the Message-ID headers
        for m in (msg1, msg2, msg3, msg4):
            m.remove_header('Message-ID')

        muid = self.db.get_muid(msg1, update_header=True, commit=False)
        self.assertEqual(msg1.get('X-AMT-MUID'), muid.value)

        muid2 = self.db.get_muid(msg2, update_header=False, dup_check=True,
                                 commit=False)
        self.assertEqual(msg2.get('X-AMT-MUID'), None)
        self.assertEqual(muid, muid2)

        muid3 = self.db.get_muid(msg3, update_header=True, dup_check=False,
                                 commit=False)
        self.assertEqual(msg3.get('X-AMT-MUID'), muid3.value)
        self.assertNotEqual(muid, muid3)

        muid4 = self.db.get_muid(msg4, update_header=True, dup_check=True,
                                 commit=False)
        self.assertEqual(msg4.get('X-AMT-MUID'), muid4.value)
        # muid4 should match either muid or muid3
        if muid4 != muid:
            self.assertEqual(muid4, muid3)

    def test_labels(self):
        msg = self.new_message()
        muid = self.db.get_muid(msg, commit=False)

        labels = self.db.get_labels(muid)
        self.assertEqual(labels, [])

        expected = set()
        self.db.add_label(muid, 'test_label', commit=False)
        expected.add('test_label')
        self.assertEqual(set(self.db.get_labels(muid)), expected)

        self.db.add_label(muid, 'auto_label', automatic=True, commit=False)
        expected.add('auto_label')
        self.assertEqual(set(self.db.get_labels(muid)), expected)

        self.db.add_labels(muid, ['foo', 'bar', ('auto2', True)], commit=False)
        expected.update(['foo', 'bar', 'auto2'])
        self.assertEqual(set(self.db.get_labels(muid)), expected)

        expected_details = set([
            ('test_label', False), ('auto_label', True),
            ('foo', False), ('bar', False), ('auto2', True),
        ])
        self.assertEqual(set(self.db.get_label_details(muid)),
                         expected_details)

    def test_get_tuid(self):
        msg1 = self.new_message()

        muid1 = self.db.get_muid(msg1, commit=False)
        tuid1 = self.db.get_tuid(muid1, msg1, commit=False)
        self.assertEqual(set(self.db.get_thread_msgs(tuid1)),
                         set([muid1]))

        msg2 = self.new_message()
        muid2 = self.db.get_muid(msg2, commit=False)
        tuid2 = self.db.get_tuid(muid2, msg2, commit=False)
        self.assertNotEqual(tuid1, tuid2)
        self.assertEqual(set(self.db.get_thread_msgs(tuid2)),
                         set([muid2]))

        # msg1_1 references msg_1, but has a different subject
        msg1_1 = self.new_message()
        msg1_1.add_header('References', msg1.get_message_id())
        muid1_1 = self.db.get_muid(msg1_1, commit=False)
        tuid1_1 = self.db.get_tuid(muid1_1, msg1_1, commit=False)
        self.assertEqual(tuid1_1, tuid1)
        self.assertEqual(set(self.db.get_thread_msgs(tuid1)),
                         set([muid1, muid1_1]))
