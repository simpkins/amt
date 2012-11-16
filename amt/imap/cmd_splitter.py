#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import logging

from .err import ImapError, ParseError

_ASCII_CR = ord(b'\r')
_ASCII_LF = ord(b'\n')
_ASCII_OPEN_BRACE = ord(b'{')
_ASCII_CLOSE_BRACE = ord(b'}')


# Note: This class is somewhat heuristic, and makes a best effort to detect
# command boundaries, but it isn't guaranteed to be right.
#
# Currently the only case where it may be wrong is if the server ends a
# resp-text section with something that looks like the start of a string
# literal ({NNN}\r\n).  Hopefully no sane servers do this.  Python's built-in
# imaplib module would also interpret such a response incorrectly.
#
# IMAP seems like a fairly stupidly designed language from a parsing
# perspective.  You can't detect command boundaries without knowing exactly
# what the command is and how it should be parsed.  You can't even tokenize the
# data: In some cases a DQUOTE indicates the start of a quoted string, in some
# cases it's not special at all.  In some cases {NNN} followed by CRLF
# indicates the start of a string literal, in some cases its just normal data
# and the CRLF indicates the end of the command.
class CommandSplitter:
    '''
    CommandSplitter accepts data via the feed() function, and splits it up into
    separate IMAP commands.

    When a full command has been received, the cmd_callback is invoked with the
    command parts.  The command parts is a list of alternating lines and
    literal tokens.  (This structure is used based on IMAPs protocol format:
    commands consist of full lines, but literal tokens may appear in the line
    as well.)

    The command parts list will always contain an odd number of parts: starting
    and ending with a text-based line.  The lines passed to the cmd_callback do
    not contain the b'\r\n' terminator.

    CommandSplitter expects to receive input as bytes, and will also pass the
    command parts to cmd_callback as bytes.
    '''
    def __init__(self, cmd_callback, conn_id=None):
        # A list of the command parts.  This is an alternating list of
        # lines and literal tokens.  A fully parsed command always starts and
        # ends with a line.
        #
        # The lines do not include the terminating b'\r\n'.
        self._cmd_parts = []

        # The list of buffers remaining to be parsed
        # All buffers in self._to_parse are guaranteed to be non-empty
        self._to_parse = []
        # The list of buffers already parsed, and known to be part of the
        # next cmd_part
        self._current_bufs = []

        # The remaining length of the literal token we are currently trying to
        # parse
        self._literal_len_left = None

        # The callback to invoke when we have a full command available
        # This will be invoked with the self._cmd_parts list
        self.cmd_callback = cmd_callback

        self._conn_id = conn_id

    def feed(self, data):
        assert isinstance(data, (bytes, bytearray))
        if not data:
            return

        # Appending to buffers is very expensive in python, so rather than
        # joining the unparsed data into one buffer, keep a list of the
        # individual buffers we have received.
        self._to_parse.append(data)

        while True:
            if self._literal_len_left is not None:
                if not self._parse_literal():
                    return
            else:
                if not self._parse_line():
                    return

    def eof(self):
        if self._to_parse or self._current_bufs:
            parts_so_far = self._current_bufs + self._to_parse
            raise ParseError(parts_so_far, 'unexpected EOF')

    def _parse_literal(self):
        assert self._literal_len_left is not None
        assert(len(self._cmd_parts) % 2 == 1)

        while self._literal_len_left > 0 and self._to_parse:
            buf = self._to_parse[0]
            if len(buf) > self._literal_len_left:
                idx = self._literal_len_left
                self._literal_len_left = 0
                self._current_bufs.append(buf[:idx])
                self._to_parse[0] = buf[idx:]
                break
            else:
                self._current_bufs.append(buf)
                self._literal_len_left -= len(buf)
                self._to_parse.pop(0)

        if self._literal_len_left == 0:
            full_literal = b''.join(self._current_bufs)
            self._current_bufs = []
            self._literal_len_left = None
            self._cmd_parts.append(full_literal)
            return True

        return False

    def _parse_line(self):
        assert self._literal_len_left is None
        assert(len(self._cmd_parts) % 2 == 0)

        while self._to_parse:
            buf = self._to_parse[0]

            if (self._current_bufs and
                self._current_bufs[-1][-1] == _ASCII_CR and
                buf[0] == _ASCII_LF):
                # The CRLF is split across the last buffer and this one
                self._current_bufs[-1] = self._current_bufs[-1][:-1]
                if len(buf) == 1:
                    self._to_parse.pop(0)
                else:
                    self._to_parse[0] = buf[1:]
                self._on_full_line()
                return True

            idx = buf.find(b'\r\n')
            if idx < 0:
                # No CRLF in this buffer.  Append it and move on
                self._current_bufs.append(buf)
                self._to_parse.pop(0)
                continue

            # Found a CRLF
            self._current_bufs.append(buf[:idx])
            if len(buf) == idx + 2:
                self._to_parse.pop(0)
            else:
                self._to_parse[0] = buf[idx + 2:]
            self._on_full_line()
            return True

        return False

    def _on_full_line(self):
        assert self._current_bufs
        line = b''.join(self._current_bufs)

        if self._conn_id is None:
            logging.debug('Response line: %s', line)
        else:
            logging.debug('conn %d: Response line: %s', self._conn_id, line)

        self._current_bufs = []
        line, literal_count = self._strip_literal_length(line)
        self._cmd_parts.append(line)

        if literal_count is None:
            # No literal token, this is the end of the command.
            # Inform the cmd_callback
            self._on_cmd_end()
        else:
            assert self._literal_len_left is None
            self._literal_len_left = literal_count

    def _on_cmd_end(self):
        parts = self._cmd_parts
        self._cmd_parts = []
        self.cmd_callback(parts)

    def _strip_literal_length(self, line):
        '''
        Strip off any literal count from the end of the line.

        Returns a tuple of (stripped_line, count).  If no literal count was
        present, stripped_line is the same as the original line, and count is
        None.

        Note that a count of 0 may be returned, so be careful to distinguish
        return values of None from 0.
        '''
        # TODO: IMAP was unfortunately not at all designed with ease of parsing
        # in mind.  We can't really tell where the command ends without fully
        # parsing the command.
        #
        # We assume that a line ending in {NNN} indicates a literal count, but
        # this is not necessarily guaranteed to be true.  Some commands end
        # with resp-text, which can include any arbitrary text, including
        # things that look like literal counts.  Hopefully no sane server will
        # ever send a resp-text that ends in something that looks like a
        # literal count.  In order to really figure out if this line may end in
        # a literal, we would need to fully parse the command up to this point
        # first.
        if not line:
            return (line, None)

        end = len(line) - 1
        if line[end] != _ASCII_CLOSE_BRACE:
            return (line, None)

        idx = end
        while True:
            idx -= 1
            if idx < 0:
                break

            char_value = line[idx]
            if char_value == _ASCII_OPEN_BRACE:
                # Looks like a literal count; return it
                count = int(line[idx+1:end])
                return (line[:idx], count)

            if not (ord(b'0') <= char_value <= ord(b'9')):
                # not a digit
                break

            # Give up if we have already gone back more than 20 characters
            if end - idx > 20:
                break

        return (line, None)
