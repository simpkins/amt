#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import datetime
import errno
import logging
import random
import select
import socket
import time

from .. import ssl_util

from .err import *
from .cmd_splitter import CommandSplitter
from .constants import IMAP_PORT, IMAPS_PORT
from .parse import parse_response, _MONTHS_BY_NUM


class Literal:
    def __init__(self, data):
        if not isinstance(data, (bytes, bytearray)):
            raise ImapError('literal data must be bytes')
        self.data = data

    def __str__(self):
        # throw, to catch the error if anyone ever accidentally
        # tries simple string conversion on a Literal object
        raise ImapError('attempted string conversion on a Literal')


class ResponseStream:
    '''
    ResponseStream accepts raw IMAP response data via the feed() method,
    and invokes a callback with the parsed responses.
    '''
    def __init__(self, callback):
        self.splitter = CommandSplitter(self._on_cmd)
        self.callback = callback

    def feed(self, data):
        self.splitter.feed(data)

    def eof(self):
        self.splitter.eof()

    def _on_cmd(self, parts):
        resp = parse_response(parts)
        self.callback(resp)


class HandlerDict:
    def __init__(self):
        self.handlers = {}

    def get_handlers(self, token):
        token = self._canonical_token(token)

        handlers = []
        # Get the handlers for this token
        handlers.extend(self.handlers.get(token, []))
        # Also get the wildcard handlers
        handlers.extend(self.handlers.get(None, []))
        return handlers

    def register(self, token, handler):
        token = self._canonical_token(token)
        token_handlers = self.handlers.setdefault(token, [])
        token_handlers.append(handler)

    def unregister(self, token, handler):
        token = self._canonical_token(token)
        token_handlers = self.handlers.get(token)
        if not token_handlers:
            raise KeyError('no handler registered for %s' % token)

        for idx, registered_handler in enumerate(token_handlers):
            if registered_handler == handler:
                del token_handlers[idx]
                return

        raise KeyError('unable to find specified handler for %s' % token)

    def _canonical_token(self, token):
        if isinstance(token, str):
            return token.encode('ASCII', errors='strict')
        return token


class ConnectionCore:
    '''
    Very basic functionality for an IMAP connection.

    Supports sending requests, receiving responses, and managing handlers for
    untagged responses.
    '''
    def __init__(self, server, port=None, timeout=60, ssl=True):
        self._responses = []
        self._parser = ResponseStream(self._on_response)
        self.default_response_timeout = timeout
        self.default_send_timeout = timeout

        tag_prefix = ''.join(random.sample('ABCDEFGHIJKLMNOP', 4))
        self._tag_prefix = bytes(tag_prefix, 'ASCII')
        self._next_tag = 1

        # Handlers for untagged responses
        # _response_handlers is indexed by the response type
        self._response_handlers = HandlerDict()
        # _response_code_handlers is indexed by the response code token
        self._response_code_handlers = HandlerDict()

    def _connect_sock(self, server, port, timeout, ssl):
        if port is None:
            if ssl:
                port = IMAPS_PORT
            else:
                port = IMAP_PORT

        self.raw_sock = socket.create_connection((server, port),
                                                 timeout=timeout)
        if ssl:
            ctx = ssl_util.new_ctx()
            self.sock = ctx.wrap_socket(self.raw_sock)
        else:
            self.sock = self.raw_sock

        # Put the socket in non-blocking mode once we have established
        # the connection.
        self.sock.setblocking(False)

    def close(self):
        self.sock.close()

    def _on_response(self, response):
        self._responses.append(response)

    def get_new_tag(self):
        tag = self._tag_prefix + bytes(str(self._next_tag), 'ASCII')
        self._next_tag += 1
        return tag

    def run_cmd(self, command, *args, suppress_log=False):
        tag = self.send_request(command, *args, suppress_log=suppress_log)
        self.wait_for_response(tag)

    def has_nonsynch_literals(self):
        return b'LITERAL+' in self.get_capabilities()

    def send_request(self, command, *args, suppress_log=False):
        tag = self.get_new_tag()
        args = (tag, command) + args
        nonsynch = self.has_nonsynch_literals()

        if suppress_log:
            logging.debug('sending:  %r <args suppressed>', command)

        parts = []
        cur_part = []
        for arg in args:
            cur_part.append(arg)
            if isinstance(arg, Literal):
                parts.append(cur_part)
                cur_part = []
        parts.append(cur_part)

        for part in parts[:-1]:
            literal = part[-1]

            len_str = str(len(literal.data)).encode('ASCII')
            if nonsynch:
                part[-1] = b'{' + len_str + b'+}'
            else:
                part[-1] = b'{' + len_str + b'}'

            data = b' '.join(part)
            if not suppress_log:
                logging.debug('sending:  %r', data)
            self._sendall(data + b'\r\n')

            if not nonsynch:
                self.wait_for_response(b'+')

            if not suppress_log:
                logging.debug('sending %d bytes', len(literal.data))
            self._sendall(literal.data)

        part = parts[-1]
        data = b' '.join(part)
        if not suppress_log:
            logging.debug('sending:  %r', data)
        self._sendall(data + b'\r\n')

        return tag

    def send_line(self, data, timeout=None):
        logging.debug('sending:  %r', data)
        self._sendall(data + b'\r\n')

    def _sendall(self, data, timeout=None):
        # We put the socket in non-blocking mode, so we need to implement
        # sendall() ourself.
        #
        # First try an optimistic send, without checking the socket for
        # writablity.
        bytes_sent = self.sock.send(data, 0)

        if timeout is None:
            timeout = self.default_send_timeout
        end_time = time.time() + timeout

        bytes_left = len(data) - bytes_sent
        while bytes_left > 0:
            # Wait for the socket to become writable
            self._wait_for_send_ready(end_time)
            bytes_sent = self.sock.send(data, 0)
            assert bytes_sent <= bytes_left
            bytes_left -= bytes_sent

    def get_response(self, timeout=None):
        if timeout is None:
            timeout = self.default_response_timeout
        end_time = time.time() + timeout
        return self._get_response(end_time)

    def _get_response(self, end_time):
        # We perform our own timeout handling.  The builtin socket code
        # will put the socket in an error state on a timeout, and we want to
        # still be able to re-use the socket after a timeout.  (We can
        # correctly resume even if a timeout occurs partway through a
        # response.)
        while not self._responses:
            self._wait_for_recv_ready(end_time)
            try:
                data = self.sock.recv(4096)
            except socket.error as ex:
                if ex.errno == errno.EAGAIN:
                    continue
                raise
            if not data:
                raise EOFError('got EOF while waiting on response')
            self._parser.feed(data)

        resp = self._responses.pop(0)
        self.process_response(resp)
        return resp

    def _wait_for_recv_ready(self, end_time):
        # SSL sockets have a pending() call to check and see if they
        # already have some data buffered waiting to be processed.
        if hasattr(self.sock, 'pending') and self.sock.pending():
            return

        # No data buffered ready to process, we have to wait for the socket
        # to become readable.
        self._wait_for_sock_ready(select.POLLIN | select.POLLPRI, end_time,
                                  'socket to become readable')

    def _wait_for_send_ready(self, end_time):
        self._wait_for_sock_ready(select.POLLOUT, end_time,
                                  'socket to become writable')

    def _wait_for_sock_ready(self, events, end_time, msg):
        # Figure out how long we can wait
        time_left = end_time - time.time()
        if time_left < 0:
            raise TimeoutError('timed out waiting on %s', msg)
        time_left_ms = time_left * 1000

        p = select.poll()
        p.register(self.sock.fileno(), events)
        ret = p.poll(time_left_ms)
        if not ret:
            raise TimeoutError('timed out waiting on %s', msg)


    def wait_for_response(self, tag, timeout=None):
        if timeout is None:
            timeout = self.default_response_timeout
        end_time = time.time() + timeout

        while True:
            resp = self._get_response(end_time)
            if resp.tag == b'*':
                continue

            if resp.tag == tag:
                break

            if resp.tag == b'+':
                logging.debug('unexpected continuation response')
                continue

            raise ImapError('unexpected response tag: %s', resp)

        if tag != b'+' and resp.resp_type != b'OK':
            raise CmdError(resp)

        return resp

    def process_response(self, response):
        if response.tag == b'+':
            # Continuation responses don't need any processing.
            # They will be handled by our caller.
            assert response.resp_type is None
            return

        handled = False
        if hasattr(response, 'code') and response.code is not None:
            ret = self.process_response_code(response)
            if ret:
                handled = True

        handlers = self._response_handlers.get_handlers(response.resp_type)
        if handlers:
            handled = True
        for handler in handlers:
            handler(response)

        if not handled and response.tag == b'*':
            logging.debug('unhandled untagged response: %r',
                          response.resp_type)

    def process_response_code(self, response):
        token = response.code.token
        handlers = self._response_code_handlers.get_handlers(token)
        handled = bool(handlers)
        for handler in handlers:
            handler(response)

        if not handled:
            logging.debug('unhandled response code: %r' % (token,))

        return handled

    def register_handler(self, resp_type, handler):
        self._response_handlers.register(resp_type, handler)

    def unregister_handler(self, resp_type, handler):
        self._response_handlers.unregister(resp_type, handler)

    def register_code_handler(self, token, handler):
        self._response_code_handlers.register(token, handler)

    def unregister_code_handler(self, token, handler):
        self._response_code_handlers.unregister(token, handler)

    def untagged_handler(self, resp_type, callback=None):
        return ResponseHandlerCtx(self, resp_type, callback)

    # TODO: Move the following functions to some encoding module
    # They don't really belong as part of the ConnectionCore class.

    def to_astring(self, value):
        # TODO: We could just return the value itself if it doesn't contain
        # any atom-specials.
        return self.to_string(value)

    def to_string(self, value):
        if len(value) > 256:
            return to_literal(value)

        return self.to_quoted(value)

    def to_literal(self, value):
        return Literal(value)

    def to_quoted(self, value):
        escaped = value.replace(b'\\', b'\\\\').replace(b'"', b'\\"')
        return b'"' + escaped + b'"'

    def to_date_time(self, timestamp):
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

    def _format_sequence_set(self, msg_ids):
        if isinstance(msg_ids, (list, tuple)):
            return b','.join(self._format_seq_range(r) for r in msg_ids)

        try:
            return self._format_seq_range(msg_ids)
        except TypeError:
            raise TypeError('expected a numeric message ID, '
                            'a string message range, or list of message '
                            'IDs/ranges, got %s: %r' %
                            (type(value).__name__, value))

    def _format_seq_range(self, value):
        if isinstance(value, int):
            return str(value).encode('ASCII', errors='strict')
        elif isinstance(value, str):
            return value.encode('ASCII', errors='strict')
        elif isinstance(value, (bytes, bytearray)):
            return value

        raise TypeError('expected a numeric message ID or a string '
                        'message range, got %s: %r' %
                        (type(value).__name__, value))


class ResponseHandlerCtx:
    def __init__(self, conn, resp_type, callback=None):
        self.conn = conn
        self.resp_type = resp_type
        self.responses = []
        self.callback = callback

    def __enter__(self):
        self.conn.register_handler(self.resp_type, self.on_response)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.conn.unregister_handler(self.resp_type, self.on_response)

    def on_response(self, response):
        self.responses.append(response)
        if self.callback is not None:
            self.callback(response)

    def get_exactly_one(self):
        if not self.responses:
            raise ImapError('no %s response received', self.resp_type)
        if len(self.responses) != 1:
            raise ImapError('received %d %s responses, expected only 1',
                            len(self.responses), self.resp_type)
        return self.responses[0]
