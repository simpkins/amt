#!/usr/bin/python3 -tt
#
# Copyright (c) 2013, Adam Simpkins
#
import datetime
import time

from .parse import _MONTHS_BY_NUM


class Literal:
    def __init__(self, data):
        if not isinstance(data, (bytes, bytearray)):
            raise ImapError('literal data must be bytes')
        self.data = data

    def __str__(self):
        # throw, to catch the error if anyone ever accidentally
        # tries simple string conversion on a Literal object
        raise ImapError('attempted string conversion on a Literal')


def to_astring(value):
    # TODO: We could just return the value itself if it doesn't contain
    # any atom-specials.
    return to_string(value)


def to_string(value):
    if len(value) > 256:
        return to_literal(value)

    return to_quoted(value)


def to_literal(value):
    return Literal(value)


def to_quoted(value):
    escaped = value.replace(b'\\', b'\\\\').replace(b'"', b'\\"')
    return b'"' + escaped + b'"'


def to_date(timestamp):
    if not isinstance(timestamp, datetime.datetime):
        timestamp = datetime.datetime.fromtimestamp(timestamp)

    month_text = _MONTHS_BY_NUM[timestamp.month].decode('ASCII',
                                                        errors='strict')
    date_text = '%d-%s-%d' % (timestamp.day, month_text, timestamp.year)
    return date_text.encode('ASCII', errors='strict')


def to_date_time(timestamp):
    if not isinstance(timestamp, datetime.datetime):
        timestamp = datetime.datetime.fromtimestamp(timestamp)

    tz_offset = timestamp.utcoffset()
    if tz_offset is None:
        if time.daylight:
            tz_seconds = -int(time.altzone / 60)
        else:
            tz_seconds = -int(time.timezone / 60)
    else:
        tz_seconds = tz_offset.total_seconds()

    if tz_seconds < 0:
        tz_sign = '-'
        tz_seconds = -tz_seconds
    else:
        tz_sign = '+'
    tz_hour = int(tz_seconds / 60)
    tz_min = int(tz_seconds % 60)

    month = _MONTHS_BY_NUM[timestamp.month].decode('ASCII',
                                                   errors='strict')
    params = (timestamp.day, month, timestamp.year,
              timestamp.hour, timestamp.minute, timestamp.second,
              tz_sign, tz_hour, tz_min)
    s = '"%02d-%s-%04d %02d:%02d:%02d %s%02d%02d"' % params
    return s.encode('ASCII', errors='strict')

def format_sequence_set(msg_ids):
    if isinstance(msg_ids, (list, tuple)):
        return b','.join(_format_seq_range(r) for r in msg_ids)

    try:
        return _format_seq_range(msg_ids)
    except TypeError:
        raise TypeError('expected a numeric message ID, '
                        'a string message range, or list of message '
                        'IDs/ranges, got %s: %r' %
                        (type(value).__name__, value))

def _format_seq_range(value):
    if isinstance(value, int):
        return str(value).encode('ASCII', errors='strict')
    elif isinstance(value, str):
        return value.encode('ASCII', errors='strict')
    elif isinstance(value, (bytes, bytearray)):
        return value

    raise TypeError('expected a numeric message ID or a string '
                    'message range, got %s: %r' %
                    (type(value).__name__, value))


def collapse_seq_ranges(msg_ids):
    ranges = []
    start = None
    last = None
    for msg_id in sorted(msg_ids):
        if start is None:
            assert last is None
            start = msg_id
            last = msg_id
        elif msg_id == last:
            continue
        elif msg_id == last + 1:
            last = msg_id
        else:
            ranges.append('%d:%d' % (start, last))
            start = msg_id
            last = msg_id
    if last is not None:
        ranges.append('%d:%d' % (start, last))

    range_str = ','.join(ranges)
    return range_str.encode('ASCII', errors='strict')
