#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import logging
import random
import socket

from .. import ssl_util

from .err import ImapError
from .cmd_splitter import CommandSplitter
from .constants import IMAP_PORT, IMAPS_PORT
from .parse import parse_response


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
        if not isinstance(token, (bytes, bytearray)):
            token = token.encode('ASCII', errors='strict')

        return self.handlers.get(token, [])

    def register(self, token, handler):
        if not isinstance(token, (bytes, bytearray)):
            token = token.encode('ASCII', errors='strict')

        token_handlers = self.handlers.setdefault(token, [])
        token_handlers.append(handler)

    def unregister(self, token, handler):
        if not isinstance(token, (bytes, bytearray)):
            token = token.encode('ASCII', errors='strict')

        token_handlers = self.handlers.get(token)
        if not token_handlers:
            raise KeyError('no handler registered for %s' % token)

        for idx, registered_handler in enumerate(token_handlers):
            if registered_handler == handler:
                del token_handlers[idx]
                return

        raise KeyError('unable to find specified handler for %s' % token)


class ConnectionCore:
    '''
    Very basic functionality for an IMAP connection.

    Supports sending requests, receiving responses, and managing handlers for
    untagged responses.
    '''
    def __init__(self, server, port=None, timeout=60, ssl=True):
        self._responses = []
        self._parser = ResponseStream(self._on_response)

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

    def _on_response(self, response):
        self._responses.append(response)

    def get_new_tag(self):
        tag = self._tag_prefix + bytes(str(self._next_tag), 'ASCII')
        self._next_tag += 1
        return tag

    def run_cmd(self, command, *args, suppress_log=False):
        tag = self.send_request(command, *args, suppress_log=suppress_log)
        self.wait_for_response(tag)

    def send_request(self, command, *args, suppress_log=False):
        tag = self.get_new_tag()

        msg = b' '.join((tag, command) + args)
        if suppress_log:
            logging.debug('sending:  %r <args suppressed>', command)
        else:
            logging.debug('sending:  %r', msg)
        self.sock.sendall(msg + b'\r\n')
        return tag

    def get_response(self):
        while not self._responses:
            data = self.sock.recv(4096)
            self._parser.feed(data)

        resp = self._responses.pop(0)
        self.process_response(resp)
        return resp

    def wait_for_response(self, tag):
        while True:
            resp = self.get_response()
            if resp.tag == b'*':
                continue

            if resp.tag == tag:
                break

            raise ImapError('unexpected response tag: %s', resp)

        if resp.resp_type != b'OK':
            raise ImapError('command failed: %s %s',
                            resp.resp_type, resp.text)

    def process_response(self, response):
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

    def untagged_handler(self, resp_type):
        return ResponseHandlerCtx(self, resp_type)

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
        prefix = b'{' + bytes(str(len(value)), 'ASCII') + b'}\r\n'
        return prefix + value

    def to_quoted(self, value):
        escaped = value.replace(b'\\', b'\\\\').replace(b'"', b'\\"')
        return b'"' + escaped + b'"'

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
    def __init__(self, conn, resp_type):
        self.conn = conn
        self.resp_type = resp_type
        self.responses = []

    def __enter__(self):
        self.conn.register_handler(self.resp_type, self.on_response)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.conn.unregister_handler(self.resp_type, self.on_response)

    def on_response(self, response):
        self.responses.append(response)

    def get_exactly_one(self):
        if not self.responses:
            raise ImapError('no %s response received', self.resp_type)
        if len(self.responses) != 1:
            raise ImapError('received %d %s responses, expected only 1',
                            len(self.responses), self.resp_type)
        return self.responses[0]
