#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
from .err import ParseError


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


class NumericResponse(Response):
    def __init__(self, tag, number, resp_type):
        super().__init__(tag, resp_type)
        self.number = number


class UnknownNumericResponse(NumericResponse):
    def __init__(self, tag, number, resp_type, parts):
        super().__init__(tag, number, resp_type)
        self.parts = parts


class FetchResponse(NumericResponse):
    def __init__(self, tag, number):
        super().__init__(tag, number, b'FETCH')
        # TODO: Store the additional data from the response


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

        #b'LIST': UnknownResponseParser,  # TODO
        #b'LSUB': UnknownResponseParser,  # TODO
        #b'STATUS': UnknownResponseParser,  # TODO

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
        # FIXME
        raise NotImplementedError('parsing FETCH response not implemented')
        return FetchResponse(self.tag, self.number)

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

        # The delimiters are specified as bytes.
        # Convert them into a list of the integer values
        delim_values = [c for c in delim]

        buf = self.parts[self.part_idx]
        start = self.char_idx
        while True:
            if buf[self.char_idx] in delim:
                return buf[start:self.char_idx]
            self.char_idx += 1
            if self.char_idx == len(buf):
                data = buf[start:]
                return data

    def read_astring(self):
        # Check for a literal
        if self.is_at_end_of_part():
            if self.part_idx < len(self.parts) - 1:
                assert self.part_idx + 2 < len(self.parts)
                literal = self.parts[self.part_idx + 1]
                self.part_idx += 1
                self.char_idx = 0
                return literal
            self.error('expected astring, but found end of message')

        # Check for a quoted string
        char = self.peek_char()
        if char == b'"':
            self.advance_over(b'"')
            data = self.read_until(b'"')
            self.advance_over(b'"')
            return data

        # Must be an atom
        # TODO: Also stop at control chars or anything over 0x7e
        data = self.read_until(b'(){ %*"\\')
        return data

    def get_remainder(self):
        self.ensure_no_literals()
        return self.parts[self.part_idx][self.char_idx:]

    def parse_resp_text(self):
        if self.is_at_end_of_part():
            sef.ensure_eom()
            return (None, b'')

        if self.peek_char() != b'[':
            # No resp-text-code, just human readable data.
            return (None, self.get_remainder())

        self.advance_over(b'[')
        token = self.read_until(b' ]')

        if token in (b'ALERT', b'PARSE', b'READ-ONLY', b'READ-WRITE',
                     b'TRYCREATE', b'UIDNOTSTICKY'):
            # These codes aren't allowed to be followed by any data
            if self.peek_char() != b']':
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
            if self.peek_char() == b' ':
                self.advance_over(b' ')
                data = self.read_until(b']')
                code = ResponseCode(token, data)
            else:
                code = ResponseCode(token)

        self.advance_over(b'] ')
        return code, self.get_remainder()

    def parse_badcharset_code(self):
        self.advance_over(b' (')
        tokens = []
        while True:
            if self.peek_char() == b')':
                break
            token = self.read_astring()
            tokens.append(token)

        # We could perhaps verify that at least one token was present.
        # This is required by the RFC.

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


def parse_response(parts):
    parser = ResponseParser(parts)
    return parser.parse()
