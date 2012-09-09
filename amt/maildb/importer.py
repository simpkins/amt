#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
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

    def msg_already_imported(self, loc, muid, idx, total=None):
        '''
        This method is called when a message is encountered that
        has already been imported at some previous time.

        - idx is the current message index in the mailbox (starting from 0).
        - total is the total number of messages in the mailbox.  It will
          be None unless want_percentage() returns True.
        '''
        pass

    def msg_import_starting(self, loc, idx, total=None):
        '''
        This method is called when starting to import a new message.
        (msg_import_starting() is not called for messages that have already been
        previously imported into the MailDB.)

        - idx is the current message index in the mailbox.
        - total is the total number of messages in the mailbox.  It will
          be None unless want_percentage() returns True.
        '''
        pass

    def msg_import_done(self, loc, msg, idx, total=None):
        '''
        This method is called after a message has been imported.
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
    def msg_already_imported(self, loc, muid, idx, total=None):
        print('%s --> already imported' % (loc,))

    def msg_import_starting(self, loc, idx, total=None):
        if total is not None:
            print('%d/%d  %s' % (idx + 1, total, loc))
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

    def run(self, maildir):
        # Accept a Maildir object, or a path to a maildir
        if not isinstance(maildir, Maildir):
            maildir = Maildir(maildir)

        if self.progress.want_percentage():
            # Perhaps we should report some progress as we are listing the
            # maildir?
            messages = list(maildir.list())
            total_count = len(messages)
        else:
            messages = maildir.list()
            total_count = None

        try:
            num_imported = 0
            for key, path in maildir.list():
                loc = MaildirLocation(path)
                self.import_msg(loc, num_imported, total_count)
                num_imported += 1

            self.mdb.commit()
        except:
            self.progress.import_aborted(num_imported)
            raise

        self.progress.import_done(num_imported)

    def import_msg(self, loc, num, total_count):
        try:
            muid = self.mdb.get_muid_by_location(loc)
            # We've already imported this message
            self.progress.msg_already_imported(loc, num, total_count)
            return
        except KeyError:
            # This message doesn't exist.  Fall through and import it
            pass

        self.progress.msg_import_starting(loc, num, total_count)
        msg = Message.from_maildir(loc.path)

        self.msgs_since_commit += 1
        if (self.commit_every > 0 and
            self.msgs_since_commit >= self.commit_every):
            should_commit = True
            self.msgs_since_commit = 0
        else:
            should_commit = False

        muid, tuid = self.mdb.import_msg(msg, commit=False)
        self.mdb.add_location(muid, loc, commit=should_commit)

        self.progress.msg_import_done(loc, msg, num, total_count)
