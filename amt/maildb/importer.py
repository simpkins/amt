#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import multiprocessing
import sys

from ..maildir import Maildir
from ..message import Message

from .location import MaildirLocation


class ProgressDisplay:
    def want_percentage(self):
        '''
        This function should return True if the ProgressDisplay would like
        the total number of messages to be pre-computed so it can display
        progress information.
        '''
        return False

    def msg_already_imported(self, loc, muid, num, total=None):
        '''
        This method is called when a message is encountered that
        has already been imported at some previous time.

        - loc is a Location object describing the message path
        - num is how many messages have been processed (including this one)
        - total is the total number of messages in the mailbox.  It will
          be None unless want_percentage() returns True.
        '''
        pass

    def msg_import_done(self, loc, msg, num, total=None):
        '''
        This method is called after a message has been imported.

        - loc is a Location object describing the message path
        - msg is the Message object
        - num is how many messages have been processed (including this one)
        - total is the total number of messages in the mailbox.  It will
          be None unless want_percentage() returns True.
        '''
        pass

    def import_done(self, total):
        '''
        This method is called when an import run is complete.

        total will contain the total number of messages imported.
        '''
        pass

    def import_aborted(self, total):
        '''
        This method is called when an import run is aborted part-way
        through.  (For example, due to an error or KeyboardInterrupt.)

        total will contain the total number of messages imported.
        '''
        pass


class SimpleProgressDisplay(ProgressDisplay):
    def msg_already_imported(self, loc, muid, num, total=None):
        print('%s --> already imported' % (loc,))

    def msg_import_done(self, loc, msg, num, total=None):
        if total is not None:
            print('%d/%d  %s' % (num, total, loc))
        else:
            print(loc)


class Importer:
    def __init__(self, mdb, progress):
        self.mdb = mdb
        self.progress = progress
        if self.progress is None:
            self.progress = ProgressDisplay()

        self.commit_every = 20
        self.msgs_since_commit = 0
        self.num_threads = multiprocessing.cpu_count()

    def run(self, maildir):
        # Accept a Maildir object, or a path to a maildir
        if not isinstance(maildir, Maildir):
            maildir = Maildir(maildir)

        try:
            self._run_import(maildir)
        except:
            self.progress.import_aborted(self.num_finished)
            raise

        self.mdb.commit()
        self.msgs_since_commit = 0
        self.progress.import_done(self.num_finished)

    def _run_import(self, maildir):
        self.num_in_flight = 0
        self.num_finished = 0

        if self.progress.want_percentage():
            messages = list(maildir.list())
            self.msg_iterator = iter(messages)
            self.total_count = len(messages)
        else:
            self.msg_iterator = maildir.list()
            self.total_count = None

        # Start worker threads to load the messages
        self.to_process = multiprocessing.Queue()
        self.loaded_msgs = multiprocessing.Queue()
        self.workers = []
        try:
            for n in range(self.num_threads):
                self._add_next_loc()
                if self.msg_iterator is None:
                    # No more input to process.
                    # Don't bother starting more workers
                    return

                t = multiprocessing.Process(target=self._msg_parser_thread)
                self.workers.append(t)
                t.start()

            # Add one more message to the queue for each thread,
            # so that we have 2 messages in the pipeline for each thread
            # at any point in time.  This generally helps us make better
            # use of the CPU, as it is less likely for a worker thread to be
            # idle waiting on us to give it another message.
            for n in range(self.num_threads):
                self._add_next_loc()

            while self.num_in_flight > 0:
                self._add_next_loc()
                loc, msg = self.loaded_msgs.get()
                self.num_in_flight -= 1

                if loc is None:
                    # msg is actually an exception that occurred
                    raise msg

                self._import_msg(loc, msg)
        finally:
            for worker in self.workers:
                self.to_process.put(None)
            for worker in self.workers:
                worker.join()

    def _add_next_loc(self):
        if self.msg_iterator is None:
            return

        while True:
            try:
                key, path = next(self.msg_iterator)
            except StopIteration:
                # No more input left to process
                self.msg_iterator = None
                return

            loc = MaildirLocation(path)
            try:
                muid = self.mdb.get_muid_by_location(loc)
                # We've already imported this message
                self.num_finished += 1
                self.progress.msg_already_imported(loc, self.num_finished,
                                                   self.total_count)
                continue
            except KeyError:
                # This message doesn't exist.
                # Add it to the queue to be imported
                self.num_in_flight += 1
                self.to_process.put(loc)
                return

    def _msg_parser_thread(self):
        try:
            while True:
                loc = self.to_process.get()
                if loc is None:
                    return

                try:
                    msg = Message.from_maildir(loc.path)
                except Exception as ex:
                    self.loaded_msgs.put((None, ex))
                    continue
                self.loaded_msgs.put((loc, msg))
        except:
            # On any other exception, just exit this worker thread.
            # This lets us handle KeyboardInterrupt, when all threads
            # receive an interrupt.  We may see this as a
            # KeyboardInterrupt, or possibly as an EOFError when trying to
            # read from the to_process queue if the main thread was
            # interrupted while putting data on the queue.
            return

    def _import_msg(self, loc, msg):
        self.msgs_since_commit += 1
        if (self.commit_every > 0 and
            self.msgs_since_commit >= self.commit_every):
            should_commit = True
            self.msgs_since_commit = 0
        else:
            should_commit = False

        muid, tuid = self.mdb.import_msg(msg, commit=False)
        self.mdb.add_location(muid, loc, commit=should_commit)

        self.num_finished += 1
        self.progress.msg_import_done(loc, msg,
                                      self.num_finished, self.total_count)
