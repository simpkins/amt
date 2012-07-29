#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import base64
import functools
import logging
import os
import sqlite3

import whoosh.fields
import whoosh.index

from . import interface
from .interface import MUID, TUID, Location, MUID_HEADER, TUID_HEADER
from .err import *


def committable(fn):
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        do_commit = kwargs.pop('commit', True)
        ret = fn(self, *args, **kwargs)
        if do_commit:
            self.commit()
        return ret
    return wrapper


class MailDB(interface.MailDB):
    def __init__(self, path, widx):
        self.path = path
        self.widx = widx

        self._log = logging.getLogger('amt.maildb')

        sqlite_path = os.path.join(path, 'maildb.sqlite')
        self.db = sqlite3.connect(sqlite_path)

        uid_prefix = self.get_config_value('uid_prefix').decode('ASCII')
        self.muid_prefix = uid_prefix + '_M'
        self.tuid_prefix = uid_prefix + '_T'

    @classmethod
    def open_db(cls, path):
        # TODO: Make this code more robust to partially created/bad MailDB
        # directories.
        if not whoosh.index.exists_in(path):
            raise MailDBError('no MailDB found at "%s"', path)

        widx = whoosh.index.open_dir(path)
        return cls(path, widx)

    @classmethod
    def create_db(cls, path):
        # TODO: Make this code more robust to partially created/bad MailDB
        # directories.
        os.makedirs(path)

        schema = whoosh.fields.Schema(
            muid=whoosh.fields.ID(stored=True, unique=True),
            body=whoosh.fields.TEXT(stored=True),
            subject=whoosh.fields.TEXT(stored=True),
            date=whoosh.fields.DATETIME(stored=True),
            to=whoosh.fields.TEXT(stored=True),
            cc=whoosh.fields.TEXT(stored=True),
        )
        # 'from' is a keyword, so we have to add it separately
        schema.add('from', whoosh.fields.TEXT(stored=True))

        widx = whoosh.index.create_in(path, schema)

        cls.init_sqlite_db(path)

        return cls(path, widx)

    @classmethod
    def init_sqlite_db(cls, path):
        sqlite_path = os.path.join(path, 'maildb.sqlite')
        db = sqlite3.connect(sqlite_path)

        db.execute('CREATE TABLE metadata ('
                   'key TEXT UNIQUE, value TEXT, '
                   'PRIMARY KEY (key) ON CONFLICT REPLACE)')

        db.execute('CREATE TABLE messages ('
                   'muid INTEGER PRIMARY KEY AUTOINCREMENT, '
                   'message_id BLOB, subject BLOB, '
                   'timestamp DATETIME)')
        db.execute('CREATE INDEX messages_by_message_id '
                   'ON messages (message_id)')

        db.execute('CREATE TABLE msg_locations ('
                   'muid INTEGER, location BLOB, '
                   'UNIQUE (muid, location) ON CONFLICT IGNORE)')
        db.execute('CREATE INDEX locations_by_muid ON msg_locations (muid)')

        db.execute('CREATE TABLE msg_labels ('
                   'muid INTEGER, label TEXT, automatic BOOLEAN, '
                   'UNIQUE (muid, label) ON CONFLICT IGNORE)')
        db.execute('CREATE INDEX labels_by_muid ON msg_labels (muid)')

        db.execute('CREATE TABLE msg_thread ('
                   'muid INTEGER PRIMARY KEY, tuid INTEGER, '
                   'UNIQUE (muid, tuid) ON CONFLICT IGNORE)')
        db.execute('CREATE INDEX thread_msgs ON msg_thread (tuid)')

        db.execute('CREATE TABLE message_ids_to_thread '
                   '(message_id BLOB, tuid INTEGER)')
        db.execute('CREATE INDEX message_ids_to_thread_by_msg_id '
                   'ON message_ids_to_thread (message_id)')

        # The 'automatic' field records if this thread was automatically
        # created by get_tuid(), or was manually created by the user explicitly
        # splitting threads.  This is used to prevent the code from
        # automatically re-joining threads that had been explicitly split.
        db.execute('CREATE TABLE threads ('
                   'tuid INTEGER PRIMARY KEY AUTOINCREMENT, '
                   'subject STRING, '
                   'start_time INTEGER, end_time INTEGER, '
                   'automatic BOOLEAN)')
        db.execute('CREATE INDEX thread_subjects ON threads (subject)')

        random_data = os.urandom(6)
        uid_prefix = base64.b64encode(random_data)
        db.execute('INSERT INTO metadata VALUES (?, ?)',
                   ('uid_prefix', uid_prefix))

        db.commit()

    def get_config_value(self, key):
        cursor = self.db.execute('SELECT value FROM metadata WHERE key = ?',
                                 (key,))
        results = [entry[0] for entry in cursor]
        if not results:
            raise KeyError('no config entry named "%s"' % (key,))
        if len(results) != 1:
            raise AssertionError('found multiple entries for config key '
                                 '"%s": %s' % (key, results))
        return results[0]

    @committable
    def get_muid(self, msg, update_header=True, dup_check=True):
        muid_hdr = msg.get(MUID_HEADER)
        if muid_hdr is not None:
            return self._handle_existing_muid_header(muid_hdr, msg)

        muid = None
        if dup_check:
            muid = self._search_for_existing_muid(msg)

        if muid is None:
            muid = self._allocate_muid(msg)

        if update_header:
            msg.add_header(MUID_HEADER, muid.value)

        return muid

    def _handle_existing_muid_header(self, muid_hdr, msg):
        # Convert this into an internal ID.
        try:
            intid = self._muid2intid(muid_hdr)
        except BadMUIDError:
            # FIXME: handle the error
            raise

        msg_id = msg.get_message_id()
        timestamp = int(msg.timestamp)

        cursor = self.db.execute('SELECT (message_id, subject, timestamp) '
                                 'FROM messages WHERE muid = intid')
        results = list(cursor)
        if not results:
            # Hmm.  The message has a MUID we don't know about.
            # Maybe someone is rebuilding the database?
            # Just add this entry.
            self.db.execute('INSERT INTO messages '
                            '(muid, message_id, subject, timestamp) '
                            'VALUES (?, ?, ?, ?)',
                            (intid, msg.subject, timestamp))
            return MUID(muid_hdr)

        # Log a warning if this message doesn't look like the information
        # already in the DB.
        assert(len(results) == 1)
        entry = results[0]
        if (msg_id != entry[0] or msg.subject != entry[1] or
            timestamp != entry[2]):
            self._log.warning('found existing MUID header on message, '
                              'but does not match information in DB: '
                              'existing Message-ID: "%s", '
                              'new Message-ID: "%s"; '
                              'existing Subject: "%s", new Subject: "%s"; '
                              'existing timestamp: %s, new timestamp: %s',
                              msg_id, entry[0], msg.subject, entry[1],
                              timestamp, entry[2])

        return MUID(muid_hdr)

    def _search_for_existing_muid(self, msg):
        msg_id = msg.get_message_id()
        timestamp = int(msg.timestamp)
        if msg_id is None:
            # Search by subject and timestamp instead.
            # This search will be slow.  Maybe skip it?
            cursor = self.db.execute(
                'SELECT muid, message_id, subject, timestamp '
                'FROM messages WHERE '
                'message_id IS NULL AND subject = ? AND timestamp = ?',
                (msg.subject, timestamp))
        else:
            # TODO: Should we check the timestamps for agreement?
            cursor = self.db.execute(
                'SELECT muid, message_id, subject, timestamp '
                'FROM messages WHERE '
                'message_id = ? AND subject = ?',
                (msg_id, msg.subject))

        results = list(cursor)
        if not results:
            return None

        # TODO: We probably should store some sort of message fingerprint
        # in the messages table, and check that for equality.
        # This would be especially useful for messages with no Message-ID
        # header.

        # If we have a location for the existing MUID, should we perhaps check
        # the body contents?
        if len(results) == 1:
            entry = results[0]
            return self._intid2muid(entry[0])

        # Multiple matches.  Just return the first one whose timestamp matches.
        # (These are quite possibly just duplicate entries of each other.)
        for entry in results:
            if entry[3] == timestamp:
                return self._intid2muid(entry[0])

        return None

    def _allocate_muid(self, msg):
        msg_id = msg.get_message_id()
        timestamp = int(msg.timestamp)

        cursor = self.db.execute('INSERT INTO messages '
                                 '(message_id, subject, timestamp) '
                                 'VALUES (?, ?, ?)',
                                 (msg_id, msg.subject, timestamp))
        return self._intid2muid(cursor.lastrowid)

    def _intid2muid(self, internal_id):
        '''
        Convert an internal ID used in the sqlite database to a MUID.
        '''
        return MUID(self.muid_prefix + str(internal_id))

    def _muid2intid(self, muid):
        '''
        Convert a MUID to an internal ID for use in the sqlite database.
        '''
        return self._id2internal(muid.value, self.muid_prefix, BadMUIDError)

    def _intid2tuid(self, internal_id):
        '''
        Convert an internal ID used in the sqlite database to a MUID.
        '''
        return TUID(self.tuid_prefix + str(internal_id))

    def _tuid2intid(self, tuid):
        '''
        Convert a MUID to an internal ID for use in the sqlite database.
        '''
        return self._id2internal(tuid.value, self.tuid_prefix, BadTUIDError)

    def _id2internal(self, value, prefix, error_class):
        if not value.startswith(prefix):
            raise error_class(value, 'must start with "%s"', prefix)
        id_suffix = value[len(prefix):]
        return int(id_suffix)

    def commit(self):
        self.db.commit()

    @committable
    def add_location(self, muid, location):
        intid = self._muid2intid(muid)
        self.db.execute('INSERT INTO msg_locations VALUES (?, ?)',
                        (intid, location))

    @committable
    def remove_location(self, muid, location):
        intid = self._muid2intid(muid)
        loc_value = location.serialize()
        self.db.execute('DELETE FROM msg_locations WHERE '
                        'muid = ? AND location = ?',
                        (intid, loc_value))

    def get_locations(self, muid):
        intid = self._muid2intid(muid)
        cursor = self.db.execute('SELECT location FROM msg_locations '
                                 'WHERE muid = ?', (intid,))
        return [Location.deserialize(entry[0]) for entry in cursor]

    @committable
    def add_labels(self, muid, labels, automatic=False):
        intid = self._muid2intid(muid)

        def _gen_params():
            for label in labels:
                if isinstance(label, tuple):
                    yield (intid, label[0], bool(label[1]))
                else:
                    yield (intid, label, bool(automatic))

        self.db.executemany('INSERT INTO msg_labels VALUES (?, ?, ?)',
                            _gen_params())

    @committable
    def remove_labels(self, muid, labels):
        intid = self._muid2intid(muid)

        label_qmarks = ', '.join('?' for label in labels)
        params = (intid,) + tuple(labels)
        self.db.executemany('DELETE FROM msg_labels WHERE  muid = ? '
                            'AND label IN (%s)' % (label_qmarks,),
                            params)

    def get_label_details(self, muid):
        intid = self._muid2intid(muid)
        cursor = self.db.execute('SELECT label, automatic FROM msg_labels '
                                 'WHERE muid = ?', (intid,))
        return list(cursor)

    def index_msg(self, muid, msg, reindex=True):
        raise NotImplementedError()

    def search(self, query):
        raise NotImplementedError()

    def get_thread_msgs(self, tuid):
        intid = self._tuid2intid(tuid)
        cursor = self.db.execute('SELECT muid FROM msg_thread '
                                 'WHERE tuid = ?', (intid,))
        return [self._intid2muid(entry[0]) for entry in cursor]

    @committable
    def get_tuid(self, muid, msg, update_header=True):
        internal_tuid = self._pick_tuid(muid, msg)

        # Store the fact that this message belongs to this thread.
        # Store the MUID <--> TUID mapping
        self.db.execute('INSERT INTO msg_thread (muid, tuid) VALUES (?, ?)',
                        (self._muid2intid(muid), internal_tuid))

        # Store the Message-ID <--> TUID mapping
        msg_id = msg.get_message_id()
        if msg_id is not None:
            self.db.execute('INSERT INTO message_ids_to_thread '
                            '(message_id, tuid) VALUES (?, ?)',
                            (msg_id, internal_tuid))

        # Process the References and In-Reply-To headers from this message, and
        # store the fact that these Message-IDs belong to this thread.
        referenced_ids = msg.get_referenced_ids()
        self.db.executemany('INSERT INTO message_ids_to_thread '
                            '(message_id, tuid) VALUES (?, ?)',
                            ((msg_id, internal_tuid)
                             for msg_id in referenced_ids))

        tuid = self._intid2tuid(internal_tuid)
        if update_header:
            msg.add_header(TUID_HEADER, tuid.value)

        return tuid

    def _pick_tuid(self, muid, msg):
        # Check to see if this message has a TUID header
        tuid_hdr = msg.get(TUID_HEADER)
        if tuid_hdr is not None:
            return self._handle_existing_tuid_header(muid, msg, tuid_hdr)

        # Check to see if the database already contains a TUID for this MUID
        int_tuid = self._search_for_tuid_by_muid(muid, msg)
        if int_tuid is not None:
            return int_tuid

        # Search for a TUID by Message-ID
        int_tuid = self._search_for_tuid_by_message_id(muid, msg)
        if int_tuid is not None:
            return int_tuid

        # Search for a TUID by the Thread-Index header
        int_tuid = self._search_for_tuid_by_thread_index(muid, msg)
        if int_tuid is not None:
            return int_tuid

        # Search for a TUID by Subject
        subject_root = msg.get_subject_stem()
        int_tuid = self._search_for_tuid_by_subject(muid, msg, subject_root)
        if int_tuid is not None:
            return int_tuid

        # We didn't find any existing TUID.  Allocate a new one.
        return self._allocate_tuid(msg, subject_root)

    def _handle_existing_tuid_header(self, muid, msg, tuid_hdr):
        # Convert this into an internal ID.
        try:
            intid = self._tuid2intid(tuid_hdr)
        except BadMUIDError:
            # FIXME: handle the error
            raise

        # FIXME Make sure this TUID is present in the DB, and add it if not
        raise NotImplementedError()
        return intid

    def _search_for_tuid_by_muid(self, muid, msg):
        # Check to see if this MUID already has a known thread
        internal_muid = self._muid2intid(muid)
        c = self.db.execute('SELECT tuid FROM msg_thread WHERE muid = ?',
                            (internal_muid,))
        results = list(c)
        if results:
            assert len(results) == 1
            return results[0][0]

        return None

    def _search_for_tuid_by_message_id(self, muid, msg):
        # Search for any of the Message-IDs listed in the Message-ID,
        # References, or In-Reply-To header.
        msg_ids = []
        msg_ids.extend(msg.get_referenced_ids())

        msg_id = msg.get_message_id()
        if msg_id is not None:
            msg_ids.append(msg_id)

        if not msg_ids:
            return None

        qmarks = ', '.join('?' for msg_id in msg_ids)
        cursor = self.db.execute('SELECT tuid FROM message_ids_to_thread '
                                 'WHERE message_id IN (%s)' % qmarks,
                                 tuple(msg_ids))
        results = [entry[0] for entry in cursor]

        if not results:
            return None
        if len(results) == 1:
            return results[0]

        # FIXME: resolve the conflict
        raise NotImplementedError()

    def _search_for_tuid_by_thread_index(self, muid, msg):
        # TODO: Use the Thread-Index header
        return None

    def _search_for_tuid_by_subject(self, muid, msg, subject_root):
        # Search for threads with similar subjects
        # Only treat them as the same thread if they are close enough together
        # in time.  This new message may be close enough in time to multiple
        # existing TUIDs, in which case we should probably join them (unless
        # they were explicitly separated before...)
        cursor = self.db.execute('SELECT '
                                 'tuid, start_time, end_time, automatic '
                                 'FROM threads WHERE subject = ?',
                                 (subject_root,))

        # Only consider threads that occurred within 7 days of this message
        threshold = 60*60*24*7
        timestamp = int(msg.timestamp)

        for_consideration = []
        for match in cursor:
            tuid, start_time, end_time, automatic = match
            if (start_time - threshold) <= timestamp <= (end_time + threshold):
                for_consideration.append(tuid, automatic)

        if not for_consideration:
            return None
        if len(for_consideration) == 1:
            return for_consideration[0][0]

        # We have multiple matches.  We should join these threads together,
        # unless they were explicitly separated.
        raise NotImplementedError()

    def _allocate_tuid(self, msg, subject_root=None):
        if subject_root is None:
            subject_root = msg.get_subject_stem()

        timestamp = int(msg.timestamp)
        c = self.db.execute('INSERT INTO threads '
                            '(subject, start_time, end_time, automatic) '
                            'VALUES (?, ?, ?, ?)',
                            (subject_root, timestamp, timestamp, True))
        return c.lastrowid
