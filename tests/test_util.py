#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import base64
import math
import os
import random

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


def random_string(length=16):
    bytes_needed = 3 * math.ceil(length / 4)
    data = os.urandom(bytes_needed)
    b64data = base64.b64encode(data)[:length]
    return b64data.decode('ASCII')


def random_message(subject=None, body=None, from_addr=None, to=None, **kwargs):
    if subject is None:
        subject = 'Sample subject ' + random_string()
    if body is None:
        lines = []
        for n in range(random.randint(1, 15)):
            line = 'Line %d: %s\n' % (n, random_string())
            lines.append(line)
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
