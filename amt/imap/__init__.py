#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import logging
import random
import socket

from .. import ssl_util

from .err import ImapError, ParseError
from .cmd_splitter import CommandSplitter
from .parse import *

IMAP_PORT = 143
IMAPS_PORT = 993

STATE_NOT_AUTHENTICATED = 'not auth'
STATE_AUTHENTICATED = 'auth'
STATE_READ_ONLY = 'selected read-only'
STATE_READ_WRITE = 'selected read-write'
STATE_LOGOUT = 'logout'


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


class MailboxInfo:
    def __init__(self, name):
        self.name = name
        self.state = None
        self.uidvalidity = None
        self.flags = None
        self.permanent_flags = None

        self.num_exists = None
        self.num_recent = None

    def change_state(self, state):
        self.state = state

    def on_flags(self, flags):
        self.flags = flags

    def on_permanent_flags(self, flags):
        self.permanent_flags = flags

    def on_uidvalidity(self, uidvalidity):
        self.uidvalidity = uidvalidity

    def on_uidnext(self, uidnext):
        # We currently don't store this
        pass

    def on_unseen(self, msg_seq):
        # We currently don't store this
        pass

    def on_highest_mod_seq(self, mod_seq):
        # We currently don't store this
        pass

    def on_exists(self, num_msgs):
        self.num_exists = num_msgs

    def on_recent(self, num_msgs):
        self.num_recent = num_msgs

    def on_expunge(self, msg_seq):
        self.num_exists -= 1
        # Reset num_recent to None, since we don't really know if
        # the expunged message was recent or not.
        self.num_recent = None


class Connection:
    def __init__(self, server, port=None, timeout=60, ssl=True):
        self._responses = []
        self._parser = ResponseStream(self._on_response)

        self._server_capabilities = None
        self.mailbox_info = None

        tag_prefix = ''.join(random.sample('ABCDEFGHIJKLMNOP', 4))
        self._tag_prefix = bytes(tag_prefix, 'ASCII')
        self._next_tag = 1

        self._connect(server, port, timeout, ssl)

    def _connect(self, server, port, timeout, ssl):
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

        # Receive the server greeting
        resp = self.get_response()
        if resp.resp_type == b'OK':
            self.change_state(STATE_NOT_AUTHENTICATED)
        elif resp.resp_type == b'PREAUTH':
            self.change_state(STATE_AUTHENTICATED)
        elif resp.resp_type == b'BYE':
            raise ImapError('server responded with BYE greeting')
        else:
            raise ImapError('server responded with unexpected greeting: %r',
                            resp)

    def get_capabilities(self):
        if self._server_capabilities is None:
            # FIXME: send CAPABILITY command
            raise NotImplementedError()
        return self._server_capabilities

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
        if hasattr(response, 'code') and response.code is not None:
            self.process_response_code(response)

        if response.resp_type == b'CAPABILITY':
            self._server_capabilities = response.capabilities
        elif response.resp_type == b'FLAGS':
            self.mailbox_info.on_flags(response.flags)
        elif response.resp_type == b'EXISTS':
            self.mailbox_info.on_exists(response.number)
        elif response.resp_type == b'RECENT':
            self.mailbox_info.on_recent(response.number)
        elif response.resp_type == b'EXPUNGE':
            self.mailbox_info.on_expunge(response.number)
        elif response.resp_type in (b'OK', b'NO', b'BAD'):
            # self.process_response_code() will have processed the code
            pass
        elif response.tag == b'*':
            logging.debug('unhandled untagged response: %r',
                          response.resp_type)

    def process_response_code(self, response):
        code = response.code
        if code.token == b'CAPABILITY':
            self._server_capabilities = code.data
        elif code.token == b'ALERT':
            logging.warning(response.text)
        elif code.token == b'READ-ONLY':
            self.change_state(STATE_READ_ONLY)
            self.mailbox_info.change_state(STATE_READ_ONLY)
        elif code.token == b'READ-WRITE':
            self.change_state(STATE_READ_WRITE)
            self.mailbox_info.change_state(STATE_READ_WRITE)
        elif code.token == b'UIDVALIDITY':
            self.mailbox_info.on_uidvalidity(code.data)
        elif code.token == b'UIDNEXT':
            self.mailbox_info.on_uidnext(code.data)
        elif code.token == b'UNSEEN':
            self.mailbox_info.on_unseen(code.data)
        elif code.token == b'HIGHESTMODSEQ':
            self.mailbox_info.on_highest_mod_seq(code.data)
        elif code.token == b'PERMANENTFLAGS':
            self.mailbox_info.on_permanent_flags(code.data)
        else:
            logging.debug('unhandled response code: %r' % (code.token,))

    def change_state(self, new_state):
        logging.debug('connection state change: %s', new_state)
        self.state = new_state

    def _on_response(self, response):
        self._responses.append(response)

    def login(self, user, password):
        if isinstance(user, str):
            user = user.encode('ASCII')
        if isinstance(password, str):
            password = password.encode('ASCII')

        tag = self.send_request(b'LOGIN', self.to_astring(user),
                                self.to_astring(password),
                                suppress_log=True)
        self.wait_for_response(tag)

    def select_mailbox(self, mailbox, readonly=False):
        if self.mailbox_info is not None:
            raise ImapError('cannot select a new mailbox with '
                            'one already selected')
        self.mailbox_info = MailboxInfo(mailbox)

        if readonly:
            cmd = b'EXAMINE'
        else:
            cmd = b'SELECT'

        if isinstance(mailbox, str):
            # RFC 3501 states mailbox names should be 7-bit only
            mailbox = mailbox.encode('ASCII', errors='strict')

        mailbox_name = self.to_astring(mailbox)
        tag = self.send_request(cmd, mailbox_name)
        self.wait_for_response(tag)

        if self.state not in (STATE_READ_ONLY, STATE_READ_WRITE):
            raise ImapError('unexpected state after %s command', cmd)

    def send_request(self, command, *args, suppress_log=False):
        tag = self.get_new_tag()

        msg = b' '.join((tag, command) + args)
        if suppress_log:
            logging.debug('sending:  %r <args suppressed>', command)
        else:
            logging.debug('sending:  %r', msg)
        self.sock.sendall(msg + b'\r\n')
        return tag

    def get_new_tag(self):
        tag = self._tag_prefix + bytes(str(self._next_tag), 'ASCII')
        self._next_tag += 1
        return tag

    def to_astring(self, value):
        if len(value) > 256:
            return to_literal(value)

        # TODO: We could just return the value itself if it doesn't contain
        # any atom-specials.
        return self.to_quoted(value)

    def to_literal(self, value):
        prefix = b'{' + bytes(str(len(value)), 'ASCII') + b'}\r\n'
        return prefix + value

    def to_quoted(self, value):
        escaped = value.replace(b'\\', b'\\\\').replace(b'"', b'\\"')
        return b'"' + escaped + b'"'
