#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import datetime
import re

from .err import ParseError

_MONTHS = {
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


class Response:
    def __init__(self, tag, resp_type):
        self.tag = tag
        self.resp_type = resp_type

    def __str__(self):
        tag_str = self.tag.decode('ASCII', errors='replace')
        type_str = self.resp_type.decode('ASCII', errors='replace')
        return '%s %s' % (tag_str, type_str)


class ResponseCode:
    def __init__(self, token, data=None):
        self.token = token
        self.data = data


class ContinuationResponse(Response):
    def __init__(self, code, text):
        super().__init__(b'+', None)
        self.code = code
        self.text = text

    def __str__(self):
        return '+ ' + self.text.decode('ASCII', errors='replace')


class StateResponse(Response):
    def __init__(self, tag, resp_type, code, text):
        super().__init__(tag, resp_type)
        self.code = code
        self.text = text

    def __str__(self):
        tag_str = self.tag.decode('ASCII', errors='replace')
        type_str = self.resp_type.decode('ASCII', errors='replace')
        text_str = self.text.decode('ASCII', errors='replace')
        return '%s %s %s' % (tag_str, type_str, text_str)


class CapabilityResponse(Response):
    def __init__(self, tag, capabilities):
        super().__init__(tag, b'CAPABILITY')
        self.capabilities = capabilities


class FlagsResponse(Response):
    def __init__(self, tag, flags):
        super().__init__(tag, b'FLAGS')
        self.flags = flags


class SearchResponse(Response):
    def __init__(self, tag, msg_numbers):
        super().__init__(tag, b'SEARCH')
        self.msg_numbers = msg_numbers


class ListResponse(Response):
    def __init__(self, tag, mailbox, attributes, delimiter):
        super().__init__(tag, b'LIST')
        self.mailbox = mailbox
        self.attributes = attributes
        self.delimiter = delimiter


class StatusResponse(Response):
    def __init__(self, tag, mailbox, attributes):
        super().__init__(tag, b'STATUS')
        self.mailbox = mailbox
        self.attributes = attributes


class NumericResponse(Response):
    def __init__(self, tag, number, resp_type):
        super().__init__(tag, resp_type)
        self.number = number


class UnknownNumericResponse(NumericResponse):
    def __init__(self, tag, number, resp_type, parts):
        super().__init__(tag, number, resp_type)
        self.parts = parts


class FetchResponse(NumericResponse):
    def __init__(self, tag, number, attributes):
        super().__init__(tag, number, b'FETCH')
        self.attributes = attributes


class UnknownResponse(Response):
    def __init__(self, tag, resp_type, cmd_parts):
        super().__init__(tag, resp_type)
        self.cmd_parts = cmd_parts


class ResponseParser:
    def __init__(self, parts):
        self.parts = parts
        self.part_idx = 0
        self.char_idx = 0

    def parse(self):
        self.tag = self.read_until(b' ')
        self.advance_over(b' ')

        if self.tag == b'+':
            code, text = self.parse_resp_text()
            return ContinuationResponse(code, text)

        token = self.read_until(b' ')
        try:
            self.number = int(token)
        except ValueError:
            self.number = None
            self.resp_type = token

        if self.number is not None:
            self.advance_over(b' ')
            self.resp_type = self.read_until(b' ')
            return self.parse_numeric_response()

        if self.resp_type in (b'OK', b'NO', b'BAD', b'PREAUTH', b'BYE'):
            return self.parse_state_response()

        if self.resp_type == b'CAPABILITY':
            return self.parse_capability_response()
        elif self.resp_type == b'FLAGS':
            return self.parse_flags_response()
        elif self.resp_type == b'SEARCH':
            return self.parse_search_response()
        elif self.resp_type == b'LIST':
            return self.parse_list_response()
        elif self.resp_type == b'STATUS':
            return self.parse_status_response()

        #b'LSUB': UnknownResponseParser,  # TODO

        return UnknownResponse(self.tag, self.resp_type, self.parts)

    def error(self, msg, *args):
        raise ParseError(self.parts, msg, *args)

    def parse_numeric_response(self):
        if self.resp_type in (b'EXISTS', b'RECENT', b'EXPUNGE'):
            self.ensure_eom()
            return NumericResponse(self.tag, self.number, self.resp_type)

        if self.resp_type != b'FETCH':
            return UnknownNumericResponse(self.tag, self.number,
                                          self.resp_type, self.parts)

        return self.parse_fetch_response()

    def parse_state_response(self):
        self.advance_over(b' ')
        code, text = self.parse_resp_text()
        return StateResponse(self.tag, self.resp_type, code, text)

    def parse_fetch_response(self):
        self.advance_over(b' (')

        attributes = {}
        while True:
            att_name = self.read_until(b' ')
            value = None

            self.advance_over(b' ')
            if att_name == b'FLAGS':
                self.advance_over(b'(')
                flags_str = self.read_until(b')')
                value = flags_str.split(b' ')
                self.advance_over(b')')
            elif att_name == b'ENVELOPE':
                value = self.parse_envelope()
            elif att_name == b'INTERNALDATE':
                value = self.parse_date_time()
            elif att_name == b'RFC822.SIZE':
                value = self.read_number()
            elif att_name in [b'RFC822', b'RFC822.HEADER', b'RFC822.TEXT']:
                value = self.read_nstring()
            elif att_name in [b'BODY', b'BODYSTRUCTURE']:
                value = self.parse_body()
            elif att_name.startswith(b'BODY'):
                value = self.read_nstring()
            elif att_name == b'UID':
                value = self.read_nznumber()
            else:
                self.error('received unknown attribute "%s" in FETCH response',
                           att_name)

            assert value != None
            attributes[att_name] = value

            c = self.get_char()
            if c == b')':
                break
            if c != b' ':
                self.error('expected space or ")" in FETCH response, '
                           'found %r', c)

        self.ensure_eom()

        return FetchResponse(self.tag, self.number, attributes)

    def parse_capability_response(self):
        self.advance_over(b' ')
        rest = self.get_remainder()
        capabilities = rest.split(b' ')
        return CapabilityResponse(self.tag, capabilities)

    def parse_flags_response(self):
        self.advance_over(b' (')
        flags_str = self.read_until(b')')
        self.advance_over(b')')
        self.ensure_eom()

        flags = flags_str.split(b' ')
        return FlagsResponse(self.tag, flags)

    def parse_search_response(self):
        if self.is_at_eom():
            return SearchResponse(self.tag, [])

        self.advance_over(b' ')
        data = self.get_remainder()
        msg_number_strings = data.split(b' ')
        msg_nums = []
        for num_str in msg_number_strings:
            try:
                num = int(num_str)
            except ValueError:
                self.error('invalid message number in SEARCH response: %r',
                           num_str)
            msg_nums.append(num)

        return SearchResponse(self.tag, msg_nums)

    def parse_list_response(self):
        self.advance_over(b' (')
        attr_str = self.read_until(b')')
        attributes = attr_str.split(b' ')
        self.advance_over(b') ')

        if self.advance_if(b'NIL'):
            delimiter = None
        else:
            delimiter = self.read_quoted_string()

        self.advance_over(b' ')
        mailbox = self.read_astring()
        self.ensure_eom()
        return ListResponse(self.tag, mailbox=mailbox, attributes=attributes,
                            delimiter=delimiter)

    def parse_status_response(self):
        self.advance_over(b' ')
        mailbox = self.read_astring()
        self.advance_over(b' (')

        attributes = {}
        if not self.advance_if(b')'):
            while True:
                att_name = self.read_until(b' ')
                self.advance_over(b' ')
                num = self.read_number()
                attributes[att_name] = num
                if not self.advance_if(b' '):
                    break
            self.advance_over(b')')

        # MS Exchange servers seem to include a trailing space here,
        # even though it doesn't seem to be allowed by the RFC 3501 grammar.
        self.advance_if(b' ')

        self.ensure_eom()
        return StatusResponse(self.tag, mailbox, attributes)

    def ensure_no_literals(self):
        if self.part_idx != len(self.parts) - 1:
            self.error('unexpected literal token')

    def ensure_eom(self):
        if not self.is_at_eom():
            self.error('expected end of message')

    def is_at_eom(self):
        if not self.is_at_end_of_part():
            return False
        if self.part_idx != len(self.parts) - 1:
            return False
        return True

    def is_at_end_of_part(self):
        return self.char_idx == len(self.parts[self.part_idx])

    def peek_char(self):
        if self.is_at_end_of_part():
            self.error('unexpected end of command')
        return self.parts[self.part_idx][self.char_idx:self.char_idx + 1]

    def get_char(self):
        char = self.parts[self.part_idx][self.char_idx:self.char_idx + 1]
        self.char_idx += 1
        return char

    def is_next(self, expected):
        buf = self.parts[self.part_idx]
        end = self.char_idx + len(expected)
        actual = buf[self.char_idx:end]
        return actual == expected

    def advance_if(self, expected):
        buf = self.parts[self.part_idx]
        end = self.char_idx + len(expected)
        actual = buf[self.char_idx:end]
        if actual == expected:
            self.char_idx = end
            return True
        return False

    def advance_over(self, expected):
        buf = self.parts[self.part_idx]
        end = self.char_idx + len(expected)
        actual = buf[self.char_idx:end]
        if actual != expected:
            self.error('expected %r, but found %r', expected, actual)

        self.char_idx = end

    def read_until(self, delim):
        '''
        Read until any one of the characters in delim is found.
        Returns the read data, excluding the delimiter.
        '''
        if self.is_at_end_of_part():
            return b''

        buf = self.parts[self.part_idx]
        start = self.char_idx
        while True:
            if buf[self.char_idx] in delim:
                return buf[start:self.char_idx]
            self.char_idx += 1
            if self.char_idx == len(buf):
                data = buf[start:]
                return data

    def read_while(self, chars):
        '''
        Read until a character not in the specified set of characters is found.
        Returns the read data.
        '''
        if self.is_at_end_of_part():
            return b''

        buf = self.parts[self.part_idx]
        start = self.char_idx
        while True:
            if buf[self.char_idx] not in chars:
                return buf[start:self.char_idx]
            self.char_idx += 1
            if self.char_idx == len(buf):
                data = buf[start:]
                return data

    def read_astring(self):
        # Check for a literal
        if self.is_at_end_of_part():
            return self.read_literal()

        # Check for a quoted string
        if self.is_next(b'"'):
            return self.read_quoted_string()

        # Must be an atom
        # TODO: Also stop at control chars or anything over 0x7e
        data = self.read_until(b'(){ %*"\\')
        if not data:
            self.error('expected astring, found nothing')
        return data

    def read_string(self):
        if self.is_at_end_of_part():
            return self.read_literal()

        if self.is_next(b'"'):
            return self.read_quoted_string()

        self.error('expected string, but found %r', char)

    def read_nstring(self):
        if self.is_at_end_of_part():
            return self.read_literal()

        char = self.peek_char()
        if char == b'"':
            return self.read_quoted_string()

        if self.advance_if(b'NIL'):
            return None

        self.error('expected nstring, but found %r', char)

    def read_literal(self):
        if not self.is_at_end_of_part():
            self.error('expected literal, but found non-literal data')
        if self.part_idx >= len(self.parts) - 1:
            self.error('expected literal, but found end of message')

        assert self.part_idx + 2 < len(self.parts)
        literal = self.parts[self.part_idx + 1]
        self.part_idx += 2
        self.char_idx = 0
        return literal

    def read_quoted_string(self):
        self.advance_over(b'"')
        data = self.read_until(b'"')
        self.advance_over(b'"')
        return data

    def read_number(self):
        num_str = self.read_while(b'0123456789')
        try:
            return int(num_str)
        except ValueError:
            self.error('expected number, found "%s"', num_str)

    def read_nznumber(self):
        num = self.read_number()
        if num == 0:
            self.error('expected non-zero number, but got 0')
        return num

    def get_remainder(self):
        self.ensure_no_literals()
        return self.parts[self.part_idx][self.char_idx:]

    def parse_resp_text(self):
        if self.is_at_end_of_part():
            sef.ensure_eom()
            return (None, b'')

        if not self.is_next(b'['):
            # No resp-text-code, just human readable data.
            return (None, self.get_remainder())

        self.advance_over(b'[')
        token = self.read_until(b' ]')

        if token in (b'ALERT', b'PARSE', b'READ-ONLY', b'READ-WRITE',
                     b'TRYCREATE', b'UIDNOTSTICKY'):
            # These codes aren't allowed to be followed by any data
            if not self.is_next(b']'):
                self.error('unexpected data after %s response code', token)
            code = ResponseCode(token)
        elif token == b'BADCHARSET':
            code = self.parse_badcharset_code()
        elif token == b'CAPABILITY':
            code = self.parse_capability_code()
        elif token == b'PERMANENTFLAGS':
            code = self.parse_permflags_code()
        elif token in (b'UIDNEXT', b'UIDVALIDITY', b'UIDSEEN',
                       b'HIGHESTMODSEQ'):
            data = self.read_until(b']')
            try:
                number = int(data)
            except ValueError:
                self.error('expected number after %s response code, found %r',
                           token, data)
            code = ResponseCode(token, number)
        else:
            # TODO: APPENDUID
            # TODO: COPYUID
            if self.advance_if(b' '):
                data = self.read_until(b']')
                code = ResponseCode(token, data)
            else:
                code = ResponseCode(token)

        self.advance_over(b'] ')
        return code, self.get_remainder()

    def parse_badcharset_code(self):
        # BADCHARSET doesn't necessarily need to be followed by anything
        if not self.advance_if(b' '):
            return

        self.advance_over(b'(')
        tokens = []
        while True:
            token = self.read_astring()
            tokens.append(token)
            if self.advance_if(b')'):
                break

        return ResponseCode(b'BADCHARSET', tokens)

    def parse_capability_code(self):
        self.advance_over(b' ')
        capability_str = self.read_until(b']')
        capabilities = capability_str.split(b' ')
        return ResponseCode(b'CAPABILITY', capabilities)

    def parse_permflags_code(self):
        self.advance_over(b' (')
        flags_str = self.read_until(b')')
        self.advance_over(b')')

        flags = flags_str.split(b' ')
        return ResponseCode(b'PERMANENTFLAGS', flags)

    def parse_date_time(self):
        date_str = self.read_quoted_string()

        regex = re.compile(br'(?P<day>[ 0-9][0-9])-(?P<month>[A-Za-z]{3})-'
                           br'(?P<year>[0-9]{4}) '
                           br'(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):'
                           br'(?P<second>[0-9]{2}) '
                           br'(?P<zone_sign>[-+])(?P<zone_hours>[0-9]{2})'
                           br'(?P<zone_minutes>[0-9]{2})')
        m = regex.match(date_str)
        if not m:
            self.error('expected date-time, got "%s"', date_str)

        try:
            month = _MONTHS[m.group('month')]
        except KeyError:
            self.error('invalid month "%s"', m.group('month'))

        # Parse the time zone info
        if m.group('zone_sign' == b'-'):
            zone_hours = -1 * int(m.group('zone_hours'))
            zone_minutes = -1 * int(m.group('zone_minutes'))
        else:
            zone_hours = int(m.group('zone_hours'))
            zone_minutes = int(m.group('zone_minutes'))
        tz_delta = datetime.timedelta(hours=zone_hours, minutes=zone_minutes)
        tz = datetime.timezone(tz_delta)

        dt = datetime.datetime(year=int(m.group('year')),
                               month=month,
                               day=int(m.group('day')),
                               hour=int(m.group('hour')),
                               minute=int(m.group('minute')),
                               second=int(m.group('second')),
                               tzinfo=tz)

        return dt

    def parse_envelope(self):
        self.advance_over(b'(')
        date = self.read_nstring()
        self.advance_over(b' ')
        subject = self.read_nstring()
        self.advance_over(b' ')
        from_addr = self.parse_env_address_list()
        self.advance_over(b' ')
        sender = self.parse_env_address_list()
        self.advance_over(b' ')
        reply_to = self.parse_env_address_list()
        self.advance_over(b' ')
        to = self.parse_env_address_list()
        self.advance_over(b' ')
        cc = self.parse_env_address_list()
        self.advance_over(b' ')
        bcc = self.parse_env_address_list()
        self.advance_over(b' ')
        in_reply_to = self.read_nstring()
        self.advance_over(b' ')
        message_id = self.read_nstring()
        self.advance_over(b')')

        return Envelope(date, subject, from_addr, sender, reply_to,
                        to, cc, bcc, in_reply_to, message_id)

    def parse_env_address_list(self):
        if self.advance_if(b'NIL'):
            return []

        self.advance_over(b'(')
        addresses = []
        while True:
            addr = self.parse_address()
            if self.advance_if(b')'):
                return addresses
            # The grammar in RFC 3501 seems to indicate that there isn't
            # supposed to be a space here.  However, some servers (at least
            # MS Exchange) use one.  The examples in the RFC are somewhat
            # ambiguous: they have newlines in the address list to avoid line
            # wrapping.
            self.advance_if(b' ')

    def parse_address(self):
        self.advance_over(b'(')
        name = self.read_nstring()
        self.advance_over(b' ')
        adl = self.read_nstring()
        self.advance_over(b' ')
        mailbox = self.read_nstring()
        self.advance_over(b' ')
        host = self.read_nstring()
        self.advance_over(b')')

        return Address(name, adl, mailbox, host)

    def parse_body(self):
        self.advance_over(b'(')

        if self.is_next(b'('):
            # body-type-mpart
            bodies = []
            while True:
                b = self.parse_body()
                bodies.append(b)
                # The grammar in RFC 3501 seems to indicate that the bodies
                # will appear one after the other with no spaces in between.
                # Allow a space in between, just in case.
                self.advance_if(b' ')
                if not self.is_next(b'('):
                    break

            self.advance_over(b' ')
            media_subtype = self.read_string()
            if self.advance_if(b' '):
                self.parse_body_ext_mpart(body)
            self.advance_over(b')')
            return MultiPartBody(bodies, media_subtype)

        # body-type-1part
        media_type = self.read_string()
        self.advance_over(b' ')
        media_subtype = self.read_string()
        body = Body(media_type, media_subtype)

        # body-fld-param: "(" string SP string *(SP string SP string) ")" / nil
        self.advance_over(b' ')
        body.params = self.parse_body_fld_params()

        self.advance_over(b' ')
        body.content_id = self.read_nstring()
        self.advance_over(b' ')
        body.description = self.read_nstring()
        self.advance_over(b' ')
        body.encoding = self.read_string()
        self.advance_over(b' ')
        body.num_octets = self.read_number()

        if (media_type.upper() == b'MESSAGE' and
            media_subtype.upper() == b'RFC822'):
            body.rfc822_envelope = self.parse_envelope()
            self.advance_over(b' ')
            body.rfc822_body = self.read_body()
            self.advance_over(b' ')
            body.num_lines = self.read_number()
        elif media_type.upper() == b'TEXT':
            # RFC 3501 seems to indicate that body-fld-lines should always
            # be present for TEXT messages, but we'll be conservative and
            # allow it to not be present.
            if self.advance_if(b' '):
                body.num_lines = self.read_number()

        if self.advance_if(b' '):
            self.parse_body_ext_1part(body)

        self.advance_over(b')')

        return body

    def parse_body_fld_params(self):
        if self.advance_if(b'NIL'):
            return []

        params = []
        self.advance_over(b'(')
        while True:
            param_name = self.read_string()
            self.advance_over(b' ')
            param_value = self.read_string()
            params.append((param_name, param_value))
            if self.advance_if(b')'):
                break
            self.advance_over(b' ')

        return params

    def parse_body_ext_mpart(self, body):
        body.params = self.parse_body_fld_params()
        if not self.advance_if(b' '):
            return

        self.parse_body_ext_common(body)

    def parse_body_ext_1part(self, body):
        body.md5 = self.read_nstring()
        if not self.advance_if(b' '):
            return

        self.parse_body_ext_common(body)

    def parse_body_ext_common(self, body):
        # body-fld-dsp
        if self.advance_if(b'('):
            body.disposition_type = self.read_string()
            body.disposition_params = self.parse_body_fld_params()
            self.advance_over(b')')
        else:
            self.advance_over(b'NIL')

        if not self.advance_if(b' '):
            return

        # body-fld-lang
        if self.advance_if(b'('):
            body.language = []
            while True:
                lang = self.read_string()
                body.language.append(lang)
                if not self.advance_if(b' '):
                    break
            self.advance_over(b')')
        else:
            body.language = self.read_nstring()

        if not self.advance_if(b' '):
            return

        # body-fld-loc
        body.location = self.read_nstring()

        if not self.advance_if(b' '):
            return

        body.extensions = self.parse_body_extension()

    def parse_body_extension(self):
        if self.is_at_end_of_part():
            return self.read_literal()

        c = self.peek_char()
        if c == b'(':
            self.advance_over(b'(')
            extensions = []
            while True:
                ext = self.parse_body_extension()
                extensions.append(ext)
                if self.advance_if(b')'):
                    return extensions
                self.advance_over(b' ')
        elif c == b'"':
            return self.read_quoted_string()
        else:
            return self.read_number()


class Envelope:
    def __init__(self, date, subject, from_addr, sender, reply_to,
                 to, cc, bcc, in_reply_to, message_id):
        self.date = date
        self.subject = subject
        self.from_addr = from_addr
        self.sender = sender
        self.reply_to = reply_to
        self.to = to
        self.cc = cc
        self.bcc = bcc
        self.in_reply_to = in_reply_to
        self.message_id = message_id


class Address:
    def __init__(self, name, adl, host, mailbox):
        self.name = name
        self.adl = adl
        self.host = host
        self.mailbox = mailbox


class Body:
    def __init__(self, media_type, media_subtype):
        self.media_type = media_type
        self.media_subtype = media_subtype

        # Subsequent fields set by Connection.parse_body()
        self.params = []
        self.disposition_type = None
        self.disposition_params = None
        self.language = None
        self.location = None
        self.extensions = None


class MultiPartBody(Body):
    def __init__(self, bodies, media_subtype):
        super().__init__(b'MULTIPART', media_subtype)
        self.bodies = bodies


class OnePartBody(Body):
    def __init__(self, media_type, media_subtype):
        super().__init__(media_type, media_subtype)

        # Subsequent fields set by Connection.parse_body()
        body.content_id = None
        body.description = None
        body.encoding = None
        body.num_octets = None

        # rfc822_envelope and rfc822_present are only present for
        # messages with media type MESSAGE/RFC822
        self.rfc822_envelope = None
        self.rfc822_body = None
        # num_lines is only present for messages with media type MESSAGE/RFC822
        # or TEXT/*
        self.num_lines = None

        self.md5 = None


def parse_response(parts):
    parser = ResponseParser(parts)
    return parser.parse()
