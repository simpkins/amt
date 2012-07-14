#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#


class Response:
    def __init__(self, tag, resp_type):
        self.tag = tag
        self.resp_type = resp_type


class ResponseParser:
    def __init__(self, tag, resp_type, parts, idx):
        self.tag = tag
        self.resp_type = resp_type
        self.parts = parts
        self.part_idx = 0
        self.char_idx = idx
        self.parse()

    def parse(self):
        raise NotImplementedError('parse() must be implemented by '
                                  'ResponseParser subclasses')

    def ensure_no_literals(self):
        if self.part_idx != len(self.parts) - 1:
            raise ParseError(self.parts, 'unexpected literal token')

    def get_remainder(self):
        self.ensure_no_literals()
        return self.parts[self.part_idx][self.char_idx:]

    def parse_resp_text(self):
        # TODO: parse resp-text-code when the resp-text starts with b'['
        return self.get_remainder()


class ContinuationResponse(Response):
    def __init__(self, resp_text):
        super().__init__(b'+', None)
        self.resp_text = resp_text


class ContinuationResponseParser(ResponseParser):
    def parse(self):
        assert self.tag == b'+'
        resp_text = self.parse_resp_text()
        return ContinuationResponse(resp_text)


class StateResponse(Response):
    def __init__(self, tag, resp_type, resp_text):
        super().__init__(tag, resp_type)
        self.resp_text = resp_text


class StateResponseParser(ResponseParser):
    def parse(self):
        resp_text = self.parse_resp_text()
        return StateResponse(self.tag, self.resp_type, resp_text)


class CapabilityResponse(Response):
    def __init__(self, tag, capabilities):
        super().__init__(tag, b'CAPABILITY')
        self.capabilities = capabilities


class CapabilityResponseParser(ResponseParser):
    def parse(self):
        rest = self.get_remainder()
        capabilities = rest.split(b' ')
        return CapabilityResponse(self.tag, capabilities)


class UnknownResponse(Response):
    def __init__(self, tag, resp_type, cmd_parts):
        super().__init__(tag, resp_type)
        self.cmd_parts = cmd_parts


class UnknownResponseParser(ResponseParser):
    def parse(self):
        return UnknownResponse(self.tag, self.resp_type, self.parts)


_RESPONSE_PARSERS = {
    b'OK': StateResponseParser,
    b'NO': StateResponseParser,
    b'BAD': StateResponseParser,
    b'PREAUTH': StateResponseParser,
    b'BYE': StateResponseParser,
    b'CAPABILITY': CapabilityResponseParser,
    b'FLAGS': UnknownResponseParser,  # TODO
    b'LIST': UnknownResponseParser,  # TODO
    b'LSUB': UnknownResponseParser,  # TODO
    b'SEARCH': UnknownResponseParser,  # TODO
    b'STATUS': UnknownResponseParser,  # TODO
}

_NUMBER_RESPONSE_PARSERS = {
    #b'EXISTS': UnknownResponseParser,  # TODO
    #b'RECENT': UnknownResponseParser,  # TODO
    #b'EXPUNGE': UnknownResponseParser,  # TODO
    #b'FETCH': UnknownResponseParser,  # TODO
}


def parse_response(parts):
    first_line = parts[0]
    # ContinuationResponse is slightly different;
    # It just contains the '+' followed by arbitrary resp-text
    if first_line.startswith(b'+ '):
        parser = ContinuationResponseParser(b'+', None, parts, 2)
        return parser.parse()

    idx = 0
    def next_token():
        nonlocal idx
        assert idx >= 0
        next_sp = first_line.find(b' ', idx)
        if next_sp < 0:
            token = first_line[idx:]
            idx = -1
        else:
            token = first_line[idx:next_sp]
            idx = next_sp + 1
        return token

    tag = next_token()
    if idx < 0:
        raise ParseError(parts, 'no space found after tag')
    resp_type = next_token()

    try:
        number = int(resp_type)
    except ValueError:
        number = None

    # If the resp_type field is a number, parse the next token too.
    # We will look up that token in _NUMBER_RESPONSE_PARSERS
    if number is not None and idx >= 0:
        fallback_idx = idx
        number_resp_type = next_token()
        parser_type = _NUMBER_RESPONSE_PARSERS.get(number_resp_type)
        if parser_type is None:
            parser = UnknownResponseParser(tag, resp_type, parts, fallback_idx)
        else:
            parser = parser_type(tag, number, number_resp_type, parts, idx)
    else:
        parser_type = _RESPONSE_PARSERS.get(resp_type, UnknownResponseParser)
        parser = parser_type(tag, resp_type, parts, idx)

    return parser.parse()
