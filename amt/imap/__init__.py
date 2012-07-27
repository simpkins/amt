#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import logging

from .. import message

from .err import ImapError, TimeoutError
from .conn_core import ConnectionCore
from .constants import IMAP_PORT, IMAPS_PORT

FLAG_SEEN = r'\Seen'
FLAG_ANSWERED = r'\Answered'
FLAG_FLAGGED = r'\Flagged'
FLAG_DELETED = r'\Deleted'
FLAG_DRAFT =  r'\Draft'
FLAG_RECENT =  r'\Recent'

STATE_NOT_AUTHENTICATED = 'not auth'
STATE_AUTHENTICATED = 'auth'
STATE_READ_ONLY = 'selected read-only'
STATE_READ_WRITE = 'selected read-write'
STATE_LOGOUT = 'logout'


class MailboxInfo:
    def __init__(self, name):
        self.name = name
        self.state = None
        self.uidvalidity = None
        self.flags = None
        self.permanent_flags = None

        self.num_messages = None
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
        self.num_messages = response.number

    def on_recent(self, response):
        self.num_recent = response.number

    def on_expunge(self, response):
        self.num_messages -= 1
        # Reset num_recent to None, since we don't really know if
        # the expunged message was recent or not.
        self.num_recent = None


class Connection(ConnectionCore):
    def __init__(self, server, port=None, timeout=60, ssl=True):
        super().__init__(server=server, port=port, timeout=timeout, ssl=ssl)

        self._server_capabilities = None
        self.mailbox = None

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
        self.mailbox.change_state(STATE_READ_ONLY)

    def _on_read_write(self, response):
        self.change_state(STATE_READ_WRITE)
        self.mailbox.change_state(STATE_READ_WRITE)

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
        if self.mailbox is not None:
            raise ImapError('cannot select a new mailbox with '
                            'one already selected')

        # Set self.mailbox, and register associated response handlers
        self.mailbox = MailboxInfo(mailbox)
        self.register_handler('FLAGS', self.mailbox.on_flags)
        self.register_handler('EXISTS', self.mailbox.on_exists)
        self.register_handler('RECENT', self.mailbox.on_recent)
        self.register_handler('EXPUNGE', self.mailbox.on_expunge)
        self.register_code_handler('READ-ONLY', self._on_read_only)
        self.register_code_handler('READ-WRITE', self._on_read_write)
        self.register_code_handler('UIDVALIDITY', self.mailbox.on_uidvalidity)
        self.register_code_handler('UIDNEXT', self.mailbox.on_uidnext)
        self.register_code_handler('UNSEEN', self.mailbox.on_unseen)
        self.register_code_handler('HIGHESTMODSEQ',
                                   self.mailbox.on_highest_mod_seq)
        self.register_code_handler('PERMANENTFLAGS',
                                   self.mailbox.on_permanent_flags)

        if readonly:
            cmd = b'EXAMINE'
        else:
            cmd = b'SELECT'

        if isinstance(mailbox, str):
            # RFC 3501 states mailbox names should be 7-bit only
            mailbox = mailbox.encode('ASCII', errors='strict')

        mailbox_name = self.to_astring(mailbox)
        self.run_cmd(cmd, mailbox_name)

        # The OK response should have included a READ-ONLY or READ-WRITE code.
        if self.state not in (STATE_READ_ONLY, STATE_READ_WRITE):
            raise ImapError('unexpected state after %s command', cmd)

        # Untagged EXISTS, RECENT, and FLAGS responses must have
        # also been received.
        if self.mailbox.num_messages is None:
            raise ImapError('server did not send an EXISTS response '
                            'in response to a %s command', cmd)
        if self.mailbox.num_recent is None:
            raise ImapError('server did not send a RECENT response '
                            'in response to a %s command', cmd)
        if self.mailbox.flags is None:
            raise ImapError('server did not send a FLAGS response '
                            'in response to a %s command', cmd)

        return self.mailbox

    def search(self, criteria):
        return self._run_search(b'SEARCH', criteria)

    def uid_search(self, criteria):
        return self._run_search(b'UID SEARCH', criteria)

    def _run_search(self, cmd, criteria):
        with self.untagged_handler('SEARCH') as search_handler:
            self.run_cmd(cmd, criteria)
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
        responses = self._run_fetch(b'FETCH', msg_ids, attributes)

        return dict((resp.number, resp.attributes) for resp in resposes)

    def fetch_one(self, msg_id, attributes):
        assert not isinstance(msg_id, (list, tuple))
        responses = self._run_fetch(b'FETCH', msg_id, attributes)
        assert len(responses) == 1
        return responses[0].attributes

    def uid_fetch(self, msg_ids, attributes, index_by_uid=True):
        responses = self._run_fetch(b'UID FETCH', msg_ids, attributes)

        if index_by_uid:
            # RFC 3501 says that the server must implicitly include the UID
            # attribute in the response even if it wasn't explicitly included
            # in the request
            return dict((resp.attributes[b'UID'], resp.attributes)
                        for resp in resposes)
        else:
            return dict((resp.number, resp.attributes) for resp in resposes)

    def uid_fetch_one(self, msg_id, attributes):
        assert not isinstance(msg_id, (list, tuple))
        responses = self._run_fetch(b'UID FETCH', msg_id, attributes)
        assert len(responses) == 1
        return responses[0].attributes

    def _run_fetch(self, cmd, msg_ids, attributes):
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
            self.run_cmd(cmd, msg_ids_arg, attributes_arg)

        return fetch_handler.responses

    def fetch_msg(self, msg_id):
        desired_attrs = ['UID', 'FLAGS', 'INTERNALDATE', 'BODY.PEEK[]']
        attrs = self.fetch_one(msg_id, desired_attrs)
        return fetch_response_to_msg(attrs)

    def uid_fetch_msg(self, msg_id):
        desired_attrs = ['UID', 'FLAGS', 'INTERNALDATE', 'BODY.PEEK[]']
        attrs = self.uid_fetch_one(msg_id, desired_attrs)
        return fetch_response_to_msg(attrs)

    def noop(self):
        self.run_cmd(b'NOOP')

    def idle(self, timeout=29*60):
        if b'IDLE' not in self.get_capabilities():
            raise ImapError('server does not support the IDLE extension')

        try:
            self._idling = True
            tag = self.send_request(b'IDLE')
            self.wait_for_continuation_response()
            try:
                self.wait_for_response(tag, timeout=timeout)
            except TimeoutError:
                self.send_line(b'DONE')
                self.wait_for_response(tag)
        finally:
            self._idling = False

    def stop_idle(self):
        if not self._idling:
            raise ImapError('attempted to stop IDLE when no IDLE command '
                            'in progress')
        self.send_line(b'DONE')


def fetch_response_to_msg(response):
    '''
    Create a new Message from an IMAP FETCH response that includes at
    least BODY[], INTERNALDATE, and FLAGS fields.
    '''
    body = response[b'BODY[]']
    timestamp = response[b'INTERNALDATE']
    imap_flags = response[b'FLAGS']

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
