#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import unittest

import amt.message


MSG1 = b'''\
MIME-Version: 1.0
Received: from mail.example.com [10.1.2.3]
 by mail2.example.com with IMAP (someclient-1.2.3)
 for <bob@example.com>; Tue, 01 May 2012 14:18:02 -0700 (PDT)
Received: from smtp.example.com ([10.1.2.4]) by
 smtp-hub.example.com ([10.1.2.5]) with mapi id 1.2.3.4; Tue,
 1 May 2012 14:18:00 -0700
From: Alice User <alice@example.com>
To: Bob User <bob@example.com>, =?UTF-8?B?Q2FybCBNYXJ0w61uZXo=?=
 <carl@example.com>, =?gb2312?B?0LvB7g==?= <xieling@example.com>
Subject: Test Mail
 with a folded subject
Date: Tue, 1 May 2012 14:17:58 -0700
Message-ID: <CBC59F9D.349C%alice@example.com>
In-Reply-To: <C4AF2C28692E4A4CAF08C94806187A58965CBB@smtp-hub.example.com>
Accept-Language: en-US
Content-Language: en-US
Content-Type: text/plain; charset="us-ascii"
Content-ID: <95CAF08DE7B65E458A6BDB69CA4B5825@example.com>
Content-Transfer-Encoding: quoted-printable


This is a test message.
Here are some contents
'''

MSG1_CRLF = MSG1.replace(b'\n', b'\r\n')

MSG2 = b'''\
Received: from mxout.example.com (unknown [1.2.3.5])	by
 mxin.example.com with ESMTP id 1ku07ucrxm-1;	Tue, 13 May 2014
 15:31:33 -0700
Received: from mx1.example.com (unknown [1.2.3.4])	by
 mx2.example.com (Postfix) with ESMTP id 0F03037EB6;	Wed, 14 May 2014
 06:35:37 +0800 (CST)
To: Bob Example <bob@example.com>
In-Reply-To: <801B8A53A0D64D4FA6409E97BA2C7E4458450700@ABC-MBX01-5.example.com>
Message-ID: <E9A0ABD4-8D8E-4CDD-83F8-3FA15B18AA93@example.com>
Subject: Sample Big5 Message
CC: Some User <user@example.com>
From: Alice Example <alice@example.com>
Date: Wed, 14 May 2014 06:31:30 +0800
X-Mailer: Lotus Notes Traveler 8.5.3.3 Build 201212060844
X-MIMETrack: =?Big5?B?U2VyaWFsaXplIGJ5IFJvdXRlciBvbiBBWElTL0FjY3RvbihSZWxlYXNl?=
 =?Big5?B?IDguNS4zRlA0fE1hcmNoIDI3LCAyMDEzKSBhdCAyMDE0LzA1LzE0IKRXpMggMDY6?=
 =?Big5?B?MzE6MzE=?=
Content-Type: text/html; charset="Big5"
Content-Disposition: inline
Content-Transfer-Encoding: base64
Return-Path: alice@example.com
MIME-Version: 1.0

PGh0bWw+DQp0ZXN0DQo8L2h0bWw+
'''


class Tests(unittest.TestCase):
    def test_parse(self):
        msg1 = amt.message.Message.from_bytes(MSG1)
        self.assertEqual(msg1.subject, 'Test Mail with a folded subject')
        self.assertEqual(len(msg1.from_addr), 1)
        self.assertEqual(msg1.from_addr[0].display_name, 'Alice User')
        self.assertEqual(len(msg1.to), 3)
        self.assertEqual(msg1.to[0].display_name, 'Bob User')
        self.assertEqual(msg1.to[0].addr_spec, 'bob@example.com')
        self.assertEqual(msg1.to[1].display_name, 'Carl Mart\u00ednez')
        self.assertEqual(msg1.to[1].addr_spec, 'carl@example.com')
        self.assertEqual(msg1.to[2].display_name, '\u8c22\u4ee4')
        self.assertEqual(msg1.to[2].addr_spec, 'xieling@example.com')

    def test_serialize(self):
        msg1 = amt.message.Message.from_bytes(MSG1)
        out = msg1.to_bytes()
        self.assertEqual(MSG1, out)

        msg2 = amt.message.Message.from_bytes(MSG2)
        out = msg2.to_bytes()
        self.assertEqual(MSG2, out)
