#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import errno
import fcntl
import logging
import os
import random
import select
import socket
import ssl
import threading
import time

from .. import ssl_util

from .err import *
from .cmd_splitter import CommandSplitter
from .constants import IMAP_PORT, IMAPS_PORT
from .parse import parse_response
from . import encode


class ResponseStream:
    '''
    ResponseStream accepts raw IMAP response data via the feed() method,
    and invokes a callback with the parsed responses.
    '''
    def __init__(self, callback, conn_id=None):
        self.splitter = CommandSplitter(self._on_cmd, conn_id)
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


_conn_id_lock = threading.Lock()
_next_conn_id = 1


def get_conn_id():
    global _conn_id_lock
    global _next_conn_id
    with _conn_id_lock:
        conn_id = _next_conn_id
        _next_conn_id += 1
        return conn_id


class ConnectionCore:
    '''
    Very basic functionality for an IMAP connection.

    Supports sending requests, receiving responses, and managing handlers for
    untagged responses.
    '''
    def __init__(self, server, port=None, timeout=None):
        self.sock = None
        self._interrupt_fds = None

        self._conn_id = get_conn_id()

        self._responses = []
        self._parser = ResponseStream(self._on_response, self._conn_id)
        self.default_response_timeout = timeout or 300
        self.response_progress_timeout = 60
        self.default_send_timeout = timeout or 60

        tag_prefix = ''.join(random.sample('ABCDEFGHIJKLMNOP', 4))
        self._tag_prefix = bytes(tag_prefix, 'ASCII')
        self._next_tag = 1

        # Handlers for untagged responses
        # _response_handlers is indexed by the response type
        self._response_handlers = HandlerDict()
        # _response_code_handlers is indexed by the response code token
        self._response_code_handlers = HandlerDict()

    def _connect_sock(self, server, port, timeout, use_ssl):
        if port is None:
            if use_ssl:
                port = IMAPS_PORT
            else:
                port = IMAP_PORT

        self.raw_sock = socket.create_connection((server, port),
                                                 timeout=timeout)
        if use_ssl:
            ctx = ssl_util.new_ctx()
            self.sock = ctx.wrap_socket(self.raw_sock)
        else:
            self.sock = self.raw_sock

        # Put the socket in non-blocking mode once we have established
        # the connection.
        self.sock.setblocking(False)

        self._init_interrupt()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.close()

    def __del__(self):
        # Call close() when the object is destroyed, just in case it wasn't
        # called previously.  (It is a no-op if it was already invoked.)
        #
        # This makes sure we don't leak the self._interrupt_fds file
        # descriptors.
        self.close()

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        if self._interrupt_fds is not None:
            os.close(self._interrupt_fds[0])
            os.close(self._interrupt_fds[1])
            self._interrupt_fds = None

    def _on_response(self, response):
        self._responses.append(response)

    def get_new_tag(self):
        tag = self._tag_prefix + bytes(str(self._next_tag), 'ASCII')
        self._next_tag += 1
        return tag

    def run_cmd(self, command, *args, suppress_log=False, timeout=None):
        tag = self.send_request(command, *args, suppress_log=suppress_log)
        self.wait_for_response(tag, timeout=timeout)

    def has_nonsynch_literals(self):
        # has_nonsynch_literals() should normally be overridden by
        # subclasses that can determine if LITERAL+ is listed in the server's
        # capabilities.
        return False

    def send_request(self, command, *args, suppress_log=False):
        tag = self.get_new_tag()
        args = (tag, command) + args

        if suppress_log:
            self.debug('sending:  %r <args suppressed>', command)

        parts = []
        cur_part = []
        for arg in args:
            cur_part.append(arg)
            if isinstance(arg, encode.Literal):
                parts.append(cur_part)
                cur_part = []
        parts.append(cur_part)

        if len(parts) > 1:
            nonsynch = self.has_nonsynch_literals()

        for part in parts[:-1]:
            literal = part[-1]

            len_str = str(len(literal.data)).encode('ASCII')
            if nonsynch:
                part[-1] = b'{' + len_str + b'+}'
            else:
                part[-1] = b'{' + len_str + b'}'

            data = b' '.join(part)
            if not suppress_log:
                self.debug('sending:  %r', data)
            self._sendall(data + b'\r\n')

            if not nonsynch:
                self.wait_for_response(b'+')

            if not suppress_log:
                self.debug('sending %d bytes', len(literal.data))
            self._sendall(literal.data)

        part = parts[-1]
        data = b' '.join(part)
        if not suppress_log:
            self.debug('sending:  %r', data)
        self._sendall(data + b'\r\n')

        return tag

    def send_line(self, data, timeout=None):
        self.debug('sending:  %r', data)
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
        recv_buf_size = 64 * 1024
        while not self._responses:
            self._wait_for_recv_ready(end_time)
            try:
                data = self.sock.recv(recv_buf_size)
            except ssl.SSLWantReadError as ex:
                continue
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

        # The end_time argument specifies how long we will wait for the entire
        # response.  This may be a very large timeout to accommodate slowly
        # downloading large messages.
        #
        # We also add a shorter timeout on how long we will wait to make
        # forward progress.  This prevents us from waiting for the full
        # response timeout if we stop receiving data entirely.
        progress_end_time = time.time() + self.response_progress_timeout
        poll_end_time = max(progress_end_time, end_time)

        # No data buffered ready to process, we have to wait for the socket
        # to become readable.
        self._wait_for_sock_ready(select.POLLIN | select.POLLPRI,
                                  poll_end_time, 'socket to become readable')

    def _wait_for_send_ready(self, end_time):
        self._wait_for_sock_ready(select.POLLOUT, end_time,
                                  'socket to become writable')

    def _wait_for_sock_ready(self, events, end_time, msg):

        # Before we sleep waiting on events, check to see if someone
        # has already requested that we wake up.
        self._check_for_recv_interrupt()

        p = select.poll()
        p.register(self.sock.fileno(), events)
        p.register(self._interrupt_fds[0], select.POLLIN)

        while True:
            # Figure out how long we can wait
            time_left = end_time - time.time()
            if time_left < 0:
                raise TimeoutError('timed out waiting on %s', msg)
            time_left_ms = time_left * 1000

            ret = p.poll(time_left_ms)

            ready = set(fd for fd, ready_events in ret)
            if self.sock.fileno() in ready:
                # We are ready
                self._clear_recv_interrupt()
                return

            if self._interrupt_fds[0] in ready:
                self._check_for_recv_interrupt()
                continue

            # If we are still here, nothing is ready, which means
            # we must have timed out
            raise TimeoutError('timed out waiting on %s', msg)

    def interrupt_waiting(self):
        self._recv_interrupt.set()
        os.write(self._interrupt_fds[1], b'x')

    def _clear_recv_interrupt_pipe(self):
        # Read all notification events of the _interrupt_fds pipe
        try:
            os.read(self._interrupt_fds[0], 1024)
        except (IOError, OSError) as ex:
            if ex.errno != errno.EAGAIN:
                raise

    def _check_for_recv_interrupt(self):
        self._clear_recv_interrupt_pipe()
        if self._recv_interrupt.is_set():
            self._recv_interrupt.clear()
            raise ReadInterruptedError('read explicitly interrupted')

    def _clear_recv_interrupt(self):
        self._clear_recv_interrupt_pipe()
        self._recv_interrupt.clear()

    def _init_interrupt(self):
        self._recv_interrupt = threading.Event()
        self._interrupt_fds = os.pipe()

        for fd in self._interrupt_fds:
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

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
                self.debug('unexpected continuation response')
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
            self.debug('unhandled untagged response: %r',
                       response.resp_type)

    def process_response_code(self, response):
        token = response.code.token
        handlers = self._response_code_handlers.get_handlers(token)
        handled = bool(handlers)
        for handler in handlers:
            handler(response)

        if not handled:
            self.debug('unhandled response code: %r' % (token,))

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

    def debug(self, msg, *args):
        if args:
            msg = msg % args
        logging.debug('conn %d: %s', self._conn_id, msg)


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
