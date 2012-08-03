#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
'''
This file defines the interface to access a MailDB.

It exists primarily to keep the API documentation in a single easy-to-read
location, and to keep it separate from the actual storage implementation.
'''

MUID_HEADER = 'X-AMT-MUID'
TUID_HEADER = 'X-AMT-TUID'


class MailDB:
    '''
    A data store containing information about a set of email messages.

    The MailDB itself only contains metadata: message labels, indices for text
    search, etc.  The actual messages and their contents are stored elsewhere
    (e.g., in maildirs or IMAP folders), and referenced by Location objects.

    The MailDB primarily tracks messages by MUIDs.  It stores a mapping from
    MUIDs to the physical Locations containing the message contents.  All other
    indices in the database then just refer to messages by MUID.
    '''
    @classmethod
    def open_db(cls, path):
        '''
        Returns a MailDB object to access the database at the specified path.

        The database must already exist at the specified path.  Use the
        create_db() classmethod to create a brand new MailDB.
        '''
        raise NotImplementedError()

    @classmethod
    def create_db(cls, path):
        '''
        Create a new MailDB at the specified path.

        Throws an exception if a MailDB already exists at the given path.
        Returns a MailDB object.
        '''
        raise NotImplementedError()

    def backup_db(self, path):
        '''
        Store a backup of the MailDB at the specified path.
        This may be a slow function.
        '''
        raise NotImplementedError()

    def commit(self):
        '''
        Commit the database changes to disk.

        Most functions that modify the database will automatically commit the
        changes to disk.  However, if an explicit commit=False keyword argument
        is supplied to any modifying function, it will skip committing the
        changes to disk.  In this case, commit() must be manually called later
        to commit the changes.
        '''
        raise NotImplementedError()

    def get_muid(self, msg, update_header=True, dup_check=True, commit=True):
        '''
        Get an MUID for a message.

        If the message already contains an X-AMT-MUID header, the existing MUID
        is read from this header and returned.  Otherwise a new MUID is
        allocated.

        If dup_check is True, the database will look at the message contents
        and search the DB to see if an existing MUID already exists for this
        message.  If dup_check is False this search will be skipped, which may
        improve performance.

        If a new MUID is allocated and the update_header parameter is True, an
        X-AMT-MUID header containing the new MUID is added to the message.

        Typically you want to use import_msg() rather than calling get_muid()
        directly.
        '''
        raise NotImplementedError()

    def import_msg(self, msg, update_header=True, reindex=False,
                   dup_check=True, commit=True):
        '''
        Get an MUID and TUID for a message, and index the message contents.

        This is essentially a helper function that combines get_muid(),
        get_tuid(), and index_msg().  The caller must still call add_location()
        to add a Location for the message.

        Returns a (muid, tuid) tuple
        '''
        muid = self.get_muid(msg, update_header=update_header,
                             dup_check=dup_check, commit=False)
        tuid = self.get_tuid(muid, msg, update_header=update_header,
                             commit=False)
        if commit:
            self.commit()
        self.index_msg(muid, msg, reindex=reindex)
        return muid, tuid

    def add_location(self, muid, location, commit=True):
        '''
        Indicate that the specified message is also stored at the specified
        location.
        '''
        raise NotImplementedError()

    def remove_location(self, muid, location, commit=True):
        '''
        Indicate that the specified message is no longer stored at the
        specified location.

        Note that even when the last location for an MUID is removed,
        the MailDB still tracks metadata for the MUID.
        '''
        raise NotImplementedError()

    def get_locations(self, muid):
        '''
        Get the locations for the specified message.

        Returns a list of Location objects.
        '''
        raise NotImplementedError()

    def get_msgs_by_mailbox(self, mailbox):
        '''
        Get all known message locations in the specified mailbox.

        Returns a list of (muid, location) tuples.

        This may be a slow operation: the MailDB does not necessarily store
        a fast index of messages by mailbox.  This is primarily intended for
        cleaning up or rebuilding the index after a mailbox has been removed or
        rebuilt.  (For example, re-indexing is necessary if the UIDVALIDITY of
        an IMAP folder changes, or if an mbox is rewritten in a non-append-only
        manner.)
        '''
        raise NotImplementedError()

    def add_label(self, muid, label, automatic=False, commit=True):
        '''
        Add a new label for the specified message.

        The automatic parameter specifies if this was an automatically computed
        or one manually specified by the user.
        '''
        self.add_labels(muid, [(label, automatic)], commit=commit)

    def add_labels(self, muid, labels, automatic=False, commit=True):
        '''
        Add new labels for the specified message.

        Each entry in the labels parameter can be either a plain string, or a
        (label, automatic) tuple, where the second entry of the tuple is a
        boolean indicating if the label was automatically computed or manually
        specified.

        For label entries that are just plain strings, they will take their
        automatic setting from the automatic parameter.
        '''
        raise NotImplementedError()

    def remove_label(self, muid, label, commit=True):
        '''
        Remove a label from the specified message.
        '''
        self.remove_labels(muid, [label], commit=commit)

    def remove_labels(self, muid, labels, commit=True):
        '''
        Add labels from the specified message.
        '''
        raise NotImplementedError()

    def get_labels(self, muid):
        '''
        Get the labels for the specified message.

        Returns a list of labels (as strings).
        '''
        return [label for label, automatic in self.get_label_details(muid)]

    def get_label_details(self, muid):
        '''
        Get the labels for the specified message.

        Returns a list of (label, automatic) tuples.
        '''
        raise NotImplementedError()

    def index_msg(self, muid, msg, reindex=True):
        '''
        Index the contents of the message for text-based search.

        If this MUID has already been indexed in the past and reindex is False,
        index_msg will return without doing anything.  If reindex is True,
        the old index information for this message will be thrown away and the
        message will be re-indexed.
        '''
        raise NotImplementedError()

    def search(self, query):
        '''
        Search for messages.

        Returns a list of MUIDs.

        The query language syntax isn't currently specified as part of the
        MailDB interface.  The query language syntax is currently
        implementation-specific.
        '''
        raise NotImplementedError()

    def get_thread_msgs(self, tuid):
        '''
        Look up the messages in the specified thread.

        Returns a list of MUIDs.
        '''
        raise NotImplementedError()

    def get_tuid(self, muid, msg, update_header=True, commit=True):
        '''
        Get the TUID for a message.

        If this message already has a TUID assigned in the MailDB, that TUID is
        returned.  Otherwise, if the message contains an X-AMT-TUID header, the
        existing TUID is read from this header and returned.

        If no existing TUID is found, this function heuristically attempts to
        determine if this message belongs to an existing known thread.  If so,
        the TUID for that thread is returned.  If the message is not part of
        any known thread, a new TUID is allocated and returned.

        If the update_header parameter is true, the message headers are updated
        with an X-AMT-TUID header storing the assigned TUID.

        Note that an existing X-AMT-TUID header may be replaced in cases where
        the MailDB contains a newer TUID for this message (in cases where
        threads have been merged or split since the original X-AMT-TUID header
        was stored).
        '''
        raise NotImplementedError()

    def merge_threads(self, tuid1, tuid2, *args):
        '''
        Merge threads, indicating that they are now a single thread.

        tuid2 and any subsequent TUID arguments will be merged into tuid1.
        All messages in tuid2 will now be marked as being in tuid1.

        tuid2 will be retired, and an annotation will be left in the MailDB
        indicating that tuid2 was merged into tuid1.  This way the MailDB will
        still be able to properly handle messages containing X-AMT-TUID headers
        with the old TUID.

        Any thread labels that exist for tuid2 will be added to tuid1.

        Raises an exception if tuid2 or any of the subsequent TUIDs was
        previously been merged to another thread (other than tuid1).

        Returns the merged thread's TUID.  Normally this is tuid1, although
        if tuid1 had previously been merged into another thread this will be
        the thread that tuid1 was merged into.
        '''
        raise NotImplementedError()

    def split_thread(self, muids):
        '''
        Split the specified messages from their current thread, and put them in
        a new thread.

        A new TUID is allocated for the specified messages and returned.
        The newly allocated thread will have no thread labels.
        '''
        raise NotImplementedError()

    def add_thread_label(self, tuid, label):
        '''
        Add a new label for the specified thread.
        '''
        raise NotImplementedError()

    def add_thread_labels(self, tuid, labels):
        '''
        Add new labels for the specified thread.
        '''
        raise NotImplementedError()

    def get_thread_labels(self, tuid):
        '''
        Get the labels for the specified thread.
        '''
        raise NotImplementedError()


class MailboxLocation:
    '''
    The physical location of a mailbox.

    This can be:
    - A maildir path
    - An IMAP folder
    - An mbox path
    - Potentially other locations in the future
    '''
    pass


class Location:
    '''
    The physical location of an email message.

    This can be:
    - A location in a maildir (i.e., a location on disk)
    - A location in an IMAP folder (IMAP folder name, UID, and UIDVALIDITY)
    - An offset into an append-only mbox
    - Potentially other locations in the future
    '''
    @classmethod
    def deserialize(cls, data):
        '''
        Create a Location object from the serialized location data.
        '''
        raise NotImplementedError()

    def serialize(self):
        '''
        Return a representation of this location as a bytes/bytearray.

        The serialized data can be stored and deserialized later.
        This method exists so that Location objects can easily be stored in a
        MailDB.
        '''
        raise NotImplementedError()


class MUID:
    '''
    A unique identifier for an email message.

    All instances of the same message will share the same MUID.

    Semantics
    ---------
    It's a little bit fuzzy exactly what qualifies as the same message:
    If a message is received, and then copied, the two copies should share the
    same MUID.  However, if the copy is modified, should it get a new MUID?
    This is mostly left up to the code performing the modification to decide if
    the modification is significant enough to warrant a new MUID.

    The MailDB supports looking up message Locations based on MUID.  If
    multiple message locations are found, there is no strict guarantee that the
    message contents/headers at each location will be identical.  Ideally they
    should be largely the same: if they aren't then someone probably should
    have allocated a new MUID when modifying a message.

    Allocation/Usage
    ----------------
    When a message is first imported into a MailDB, a new MUID will be
    allocated for it.  A new X-AMT-MUID header should be added to the message
    to store the MUID.  This way we will be able to quickly re-import the
    message in case it is ever moved/copied without notifying the MailDB.

    Contents
    --------
    An MUID is effectively just an opaque string value.
    '''
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return self.value

    def __repr__(self):
        return 'MUID(%r)' % (self.value,)

    def __eq__(self, other):
        return isinstance(other, MUID) and self.value == other.value

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.value)


class TUID:
    '''
    A unique identifier for an email thread.

    Thread IDs are assigned to messages heuristically.  Threads may be
    merged/split after TUIDs have been allocated and assigned to messages.

    Contents
    --------
    A TUID is effectively just an opaque string value.
    '''
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return self.value

    def __repr__(self):
        return 'TUID(%r)' % (self.value,)

    def __eq__(self, other):
        return isinstance(other, TUID) and self.value == other.value

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.value)
