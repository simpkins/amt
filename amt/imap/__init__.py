#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import logging
import time

from .. import message

from .err import ImapError, ReadInterruptedError, TimeoutError
from .conn_core import ConnectionCore
from .constants import IMAP_PORT, IMAPS_PORT

FLAG_SEEN = br'\Seen'
FLAG_ANSWERED = br'\Answered'
FLAG_FLAGGED = br'\Flagged'
FLAG_DELETED = br'\Deleted'
FLAG_DRAFT =  br'\Draft'
FLAG_RECENT =  br'\Recent'

STATE_NOT_AUTHENTICATED = 'not auth'
STATE_AUTHENTICATED = 'auth'
STATE_READ_ONLY = 'selected read-only'
STATE_READ_WRITE = 'selected read-write'
STATE_LOGOUT = 'logout'


class Account:
    def __init__(self, server, user, port=None, ssl=None, password=None):
        """
        Create a new IMAP Account object.

        - If port and SSL are both None, they default to 993 and True.
        - If the port is specified and ssl is None, ssl defaults to False
          if the port is 143, and True in all other cases.
        - If ssl is specified and port is None, the port defaults to 143
          if ssl is disabled, and 993 if ssl is enabled.
        """
        if ssl is None:
            if port is None:
                ssl = True
                port = IMAPS_PORT
            elif port == IMAP_PORT:
                ssl = False
            else:
                ssl = True
        if port is None:
            if ssl:
                port = IMAPS_PORT
            else:
                port = IMAP_PORT

        self.server = server
        self.port = port
        self.ssl = ssl

        self.user = user
        self.password = password


class MailboxInfo:
    def __init__(self, conn, name):
        self.conn = conn
        self.name = name
        self.state = None
        self.uidvalidity = None
        self.flags = None
        self.permanent_flags = None

        self.num_messages = None
        self.num_recent = None

        self._register_handlers()

    def __str__(self):
        return 'Mailbox(%s): %d messages' % (self.name, self.num_messages)

    def change_state(self, state):
        self.state = state

    def on_read_only(self, response):
        self.change_state(STATE_READ_ONLY)
        self.conn.change_state(STATE_READ_ONLY)

    def on_read_write(self, response):
        self.change_state(STATE_READ_WRITE)
        self.conn.change_state(STATE_READ_WRITE)

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

    def _register_handlers(self):
        conn = self.conn
        conn.register_handler('FLAGS', self.on_flags)
        conn.register_handler('EXISTS', self.on_exists)
        conn.register_handler('RECENT', self.on_recent)
        conn.register_handler('EXPUNGE', self.on_expunge)
        conn.register_code_handler('READ-ONLY', self.on_read_only)
        conn.register_code_handler('READ-WRITE', self.on_read_write)
        conn.register_code_handler('UIDVALIDITY', self.on_uidvalidity)
        conn.register_code_handler('UIDNEXT', self.on_uidnext)
        conn.register_code_handler('UNSEEN', self.on_unseen)
        conn.register_code_handler('HIGHESTMODSEQ', self.on_highest_mod_seq)
        conn.register_code_handler('PERMANENTFLAGS', self.on_permanent_flags)

    def unregister_handlers(self):
        conn = self.conn
        conn.unregister_handler('FLAGS', self.on_flags)
        conn.unregister_handler('EXISTS', self.on_exists)
        conn.unregister_handler('RECENT', self.on_recent)
        conn.unregister_handler('EXPUNGE', self.on_expunge)
        conn.unregister_code_handler('READ-ONLY', self.on_read_only)
        conn.unregister_code_handler('READ-WRITE', self.on_read_write)
        conn.unregister_code_handler('UIDVALIDITY', self.on_uidvalidity)
        conn.unregister_code_handler('UIDNEXT', self.on_uidnext)
        conn.unregister_code_handler('UNSEEN', self.on_unseen)
        conn.unregister_code_handler('HIGHESTMODSEQ', self.on_highest_mod_seq)
        conn.unregister_code_handler('PERMANENTFLAGS', self.on_permanent_flags)


class Connection(ConnectionCore):
    def __init__(self, server, port=None, timeout=60, ssl=True):
        super().__init__(server=server, port=port, timeout=timeout)

        self._server_capabilities = None
        self._mailbox_delim = None
        self.mailbox = None

        self.register_handler('CAPABILITY', self._on_capabilities)
        self.register_code_handler('CAPABILITY', self._on_capabilities_code)
        self.register_code_handler('ALERT', self._on_alert_code)

        self._connect(server, port, timeout, ssl)

    def _connect(self, server, port, timeout, use_ssl):
        self._connect_sock(server, port, timeout=timeout, use_ssl=use_ssl)

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

    def has_nonsynch_literals(self):
        return b'LITERAL+' in self.get_capabilities()

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
        self.debug('connection state change: %s', new_state)
        self.state = new_state

    def login(self, user, password):
        if isinstance(user, str):
            user = user.encode('ASCII')
        if isinstance(password, str):
            password = password.encode('ASCII')

        self.run_cmd(b'LOGIN', self.to_astring(user),
                     self.to_astring(password),
                     suppress_log=True)

    def get_mailbox_delim(self):
        if self._mailbox_delim is None:
            responses = self.list_mailboxes('', '')
            raw_delim = responses[0].delimiter
            self._mailbox_delim = raw_delim.decode('ASCII', errors='strict')
        return self._mailbox_delim

    def select_mailbox(self, mailbox, readonly=False):
        if self.mailbox is not None:
            raise ImapError('cannot select a new mailbox with '
                            'one already selected')

        # Set self.mailbox, and register associated response handlers
        self.mailbox = MailboxInfo(self, mailbox)

        if readonly:
            cmd = b'EXAMINE'
        else:
            cmd = b'SELECT'

        mailbox_name = self._quote_mailbox_name(mailbox)
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

    def close_mailbox(self):
        if self.mailbox is None:
            raise ImapError('no mailbox open')

        self.run_cmd(b'CLOSE')
        self.mailbox.unregister_handlers()
        self.mailbox = None

    def create_mailbox(self, mailbox):
        self.run_cmd(b'CREATE', self._quote_mailbox_name(mailbox))

    def ensure_mailbox(self, mailbox):
        '''
        Ensure that the specified mailbox exists.

        If the mailbox already exists, does nothing.  Otherwise it creates the
        mailbox.
        '''
        # TODO: make sure the mailbox name does not contain any wildcards
        responses = self.list_mailboxes('', mailbox)
        for response in responses:
            if response.mailbox.decode('utf-8') == mailbox:
                # The mailbox already exists
                return
        self.create_mailbox(mailbox)

    def delete_mailbox(self, mailbox):
        self.run_cmd(b'DELETE', self._quote_mailbox_name(mailbox))

    def _quote_mailbox_name(self, mailbox):
        if isinstance(mailbox, str):
            # RFC 3501 states mailbox names should be 7-bit only
            mailbox = mailbox.encode('ASCII', errors='strict')

        return self.to_astring(mailbox)

    def search(self, *criteria):
        return self._run_search(b'SEARCH', criteria)

    def uid_search(self, *criteria):
        return self._run_search(b'UID SEARCH', criteria)

    def _run_search(self, cmd, criteria):
        with self.untagged_handler('SEARCH') as search_handler:
            self.run_cmd(cmd, *criteria)
            search_response = search_handler.get_exactly_one()

        return search_response.msg_numbers

    def list_mailboxes(self, reference, name):
        return self._run_mailbox_list_cmd(b'LIST', reference, name)

    def lsub(self, name, reference=''):
        return self._run_mailbox_list_cmd(b'LSUB', reference, name)

    def _run_mailbox_list_cmd(self, cmd, reference, pattern):
        reference_arg = self._quote_mailbox_name(reference)
        pattern_arg = self._quote_mailbox_name(pattern)

        with self.untagged_handler(cmd) as list_handler:
            self.run_cmd(cmd, reference_arg, pattern_arg)

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

        return dict((resp.number, resp.attributes) for resp in responses)

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
                        for resp in responses)
        else:
            return dict((resp.number, resp.attributes) for resp in responses)

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

    def delete_msg(self, msg_ids, expunge_now=False):
        self.add_flags(msg_ids, [FLAG_DELETED])
        if expunge_now:
            self.expunge()

    def uid_delete_msg(self, msg_ids, expunge_now=False):
        self.uid_add_flags(msg_ids, [FLAG_DELETED])
        if expunge_now:
            self.expunge()

    def copy(self, msg_ids, dest):
        msg_ids_arg = self._format_sequence_set(msg_ids)
        mbox_arg = self._quote_mailbox_name(dest)
        self.run_cmd(b'COPY', msg_ids_arg, mbox_arg)

    def uid_copy(self, msg_uids, dest):
        msg_uids_arg = self._format_sequence_set(msg_uids)
        self.run_cmd(b'UID COPY', msg_uids_arg, dest)

    def add_flags(self, msg_ids, flags):
        '''
        Add the specified flags to the specified message(s)
        '''
        self._update_flags(b'+FLAGS.SILENT', msg_ids, flags, use_uids=False)

    def uid_add_flags(self, msg_ids, flags):
        self._update_flags(b'+FLAGS.SILENT', msg_ids, flags, use_uids=True)

    def remove_flags(self, msg_ids, flags):
        '''
        Remove the specified flags from the specified message(s)
        '''
        self._update_flags(b'-FLAGS.SILENT', msg_ids, flags, use_uids=False)

    def uid_remove_flags(self, msg_ids, flags):
        self._update_flags(b'-FLAGS.SILENT', msg_ids, flags, use_uids=True)

    def replace_flags(self, msg_ids, flags):
        '''
        Replace the flags on the specified message(s) with the new list of
        flags.
        '''
        self._update_flags(b'FLAGS.SILENT', msg_ids, flags, use_uids=False)

    def uid_replace_flags(self, msg_ids, flags):
        self._update_flags(b'FLAGS.SILENT', msg_ids, flags, use_uids=True)

    def _update_flags(self, cmd, msg_ids, flags, use_uids=True):
        if isinstance(flags, (str, bytes, bytearray)):
            flags = [flags]
        encoded_flags = []
        for flag in flags:
            if isinstance(flags, str):
                flag = flag.encode('ASCII', errors='strict')
            encoded_flags.append(flag)

        flags_arg = b''.join([b'(', b' '.join(encoded_flags), b')'])

        msg_ids_arg = self._format_sequence_set(msg_ids)
        if use_uids:
            store_cmd = b'UID STORE'
        else:
            store_cmd = b'STORE'

        self.run_cmd(store_cmd, msg_ids_arg, cmd, flags_arg)

    def expunge(self):
        self.run_cmd(b'EXPUNGE')

    def append_msg(self, mailbox, msg):
        args = []
        args.append(self._quote_mailbox_name(mailbox))

        imap_flags = self.get_imap_flags(msg)
        imap_flags_str = b' '.join(imap_flags)
        if imap_flags_str:
            flags_arg = b'(' + imap_flags_str + b')'
            args.append(flags_arg)

        args.append(self.to_date_time(msg.datetime))
        args.append(self.to_literal(msg.to_bytes()))

        self.run_cmd(b'APPEND', *args)

    def get_imap_flags(self, msg):
        flags = set([FLAG_SEEN])

        for flag in msg.flags:
            if flag == message.Message.FLAG_NEW:
                flags.discard(FLAG_SEEN)
            elif flag == message.Message.FLAG_REPLIED_TO:
                flags.add(FLAG_ANSWERED)
            elif flag == message.Message.FLAG_FLAGGED:
                flags.add(FLAG_FLAGGED)
            elif flag == message.Message.FLAG_DELETED:
                flags.add(FLAG_DELETED)
            elif flag == message.Message.FLAG_DRAFT:
                flags.add(FLAG_DRAFT)

        for flag in msg.custom_flags:
            if isinstance(flag, str):
                flag = flag.encode('ascii', errors='strict')
            flags.add(flag)

        return flags

    def noop(self):
        self.run_cmd(b'NOOP')

    def idle(self, timeout=29*60):
        '''
        Send an IDLE command, and wait until the specified timeout expires,
        or until stop_idle() is called.

        If stop_idle() is not called before the timeout expires,
        idle() stops idling and returns normally.  It does not raise a
        TimeoutError.
        '''
        if b'IDLE' not in self.get_capabilities():
            raise ImapError('server does not support the IDLE extension')

        try:
            self._idling = True
            tag = self.send_request(b'IDLE')
            self.wait_for_response(b'+')
            try:
                self.wait_for_response(tag, timeout=timeout)
            except ReadInterruptedError:
                self.send_line(b'DONE')
                self.wait_for_response(tag)
            except TimeoutError:
                self.send_line(b'DONE')
                self.wait_for_response(tag)
        finally:
            self._idling = False

    def stop_idle_threadsafe(self):
        '''
        Stop a currently running idle() call.

        stop_idle_threadsafe() is safe to call from any thread.
        '''
        self.interrupt_waiting()

    def stop_idle(self):
        '''
        Stop a currently running idle() call.
        '''
        if not self._idling:
            raise ImapError('attempted to stop IDLE when no IDLE command '
                            'in progress')
        self.send_line(b'DONE')

    def wait_for_exists(self, timeout=None, poll_interval=30):
        '''
        Wait until we see a new EXISTS message from the server.

        This will wait using the IDLE command if the server supports the IDLE
        extension, otherwise it will poll using NOOP.

        Once an EXISTS response has been seen, wait_for_exists() will return.
        self.mailbox.num_messages will contain an accurate count of the number
        of messages currently in the mailbox.

        Note that there will not necessarily be any new messages after
        wait_for_exists() returns, and num_messages may even be 0.  An EXPUNGE
        response may have also been seen after the EXISTS response, but before
        wait_for_exists() returns.  Additionally, some servers (such as
        MS Exchange) send an unnecessary EXISTS response after every EXPUNGE,
        which will also trigger wait_for_exists() to return.
        '''
        # TODO: It would be nice to ignore EXISTS responses if the response
        # already matches the current number of messages.  This would allow
        # us to ignore the extraneous EXISTS responses from MS Exchange,
        # without waking up from the IDLE call.
        seen_exists = False
        def on_exists(response):
            nonlocal seen_exists
            if not seen_exists:
                self.stop_idle()
            seen_exists = True

        with self.untagged_handler('EXISTS', on_exists):
            # Note that calling self.get_capabilities() may send a command
            # which causes us to see an EXISTS response.
            caps = self.get_capabilities()
            if seen_exists:
                return

            if b'IDLE' not in caps:
                self.poll_for_new_message(timeout=timeout,
                                          poll_interval=poll_interval)
                return

            # TODO: This timeout argument doesn't behave like the timeout
            # argument for most other Connection methods.  Here, a timeout of
            # None really means no timeout, rather than use the default
            # timeout.
            if timeout is None:
                end_time = None
            else:
                end_time = time.time() + timeout

            MAX_IDLE_TIME = 29 * 60
            while not seen_exists:
                if end_time is not None:
                    time_left = end_time - time.time()
                    if time_left < 0:
                        raise TimeoutError('timed out waiting for new message')
                    idle_timeout = min(time_left, MAX_IDLE_TIME)
                else:
                    idle_timeout = MAX_IDLE_TIME
                self.idle(idle_timeout)

    def poll_for_exists(self, timeout=None, poll_interval=30):
        # TODO: This timeout argument doesn't behave like the timeout argument
        # for most other Connection methods.  Here, a timeout of None really
        # means no timeout, rather than use the default timeout.
        if timeout is None:
            end_time = None
        else:
            end_time = time.time() + timeout

        with self.untagged_handler('EXISTS') as exists_handler:
            while True:
                self.noop()
                if exists_handler.responses:
                    return

                if end_time is None:
                    poll_time = poll_interval
                else:
                    time_left = time.time() - end_time
                    if time_left < 0:
                        raise TimeoutError('timed out waiting for new message')
                    poll_time = min(poll_interval, time_left)

                time.sleep(poll_time)


def fetch_response_to_msg(response):
    '''
    Create a new Message from an IMAP FETCH response that includes at
    least BODY[], INTERNALDATE, and FLAGS fields.
    '''
    body = response[b'BODY[]']
    timestamp = response[b'INTERNALDATE']
    imap_flags = response[b'FLAGS']

    flags = set([message.Message.FLAG_NEW])
    custom_flags = set()
    for flag in imap_flags:
        # The imap \Seen flag tends to mean !new for most clients
        if flag == FLAG_SEEN:
            flags.discard(message.Message.FLAG_NEW)
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


def login(account, class_=Connection):
    conn = class_(account.server, account.port, ssl=account.ssl)
    conn.login(account.user, account.password)
    return conn
