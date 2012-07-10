#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import datetime
import imaplib
import logging
import re
import socket

from . import ssl_util
from . import message

# Also expose the imaplib port constants as part of our public API.
from imaplib import IMAP4_PORT, IMAP4_SSL_PORT

FLAG_SEEN = r'\Seen'
FLAG_ANSWERED = r'\Answered'
FLAG_FLAGGED = r'\Flagged'
FLAG_DELETED = r'\Deleted'
FLAG_DRAFT =  r'\Draft'
FLAG_RECENT =  r'\Recent'


class ImapError(Exception):
    pass


class NoMessageIdsError(ValueError):
    def __str__(self):
        return 'no message IDs specified'


class Connection:
    def __init__(self, server, port=None, timeout=60):
        if port is None:
            port = IMAP4_SSL_PORT

        ctx = ssl_util.new_ctx()
        self.conn = imaplib.IMAP4_SSL(host=server, port=port,
                                      ssl_context=ctx)
        self.conn.sock.settimeout(timeout)
        logging.debug('Server capabilities: %s', self.conn.capabilities)

    def login(self, user, password):
        self.conn.login(user=user, password=password)

    def select_mailbox(self, mailbox, readonly=False):
        typ, data = self.conn.select(mailbox, readonly=readonly)
        _check_resp(typ, data, 'SELECT')

    def create_mailbox(self, name):
        typ, data = self.conn.create(name)
        _check_resp(typ, data, 'CREATE')

    def search_msg_ids(self, *criteria):
        typ, data = self.conn.uid('SEARCH', *criteria)
        _check_resp(typ, data, 'SEARCH')

        assert isinstance(data, (tuple, list))
        assert len(data) == 1

        # Split the response on spaces, and covert the IDs to integers
        msg_ids = [int(str_id) for str_id in data[0].split()]
        return msg_ids

    def fetch(self, msg_ids, parts, use_uids=True):
        '''
        Send a FETCH command to fetch the specified messages.

        msg_ids should be a list of integer message IDs.  A single message ID
        (rather than a list) is also accepted.

        parts should be a list of message data items to fetch (as specified in
        RFC 3501 section 6.4.5).

        Behaves slightly differently, depending on the msg_ids input:
        - If msg_ids is a sequence of integer IDs, returns a dictionary
          of msg_id --> data
        - If msg_ids is a single integer, returns just the data for that
          message.
        '''
        try:
            ids_arg = self._create_sequence_set(msg_ids)
        except NoMessageIdsError:
            # Just return an empty dictionary if an empty list of message IDs
            # was specified.
            return {}
        parts_arg = '(' + ' '.join(parts) + ')'

        if use_uids:
            typ, data = self.conn.uid('FETCH', ids_arg, parts_arg)
        else:
            typ, data = self.conn.fetch(ids_arg, parts_arg)

        _check_resp(typ, data, 'FETCH')

        return _parse_fetch_response(data, msg_ids, use_uids)

    def fetch_msg(self, msg_ids, use_uids=True):
        parts = ['UID', 'FLAGS', 'INTERNALDATE', 'BODY.PEEK[]']
        response = self.fetch(msg_ids, parts, use_uids=use_uids)

        if isinstance(msg_ids, int):
            # A single message
            return fetch_response_to_msg(response)

        resp_dict = dict((msg_id, fetch_response_to_msg(msg_data))
                         for msg_id, msg_data in response.items())
        return resp_dict

    def copy_msg(self, msg_id, mailbox, use_uids=True):
        '''
        Copy message(s) from the selected mailbox to the mailbox with the
        specified name.
        '''
        ids_arg = self._create_sequence_set(msg_id)

        if use_uids:
            typ, data = self.conn.uid('COPY', ids_arg, mailbox)
        else:
            typ, data = self.conn.copy(ids_arg, mailbox)

        _check_resp(typ, data, 'COPY')

    def delete_msg(self, msg_id, expunge_now=False, use_uids=True):
        self.add_flags(msg_id, [FLAG_DELETED], use_uids=use_uids)

        if expunge_now:
            self.expunge()

    def expunge(self):
        typ, data = self.conn.expunge()
        _check_resp(typ, data, 'EXPUNGE')

    def add_flags(self, msg_ids, flags, use_uids=True):
        '''
        Add the specified flags to the specified message(s)
        '''
        self._update_flags('+FLAGS.SILENT', msg_ids, flags, use_uids=use_uids)

    def remove_flags(self, msg_ids, flags, use_uids=True):
        '''
        Remove the specified flags from the specified message(s)
        '''
        self._update_flags('-FLAGS.SILENT', msg_ids, flags, use_uids=use_uids)

    def replace_flags(self, msg_ids, flags, use_uids=True):
        '''
        Replace the flags on the specified message(s) with the new list of
        flags.
        '''
        self._update_flags('FLAGS.SILENT', msg_ids, flags, use_uids=use_uids)

    def get_flags(self, msg_ids, use_uids=True):
        responses = self.fetch(msg_ids, ['FLAGS'], use_uids=use_uids)
        if isinstance(msg_ids, int):
            return responses['FLAGS']
        return dict((msg_id, data['FLAGS'])
                    for msg_id, data in responses.items())

    imaplib.Commands['IDLE'] = ('SELECTED',)

    def idle(self, callback, timeout=-1, timeout_callback=None):
        # imaplib doesn't support IDLE, so we build it ourselves.
        # Currently we're using a bunch of the non-public functions, which is
        # kind of crappy.

        tag = self.conn._command('IDLE')

        # Wait for a continuation response
        while self.conn._get_response():
            if self.tagged_commands[tag]:
                return self.conn._command_complete('IDLE', tag)

        # Flush old responses
        logging.debug('dropping %d old untagged responses when entering '
                      'IDLE (%r)', len(self.conn.untagged_responses),
                      self.conn.untagged_responses)
        self.conn.untagged_responses = {}

        orig_timeout = None
        if timeout is None or timeout >= 0:
            orig_timeout = self.conn.sock.gettimeout()
            self.conn.sock.settimeout(timeout)
        try:
            # Wait for untagged responses
            while True:
                try:
                    self.conn._get_response()
                except socket.timeout:
                    break

                for typ, responses in self.conn.untagged_responses:
                    for resp in responses:
                        idle_callback(typ, resp)
        finally:
            if orig_timeout is not None:
                self.conn.sock.settimeout(orig_timeout)

        self.conn.send(b'DONE\r\n')
        return self.conn._command_complete('IDLE', tag)

    def _update_flags(self, cmd, msg_ids, flags, use_uids=True):
        if isinstance(flags, str):
            flags = [flags]
        flags_arg = '(%s)' % ' '.join(flags)

        ids_arg = self._create_sequence_set(msg_ids)
        if use_uids:
            typ, data = self.conn.uid('STORE', ids_arg, cmd, flags_arg)
        else:
            typ, data = self.conn.store(ids_arg, data_item, flags_arg)

        _check_resp(typ, data, 'STORE')
        # Note that we could call _parse_fetch_response() to parse the response
        # data here.  Unfortunately, if use_uids is True, the "UID STORE"
        # response does not include UIDs, so we won't be able to figure out
        # which response is for which message.  Therefore, for now we just
        # ignore the response data and always use FLAGS.SILENT when storing.

    def _create_sequence_set(self, msg_ids, allow_one=True):
        if allow_one and isinstance(msg_ids, int):
            return str(msg_ids).encode('ASCII')
        if not msg_ids:
            raise NoMessageIdsError()
        return b','.join(str(i).encode('ASCII') for i in msg_ids)


def _check_resp(typ, data, cmd):
    if typ != 'OK':
        raise ImapError('unexpected response from %s: (%r, %r)' %
                        (cmd, typ, data))


def _parse_fetch_response(data, msg_ids, use_uids):
    responses = _reassemble_fetch_resp(data)

    if isinstance(msg_ids, int):
        # If a single message was requested, return just the single response
        # for that message.
        assert len(responses) == 1
        parser = _FetchParser(responses[0])
        msg_seq, attributes = parser.parse()
        if use_uids:
            assert attributes['UID'] == msg_ids
        else:
            assert msg_seq == msg_ids
        return attributes

    assert len(responses) == len(msg_ids)
    resp_dict = {}
    for resp in responses:
        parser = _FetchParser(resp)
        msg_seq, attributes = parser.parse()
        if use_uids:
            msg_seq = attributes['UID']
        assert msg_seq in msg_ids
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


def fetch_response_to_msg(response):
    '''
    Create a new Message from an IMAP FETCH response that includes at
    least BODY[], INTERNALDATE, and FLAGS fields.
    '''
    body = response['BODY[]']
    timestamp = response['INTERNALDATE']
    imap_flags = response['FLAGS']

    flags = set()
    custom_flags = set()
    for flag in imap_flags:
        if flag == FLAG_SEEN:
            flags.add(message.Message.FLAG_SEEN)
        elif flag == FLAG_ANSWERED:
            flags.add(message.Message.FLAG_REPLIED_TO)
        elif flag == FLAG_FLAGGED:
            flags.add(message.Message.FLAG_FLAGGED)
        elif flag == FLAG_DELETED:
            flags.add(message.Message.FLAG_DELETED)
        elif flag == FLAG_DRAFT:
            flags.add(message.Message.FLAG_DRAFT)
        else:
            custom_flags.add(flag)

    return message.Message.from_bytes(body, timestamp=timestamp, flags=flags,
                                      custom_flags=custom_flags)
