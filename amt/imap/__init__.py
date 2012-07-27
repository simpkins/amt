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

    def on_flags(self, response):
        self.flags = response.flags

    def on_permanent_flags(self, response):
        self.permanent_flags = response.code.data

    def on_uidvalidity(self, response):
        self.uidvalidity = response.code.data

    def on_uidnext(self, response):
        # We currently don't store this
        # uid = response.code.data
        pass

    def on_unseen(self, response):
        # We currently don't store this
        # msg_seq = response.code.data
        pass

    def on_highest_mod_seq(self, response):
        # We currently don't store this
        # mod_seq = response.code.data
        pass

    def on_exists(self, response):
        self.num_exists = response.number

    def on_recent(self, response):
        self.num_recent = response.number

    def on_expunge(self, response):
        self.num_exists -= 1
        # Reset num_recent to None, since we don't really know if
        # the expunged message was recent or not.
        self.num_recent = None


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


class Connection(ConnectionCore):
    def __init__(self, server, port=None, timeout=60, ssl=True):
        super().__init__(server=server, port=port, timeout=timeout, ssl=ssl)

        self._server_capabilities = None
        self.mailbox_info = None

        self.register_handler('CAPABILITY', self._on_capabilities)
        self.register_code_handler('CAPABILITY', self._on_capabilities_code)
        self.register_code_handler('ALERT', self._on_alert_code)

        self._connect(server, port, timeout, ssl)

    def _connect(self, server, port, timeout, ssl):
        self._connect_sock(server, port, timeout, ssl)

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
            self.run_cmd(b'CAPABILITY')
            if self._server_capabilities is None:
                raise ImapError('server did not send a CAPABILITY response')
        return self._server_capabilities

    def _on_capabilities(self, response):
        self._server_capabilities = response.capabilities

    def _on_capabilities_code(self, response):
        self._server_capabilities = response.code.data

    def _on_alert_code(self, response):
        logging.warning(response.text)

    def _on_read_only(self, response):
        self.change_state(STATE_READ_ONLY)
        self.mailbox_info.change_state(STATE_READ_ONLY)

    def _on_read_write(self, response):
        self.change_state(STATE_READ_WRITE)
        self.mailbox_info.change_state(STATE_READ_WRITE)

    def change_state(self, new_state):
        logging.debug('connection state change: %s', new_state)
        self.state = new_state

    def login(self, user, password):
        if isinstance(user, str):
            user = user.encode('ASCII')
        if isinstance(password, str):
            password = password.encode('ASCII')

        self.run_cmd(b'LOGIN', self.to_astring(user),
                     self.to_astring(password),
                     suppress_log=True)

    def select_mailbox(self, mailbox, readonly=False):
        if self.mailbox_info is not None:
            raise ImapError('cannot select a new mailbox with '
                            'one already selected')

        # Set self.mailbox_info, and register associated response handlers
        self.mailbox_info = MailboxInfo(mailbox)
        self.register_handler('FLAGS', self.mailbox_info.on_flags)
        self.register_handler('EXISTS', self.mailbox_info.on_exists)
        self.register_handler('RECENT', self.mailbox_info.on_recent)
        self.register_handler('EXPUNGE', self.mailbox_info.on_expunge)
        self.register_code_handler('READ-ONLY', self._on_read_only)
        self.register_code_handler('READ-WRITE', self._on_read_write)
        self.register_code_handler('UIDVALIDITY',
                                   self.mailbox_info.on_uidvalidity)
        self.register_code_handler('UIDNEXT', self.mailbox_info.on_uidnext)
        self.register_code_handler('UNSEEN', self.mailbox_info.on_unseen)
        self.register_code_handler('HIGHESTMODSEQ',
                                   self.mailbox_info.on_highest_mod_seq)
        self.register_code_handler('PERMANENTFLAGS',
                                   self.mailbox_info.on_permanent_flags)

        if readonly:
            cmd = b'EXAMINE'
        else:
            cmd = b'SELECT'

        if isinstance(mailbox, str):
            # RFC 3501 states mailbox names should be 7-bit only
            mailbox = mailbox.encode('ASCII', errors='strict')

        mailbox_name = self.to_astring(mailbox)
        self.run_cmd(cmd, mailbox_name)

        if self.state not in (STATE_READ_ONLY, STATE_READ_WRITE):
            raise ImapError('unexpected state after %s command', cmd)

    def search(self, criteria):
        with self.untagged_handler('SEARCH') as search_handler:
            self.run_cmd(b'SEARCH', criteria)
            search_response = search_handler.get_exactly_one()

        return search_response.msg_numbers

    def list(self, name, reference=None):
        return self._run_mailbox_list_cmd(b'LIST', name, reference)

    def lsub(self, name, reference=None):
        return self._run_mailbox_list_cmd(b'LSUB', name, reference)

    def _run_mailbox_list_cmd(self, cmd, name, reference):
        if reference is None:
            reference_arg = b'""'
        else:
            reference_arg = self.to_astring(reference)
        name_arg = self.to_astring(name)

        with self.untagged_handler(cmd) as list_handler:
            self.run_cmd(cmd, reference_arg, name_arg)

        return list_handler.responses

    def status(self, mailbox, attributes):
        if mailbox.upper() == b'INBOX':
            mailbox_arg = b'INBOX'
        else:
            mailbox_arg = self.to_astring(mailbox)
        attr_arg = b'(' + b' '.join(attributes) + b')'

        with self.untagged_handler('STATUS') as status_handler:
            self.run_cmd(b'STATUS', mailbox_arg, attr_arg)

        return status_handler.get_exactly_one()

    def fetch(self, msg_ids, attributes):
        msg_ids_arg = self._format_sequence_set(msg_ids)

        if isinstance(attributes, (list, tuple)):
            atts = []
            for att in attributes:
                if isinstance(att, str):
                    att = att.encode('ASCII', errors='strict')
                elif not isinstance(attributes, (bytes, bytearray)):
                    raise TypeError('expected string or bytes')
                atts.append(att)
            attributes_arg = b'(' + b' '.join(atts) + b')'
        elif isinstance(attributes, str):
            attributes_arg = attributes.encode('ASCII', errors='strict')
        elif isinstance(attributes, (bytes, bytearray)):
            attributes_arg = attributes

        # Send the request and get the responses
        with self.untagged_handler('FETCH') as fetch_handler:
            self.run_cmd(b'FETCH', msg_ids_arg, attributes_arg)

        # Turn the responses in to a dictionary mapping
        # the message number to the message attributes
        response_dict = {}
        for resp in fetch_handler.responses:
            response_dict[resp.number] = resp.attributes

        return response_dict

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

    def untagged_handler(self, resp_type):
        return ResponseHandlerCtx(self, resp_type)


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
