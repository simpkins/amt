#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import logging
import time

from . import imap
from .getpassword import get_password
from .message import Message
from .maildir import Maildir

'''
The fetchmail code is divided into 2 main pieces:

    - Scanner:
      - enumerates the messages on the server
      - decides which messages need to be fetched
    - Processor:
      - processes each message
      - handles delivery to local mailboxes
'''

_log = logging.getLogger('amt.fetchmail')


class NoMoreMessagesError(Exception):
    def __init__(self):
        super(NoMoreMessagesError, self).__init__(self, 'no more messages')


class ProcessorError(Exception):
    def __init__(self, msg, ret=None):
        super(ProcessorError, self).__init__(self)
        self.msg = msg
        self.ret = ret

    def __str__(self):
        err_msg = 'processor failed while processing message'
        if self.ret is not None:
            err_msg += ': returned %r rather than True' % (self.ret,)
        return err_msg


class Processor:
    def process_msg(self, msg):
        '''
        process_msg() is invoked by a Scanner to process the current message.

        process_msg() must return True on success.  This informs the Scanner
        that the message has been processed successfully, and the Scanner can
        move on and process the next message.  (Note that some Scanners may
        delete the message from the server after a successful call to
        process_msg(), so process_msg() should only return True if the message
        has really been handled successfully.)
        '''
        raise NotImplementedError('process_msg() must be implemented by '
                                  'Processor subclasses')


class MaildirProcessor(Processor):
    def __init__(self, mailbox):
        if isinstance(mailbox, Maildir):
            self.mailbox = mailbox
        else:
            self.mailbox = Maildir(mailbox, create=True)

    def process_msg(self, msg):
        self.mailbox.add(msg)
        return True


class Scanner:
    '''
    Scanner classes enumerate the messages on the server, and decide which
    messages need to be fetched.  They pass the messages on to a processor to
    handle local delivery.

    The various scanner implementations implement different mechanisms of
    deciding which messages to fetch.  Some scanner classes may delete the
    messages or mark them read after they have been fetched.
    '''
    def __init__(self, account, mailbox, processor):
        self.account = account
        self.mailbox = mailbox
        self.processor = processor

        self.conn = None

    def open(self):
        self.conn = imap.login(self.account)
        self.conn.select_mailbox(self.mailbox, readonly=self.READONLY)
        self._post_open()

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def run_once(self):
        raise NotImplementedError('run_once() must be implemented by '
                                  'Scanner subclasses')

    def run_forever(self):
        raise NotImplementedError('run_forever() must be implemented by '
                                  'Scanner subclasses')

    READONLY = False


class SeqIDScanner(Scanner):
    def __init__(self, *args, **kwargs):
        if 'backup_mbox' in kwargs:
            self.backup_mbox = kwargs['backup_mbox']
            del kwargs['backup_mbox']
        else:
            self.backup_mbox = None

        super().__init__(*args, **kwargs)

    def _post_open(self):
        self.current_msg = None
        self.next_msg = 1
        self.conn.register_handler('EXPUNGE', self._on_expunge)

        if self.backup_mbox is not None:
            self.conn.ensure_mailbox(self.backup_mbox)

    def _on_expunge(self, response):
        if self.current_msg is not None:
            if response.number == self.current_msg:
                self.current_msg = None
            elif response.number < self.current_msg:
                self.current_msg -= 1

        if response.number < self.next_msg:
            self.next_msg -= 1

    def ensure_open(self):
        if self.conn is None:
            self.open()
            return

        # Send a NOOP to ensure we have an up-to-date message count
        self.conn.noop()

    def run_once(self):
        self.ensure_open()
        self._run_once()

    def _run_once(self):
        assert(self.next_msg <= self.conn.mailbox.num_messages + 1)
        num_available = self.conn.mailbox.num_messages + 1 - self.next_msg
        _log.debug('processing %d available messages', num_available)

        while True:
            try:
                self.process_next_msg()
            except NoMoreMessagesError:
                return

    def run_forever(self):
        self.last_connect = time.time()
        imap_err_count = 0

        while True:
            try:
                self.ensure_open()
                self._run_once()
                imap_err_count = 0
            except (IOError, imap.TimeoutError, imap.EOFError) as ex:
                _log.exception('I/O error: %s', ex)
                self._handle_conn_error()
                continue
            except imap.CmdError as ex:
                if self._is_fatal_error(ex):
                    raise

                # If we see too many failures in a row, give up rather than
                # continuing to hammer the IMAP server with errors.
                imap_err_count += 1
                if imap_err_count > 3:
                    raise

                # For all of these cases, just close and re-open the
                # connection.
                delay = (imap_err_count > 1)
                self._handle_conn_error(delay=delay)
                continue
            except imap.ImapError as ex:
                # For any other IMAP error, close and re-open the connection.
                # For instance, I have seen MS Exchange simple respond with
                # a line consisting of "Server Unavailable.", which causes
                # us to throw ImapError() stating "unexpected response tag"
                self._handle_conn_error(delay=True)
                continue


            try:
                _log.debug('waiting for new messages...')
                self.conn.wait_for_exists()
            except (IOError, imap.TimeoutError, imap.EOFError) as ex:
                # Expect I/O errors, timeouts, or the server closing the
                # connection.  Just log a message, reconnect, and continue.
                _log.exception('I/O error: %s', ex)
                self._handle_conn_error()
            except imap.ImapError as ex:
                # This happens sometimes if the server sends back
                # a bogus response.  For instance, Exchange sometimes
                # returns the line "Server Unavailable."
                # Log a warning and reconnect.
                _log.warning('unexpected IMAP error: %s')
                self._handle_conn_error()
            except Exception as ex:
                # Log all exceptions that occur.  If the error occurred
                # while we are waiting on more responses to be available,
                # simply log the exception and retry.
                _log.exception('unexpected exception: %s')
                self._handle_conn_error()

    def _is_fatal_error(self, ex):
        # Exchange occasionally returns "NO" errors in some cases.
        #
        # - If another client deletes a message while we are
        #   processing it.  We will fail trying to copy it to the
        #   backup folder or delete it in this case.  Exchange itself
        #   seems to auto-delete some calendar messages relatively
        #   quickly after they arrive.
        #
        # - I have seen some other intermittent failures, such as
        #   "COPY failed or partially completed".
        if ex.response.resp_type == b'NO':
            return False

        # I have also seen exchange return
        # ("BAD", "User is authenticated but not connected.")
        # when trying to select the mailbox.  It sounds like if the
        # Exchange server has auth issues sometimes it can return
        # successfully for the login command but then return this BAD
        # error when we actually try to select the mailbox.
        #
        # Treat this as non-fatal.  We'll tear down and re-create the
        # connection, and try logging in a second time.
        if (ex.response.resp_type == b'BAD' and
              ex.response.text == b'User is authenticated but not connected.'):
            return False

        return True

    def _handle_conn_error(self, delay=True):
        try:
            self.conn.close()
        except:
            pass
        self.conn = None

        if delay:
            # Only reconnect once every 30 seconds,
            # to avoid hammering the server in a loop if something
            # is going wrong.
            min_retry_time = self.last_connect + 30
            now = time.time()
            if now < min_retry_time:
                time.sleep(min_retry_time - now)
        self.last_connect = time.time()

    def process_next_msg(self):
        assert(self.next_msg <= self.conn.mailbox.num_messages + 1)
        if self.next_msg > self.conn.mailbox.num_messages:
            _log.debug('finished processing available messages')
            raise NoMoreMessagesError()

        _log.debug('processing message %d of %d',
                   self.next_msg, self.conn.mailbox.num_messages)

        self.current_msg = self.next_msg
        self.next_msg += 1

        msg = self.conn.fetch_msg(self.current_msg)
        if self.backup_mbox is not None:
            self.copy_msg(self.backup_mbox)
        self.invoke_processor(msg)

    def msg_successful(self):
        self.current_msg = None

    def msg_failed(self):
        self.current_msg = None

    def invoke_processor(self, msg):
        # TODO: implement some sort of retry functionality on error
        try:
            ret = self.processor.process_msg(msg)
        except Exception as ex:
            self.msg_failed()
            raise ProcessorError(msg) from ex
        if ret != True:
            self.msg_failed()
            raise ProcessorError(msg, ret)

        self.msg_successful()

    def copy_msg(self, dest):
        if self.current_msg is None:
            raise Exception('current message has already been deleted')
        self.conn.copy(self.current_msg, dest)


class FetchAllScanner(SeqIDScanner):
    '''
    - fetches all messages from the server
    - does not delete the messages
    - each time it is started, it re-fetches everything
    - could possibly communicate with the Processor to avoid having to fetch
      the full body if it is a duplicate
    - useful for one-time only fetch
    '''
    READONLY = True


class FetchAndDeleteScanner(SeqIDScanner):
    '''
    - fetches all messages from the server
    - deletes messages after fetching
    '''
    def msg_successful(self):
        if self.current_msg is not None:
            self.conn.delete_msg(self.current_msg, expunge_now=True)
        super().msg_successful()


class FetchFlagScanner(SeqIDScanner):
    '''
    - marks messages with a flag after they have been fetched
    - fetches all messages without this flag
    '''
    def __init__(self, account, mailbox, processor, flag):
        raise NotImplementedError('FetchFlagScanner '
                                  'is not implemented yet')


class FetchUnreadScanner(FetchFlagScanner):
    '''
    - fetches all unread messages from the server
    - marks messages read after scanning
    '''
    def __init__(self, account, mailbox, processor):
        super(FetchUnreadScanner, self).__init__(self, account, mailbox,
                                                 processor,
                                                 flag=imap.FLAG_SEEN)


class UidScanner(SeqIDScanner):
    '''
    - remembers which UIDs have already been seen
    - throws an error if mailbox has UIDNOTSTICKY status
    - throws an error if the UIDVALIDITY changes
      - on UIDVALIDITY change, client must have some other means to detect
        already downloaded messages.
        - (MailDB can detect duplicate messages)
    '''
    def __init__(self, account, mailbox, processor):
        raise NotImplementedError('UidScanner is not implemented yet')
