#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import datetime
import imaplib
import logging
import re

import ssl_util


class ImapError(Exception):
    pass


class Connection:
    def __init__(self, server, port=None):
        if port is None:
            port = imaplib.IMAP4_SSL_PORT

        ctx = ssl_util.new_ctx()
        self.conn = imaplib.IMAP4_SSL(host=server, port=port,
                                      ssl_context=ctx)
        self.conn.sock.settimeout(60)
        logging.debug('Server capabilities: %s', self.conn.capabilities)

    def login(self, user, password):
        self.conn.login(user=user, password=password)

    def select_mailbox(self, mailbox, readonly=False):
        self.conn.select(mailbox, readonly=readonly)

    def search_msg_ids(self, *criteria):
        typ, data = self.conn.uid('SEARCH', *criteria)
        _check_resp(typ, data, 'SEARCH')

        assert isinstance(data, (tuple, list))
        assert len(data) == 1

        # Split the response on spaces, and covert the IDs to integers
        msg_ids = [int(str_id) for str_id in data[0].split()]
        return msg_ids

    def fetch(self, msg_ids, parts, use_uid=True):
        '''
        Send a FETCH command to fetch the specified messages.

        msg_ids must be a list of integer IDs.
        '''
        parts_arg = '(' + ' '.join(parts) + ')'
        ids_arg = self._create_sequence_set(msg_ids)

        if use_uid:
            typ, data = self.conn.uid('FETCH', ids_arg, parts_arg)
        else:
            typ, data = self.conn.fetch(ids_arg, parts_arg)

        _check_resp(typ, data, 'FETCH')

        msgs = _parse_fetch_response(data)
        assert len(msgs) == len(msg_ids)
        return msgs

    def fetch_one(self, msg_id, parts, use_uid=True):
        msgs = self.fetch([msg_id], parts, use_uid=use_uid)
        assert len(msgs) == 1

        resp_id, msg = next(iter(msgs.items()))
        return msg

    def copy(self, msg_id, mailbox, use_uid=True):
        '''
        Copy message(s) from the selected mailbox to the mailbox with the
        specified name.
        '''
        ids_arg = self._create_sequence_set(msg_id, allow_one=True)

        if use_uid:
            typ, data = self.conn.uid('COPY', ids_arg, mailbox)
        else:
            typ, data = self.conn.fetch(ids_arg, mailbox)

        _check_resp(typ, data, 'COPY')

    def _create_sequence_set(self, msg_ids, allow_one=False):
        if allow_one and isinstance(msg_ids, int):
            return str(msg_ids).encode('ASCII')
        return b','.join(str(i).encode('ASCII') for i in msg_ids)


def _check_resp(typ, data, cmd):
    if typ != 'OK':
        raise ImapError('unexpected response from %s: (%r, %r)' %
                        (cmd, typ, data))


def _parse_fetch_response(data):
    responses = _reassemble_fetch_resp(data)
    resp_dict = {}
    for resp in responses:
        parser = _FetchParser(resp)
        msg_seq, attributes = parser.parse()
        resp_dict[msg_seq] = attributes

    return resp_dict


def _reassemble_fetch_resp(data):
    # imaplib parses responses a little strangely.
    # Reassemble the parts back into responses
    responses = []

    i = iter(data)
    while True:
        try:
            part = next(i)
        except StopIteration:
            # All done, no more responses
            break

        cur_resp = []
        while isinstance(part, tuple):
            # A partial response, followed by a string literal
            # The remainder of the response is in the next element of data
            assert len(part) == 2
            assert isinstance(part[0], bytes)
            assert isinstance(part[1], bytes)

            cur_resp.append(part[0])
            cur_resp.append(part[1])
            try:
                part = next(i)
            except StopIteration:
                raise Exception('missing response remainder after '
                                'string literal')

        if not isinstance(part, bytes):
            raise Exception('expected final response part to be bytes, '
                            'found %s'% type(part))
        cur_resp.append(part)
        responses.append(cur_resp)

    return responses


class _FetchParser:
    _NUMBER_RE = re.compile(b'([0-9]+)')
    _MSG_ATT_NAME_RE = re.compile(b'([^ ]+) ')
    _FLAGS_RE = re.compile(b'\\(([^)]*)\\)')
    _LITERAL_RE = re.compile(b'\\{([0-9]+)\\}')
    _QUOTED_STRING_PART_RE = re.compile(b'([^"\\\r\n"]*)')
    _DATE_TIME_RE = re.compile(
            b'"'
            b'(?P<day>[ 0-9][0-9])-'
            b'(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-'
            b'(?P<year>[0-9]{4}) '
            b'(?P<hours>[0-9][0-9]):'
            b'(?P<minutes>[0-9][0-9]):'
            b'(?P<seconds>[0-9][0-9]) '
            b'(?P<zone>[-+][0-9]{4})'
            b'"')

    _MONTH_MAP = {
        b'Jan': 1,
        b'Feb': 2,
        b'Mar': 3,
        b'Apr': 4,
        b'May': 5,
        b'Jun': 6,
        b'Jul': 7,
        b'Aug': 8,
        b'Sep': 9,
        b'Oct': 10,
        b'Nov': 11,
        b'Dec': 12,
    }

    def __init__(self, response):
        self.response = response
        self.it = iter(self.response)
        self.cur_part = None
        self.offset = 0

        self.msg_seq = None
        self.attributes = {}

    def parse(self):
        assert self.cur_part is None
        assert self.offset == 0

        try:
            self.cur_part = next(self.it)
        except StopIteration:
            raise Exception('empty FETCH response')

        self.msg_seq = self._parse_nznumber()
        if not self.cur_part[self.offset:].startswith(b' ('):
            raise Exception('expected message ID followed by " (", '
                            'got %r' % (self.cur_part,))
        self.offset += 2

        first = True
        while True:
            if self.cur_part[self.offset] == ord(b')'):
                self.offset += 1
                assert self.offset == len(self.cur_part)
                try:
                    next(self.it)
                    raise Exception('found end of message attributes '
                                    'before end of FETCH response')
                except StopIteration:
                    pass
                return self.msg_seq, self.attributes

            if first:
                first = False
            else:
                if self.cur_part[self.offset] != ord(b' '):
                    raise Exception('expected SP between message attributes, '
                                    'found %r' %
                                    (self.cur_part[self.offset:],))
                self.offset += 1
            attr_name, attr_value = self._parse_attribute()
            self.attributes[attr_name] = attr_value

    def _parse_attribute(self):
        m = self._parse_re(self._MSG_ATT_NAME_RE)
        attr_name = m.group(1)

        attr_value = self._parse_attr_value(attr_name)
        return attr_name.decode(), attr_value

    def _parse_attr_value(self, name):
        if name == b'FLAGS':
            return self._parse_flags()
        elif name == b'ENVELOPE':
            return self._parse_envelope()
        elif name == b'INTERNALDATE':
            return self._parse_date_time()
        elif name == b'RFC822.SIZE':
            return self._parse_number()
        elif name.startswith(b'RFC822'):
            return self._parse_nstring()
        elif name == b'BODY':
            return self._parse_body()
        elif name == b'BODYSTRUCTURE':
            return self._parse_body()
        elif name.startswith(b'BODY['):
            return self._parse_nstring()
        elif name == b'UID':
            return self._parse_nznumber()

    def _parse_re(self, regex):
        m = regex.match(self.cur_part, self.offset)
        if not m:
            raise Exception('no match for expected regex: found %r' %
                            self.cur_part[self.offset:])
        self.offset = m.end()
        return m

    def _parse_flags(self):
        # TODO: _FLAGS_RE will accept tokens that aren't valid flags/atoms
        m = self._parse_re(self._FLAGS_RE)
        flags_str = m.group(1).decode()
        return flags_str.split(' ')

    def _parse_date_time(self):
        m = self._parse_re(self._DATE_TIME_RE)

        day = int(m.group('day'), 10)
        month = self._MONTH_MAP[m.group('month')]
        year = int(m.group('year'), 10)
        hours = int(m.group('hours'), 10)
        minutes = int(m.group('minutes'), 10)
        seconds = int(m.group('seconds'), 10)
        zone = int(m.group('zone'), 10)

        zone_hours = int(zone / 100)
        if zone < 0:
            zone_mins = -(-zone % 100)
        else:
            zone_mins = zone % 100
        tzdelta = datetime.timedelta(hours=zone_hours, minutes=zone_mins)
        tz = datetime.timezone(tzdelta)

        dt = datetime.datetime(year=year, month=month, day=day,
                               hour=hours, minute=minutes, second=seconds,
                               tzinfo=tz)
        return dt

    def _parse_envelope(self):
        raise NotImplementedError('parsing ENVELOPE')

    def _parse_body(self):
        raise NotImplementedError('parsing BODYSTRUCTURE')

    def _parse_nstring(self):
        if self.cur_part[self.offset] == ord(b'"'):
            return self._parse_quoted()
        elif self.cur_part[self.offset] == ord(b'{'):
            return self._parse_literal()
        elif self.cur_part[self.offset:].startswith(b'NIL'):
            self.offset += 3
            return None

        raise Exception('expected nstring, found %r' %
                        self.cur_part[self.offset:])

    def _parse_quoted(self):
        if self.cur_part[self.offset] != ord(b'"'):
            raise Exception('expected quoted string, found %r' %
                            self.cur_part[self.offset:])
        self.offset += 1

        parts = []
        while True:
            m = self._parse_re(self._QUOTED_STRING_PART_RE)
            parts.append(m.group(1))
            ch = self.cur_part[self.offset]
            if ch == ord(b'\\'):
                ch = self.cur_part[self.offset + 1]
                parts.append(bytes((ch,)))
                self.offset += 2
            elif ch == ord(b'"'):
                break
            else:
                raise Exception('found unexpected character %r in quoted '
                                'string' % bytes((ch,)))

        return b''.join(parts)

    def _parse_literal(self):
        m = self._parse_re(self._LITERAL_RE)
        literal_len = int(m.group(1), 10)
        if self.offset != len(self.cur_part):
            raise Exception('expected literal string size to appear at end '
                            'of imaplib response element')

        try:
            literal_part = next(self.it)
            self.cur_part = next(self.it)
        except StopIteration:
            raise Exception('missing literal token from imaplib response '
                            'elements')
        self.offset = 0

        if len(literal_part) != literal_len:
            raise Exception('unexpected length for imaplib-parsed literal: '
                            'expected %d, found %d' %
                            (literal_len, len(literal_part)))

        return literal_part

    def _parse_nznumber(self):
        n = self._parse_number()
        if n == 0:
            raise Exception('expected a non-zero number, got 0')
        return n

    def _parse_number(self):
        m = self._parse_re(self._NUMBER_RE)
        return int(m.group(1), 10)
