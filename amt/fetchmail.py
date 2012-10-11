#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import logging

from . import imap
from .getpassword import get_password
from .message import Message

'''
The fetchmail code is divided into 2 main pieces:

    - Scanner:
      - enumerates the messages on the server
      - decides which messages need to be fetched
    - Processor:
      - processes each message
      - handles delivery to local mailboxes
'''

class NoMoreMessagesError(Exception):
    def __init__(self):
        super(NoMoreMessagesError, self).__init__(self, 'no more messages')


class ProcessorError(Exception):
    def __init__(self, msg, ret):
        err_msg = 'processor failed while processing message'
        super(ProcessorError, self).__init__(self, err_msg)
        self.msg = msg
        self.ret = ret


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
    def _post_open(self):
        self.current_msg = None
        self.next_msg = 1
        self.conn.register_handler('EXPUNGE', self._on_expunge)

    def _on_expunge(self, response):
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
        while True:
            try:
                self.process_next_msg()
            except NoMoreMessagesError:
                return

    def run_forever(self):
        self.ensure_open()

        while True:
            self._run_once()
            self.conn.wait_for_exists()

    def process_next_msg(self):
        assert(self.next_msg <= self.conn.mailbox.num_messages + 1)
        if self.next_msg > self.conn.mailbox.num_messages:
            raise NoMoreMessagesError()

        self.current_msg = self.next_msg
        msg = self.conn.fetch_msg(self.current_msg)
        self.next_msg += 1
        self.invoke_processor(msg)

    def msg_successful(self):
        self.current_msg = None

    def msg_failed(self):
        self.current_msg = None

    def invoke_processor(self, msg):
        try:
            ret = self.processor.process_msg(msg)
            if ret != True:
                raise ProcessorError(msg, ret)
        except:
            # FIXME: implement some sort of retry functionality
            self.msg_failed()
            raise

        self.msg_successful()


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
