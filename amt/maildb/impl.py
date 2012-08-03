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

        db.execute('CREATE TABLE metadata '
                   '(key TEXT PRIMARY KEY ON CONFLICT REPLACE, value TEXT)')

        db.execute('CREATE TABLE messages ('
                   'muid INTEGER PRIMARY KEY AUTOINCREMENT, '
                   'message_id BLOB, subject BLOB, '
                   'timestamp DATETIME, fingerprint BLOB)')
        db.execute('CREATE INDEX messages_by_message_id '
                   'ON messages (message_id)')
        db.execute('CREATE INDEX messages_by_fingerprint '
                   'ON messages (fingerprint)')

        db.execute('CREATE TABLE msg_locations ('
                   'muid INTEGER, location BLOB, '
                   'UNIQUE (muid, location) ON CONFLICT IGNORE)')
        db.execute('CREATE INDEX locations_by_muid ON msg_locations (muid)')

        db.execute('CREATE TABLE msg_labels ('
                   'muid INTEGER, label TEXT, automatic BOOLEAN, '
                   'UNIQUE (muid, label) ON CONFLICT IGNORE)')
        db.execute('CREATE INDEX labels_by_muid ON msg_labels (muid)')
        db.execute('CREATE INDEX msgs_by_label ON msg_labels (label)')

        db.execute('CREATE TABLE thread_labels ('
                   'tuid INTEGER, label TEXT, automatic BOOLEAN, '
                   'UNIQUE (tuid, label) ON CONFLICT IGNORE)')
        db.execute('CREATE INDEX labels_by_tuid ON thread_labels (tuid)')
        db.execute('CREATE INDEX threads_by_label ON thread_labels (label)')

        db.execute('CREATE TABLE msg_thread ('
                   'muid INTEGER PRIMARY KEY, tuid INTEGER, '
                   'UNIQUE (muid, tuid) ON CONFLICT IGNORE)')
        db.execute('CREATE INDEX thread_msgs ON msg_thread (tuid)')

        db.execute('CREATE TABLE message_ids_to_thread '
                   '(message_id BLOB, tuid INTEGER)')
        db.execute('CREATE INDEX message_ids_to_thread_by_msg_id '
                   'ON message_ids_to_thread (message_id)')
        db.execute('CREATE INDEX message_ids_to_thread_by_tuid '
                   'ON message_ids_to_thread (tuid)')

        db.execute('CREATE TABLE merged_threads '
                   '(merged_from INTEGER PRIMARY KEY, merged_to INTEGER)')
        db.execute('CREATE INDEX merged_threads_by_to '
                   'ON merged_threads (merged_to)')

        # The 'automatic' field records if this thread was automatically
        # created by get_tuid(), or was manually created by the user explicitly
        # splitting threads.  This is used to prevent the code from
        # automatically re-merging threads that had been explicitly split.
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

    def commit(self):
        self.db.commit()

    @committable
    def add_location(self, muid, location):
        assert isinstance(muid, MUID)
        self.db.execute('INSERT INTO msg_locations VALUES (?, ?)',
                        (muid, location))

    @committable
    def remove_location(self, muid, location):
        assert isinstance(muid, MUID)
        loc_value = location.serialize()
        self.db.execute('DELETE FROM msg_locations WHERE '
                        'muid = ? AND location = ?',
                        (muid, loc_value))

    def get_locations(self, muid):
        cursor = self.db.execute('SELECT location FROM msg_locations '
                                 'WHERE muid = ?', (muid,))
        return [Location.deserialize(entry[0]) for entry in cursor]

    @committable
    def add_labels(self, muid, labels, automatic=False):
        assert isinstance(muid, MUID)
        def _gen_params():
            for label in labels:
                if isinstance(label, tuple):
                    yield (muid, label[0], bool(label[1]))
                else:
                    yield (muid, label, bool(automatic))

        self.db.executemany('INSERT INTO msg_labels VALUES (?, ?, ?)',
                            _gen_params())

    @committable
    def remove_labels(self, muid, labels):
        assert isinstance(muid, MUID)
        label_qmarks = ', '.join('?' for label in labels)
        params = (muid,) + tuple(labels)
        self.db.executemany('DELETE FROM msg_labels WHERE muid = ? '
                            'AND label IN (%s)' % (label_qmarks,),
                            params)

    def get_label_details(self, muid):
        assert isinstance(muid, MUID)
        cursor = self.db.execute('SELECT label, automatic FROM msg_labels '
                                 'WHERE muid = ?', (muid,))
        return list(cursor)

    @committable
    def add_thread_labels(self, tuid, labels, automatic=False):
        assert isinstance(tuid, TUID)
        def _gen_params():
            for label in labels:
                if isinstance(label, tuple):
                    yield (tuid, label[0], bool(label[1]))
                else:
                    yield (tuid, label, bool(automatic))

        self.db.executemany('INSERT INTO thread_labels VALUES (?, ?, ?)',
                            _gen_params())

    @committable
    def remove_thread_labels(self, tuid, labels):
        assert isinstance(tuid, TUID)
        label_qmarks = ', '.join('?' for label in labels)
        params = (tuid,) + tuple(labels)
        self.db.executemany('DELETE FROM thread_labels WHERE tuid = ? '
                            'AND label IN (%s)' % (label_qmarks,),
                            params)

    def get_thread_label_details(self, tuid):
        assert isinstance(tuid, TUID)
        cursor = self.db.execute('SELECT label, automatic FROM thread_labels '
                                 'WHERE tuid = ?', (tuid,))
        return list(cursor)

    def index_msg(self, muid, msg, reindex=True):
        assert isinstance(muid, MUID)
        raise NotImplementedError()

    def search(self, query):
        raise NotImplementedError()

    def get_thread_msgs(self, tuid):
        assert isinstance(tuid, TUID)
        tuid = tuid.resolve()
        cursor = self.db.execute('SELECT muid FROM msg_thread '
                                 'WHERE tuid = ?', (tuid,))
        return [self._create_muid(entry[0]) for entry in cursor]

    @committable
    def get_muid(self, msg, update_header=True, dup_check=True):
        muid_hdr = msg.get(MUID_HEADER)
        if muid_hdr is not None:
            return self._handle_existing_muid_header(muid_hdr, msg)

        muid = None
        fingerprint = None
        if dup_check:
            fingerprint = msg.fingerprint()
            muid = self._search_for_existing_muid(msg, fingerprint)

        if muid is None:
            muid = self._allocate_muid(msg, fingerprint)

        if update_header:
            msg.add_header(MUID_HEADER, muid.value())

        return muid

    def _handle_existing_muid_header(self, muid_hdr, msg):
        # Convert this into an internal ID.
        try:
            muid = self._parse_muid(muid_hdr)
        except BadMUIDError:
            # FIXME: handle the error
            raise

        msg_id = msg.get_message_id()
        timestamp = int(msg.timestamp)

        cursor = self.db.execute(
            'SELECT (message_id, subject, timestamp, fingerprint) '
            'FROM messages WHERE muid = intid')
        results = list(cursor)
        if not results:
            # Hmm.  The message has a MUID we don't know about.
            # Maybe someone is rebuilding the database?
            # Just add this entry.
            self.db.execute('INSERT INTO messages '
                            '(muid, message_id, subject, timestamp, '
                            'fingerprint) '
                            'VALUES (?, ?, ?, ?)',
                            (muid, msg.subject, timestamp, msg.fingerprint()))
            return muid

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

        return muid

    def _search_for_existing_muid(self, msg, fingerprint=None):
        if fingerprint is None:
            fingerprint = msg.fingerprint()
        cursor = self.db.execute(
            'SELECT muid, message_id, subject, timestamp '
            'FROM messages WHERE fingerprint = ?',
            (fingerprint,))
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
            return self._create_muid(entry[0])

        # Multiple matches.  Just return the first one whose timestamp matches.
        # (These are quite possibly just duplicate entries of each other.)
        timestamp = int(msg.timestamp)
        for entry in results:
            if entry[3] == timestamp:
                return self._create_muid(entry[0])

        return None

    def _allocate_muid(self, msg, fingerprint=None):
        msg_id = msg.get_message_id()
        timestamp = int(msg.timestamp)

        if fingerprint is None:
            fingerprint = msg.fingerprint()

        cursor = self.db.execute(
            'INSERT INTO messages '
            '(message_id, subject, timestamp, fingerprint) '
            'VALUES (?, ?, ?, ?)',
            (msg_id, msg.subject, timestamp, fingerprint))
        return self._create_muid(cursor.lastrowid)

    @committable
    def get_tuid(self, muid, msg, update_header=True):
        assert isinstance(muid, MUID)
        tuid = self._pick_tuid(muid, msg)

        # Store the fact that this message belongs to this thread.
        # Store the MUID <--> TUID mapping
        self.db.execute('INSERT INTO msg_thread (muid, tuid) VALUES (?, ?)',
                        (muid, tuid))

        # Store the Message-ID <--> TUID mapping
        msg_id = msg.get_message_id()
        if msg_id is not None:
            self.db.execute('INSERT INTO message_ids_to_thread '
                            '(message_id, tuid) VALUES (?, ?)',
                            (msg_id, tuid))

        # Process the References and In-Reply-To headers from this message, and
        # store the fact that these Message-IDs belong to this thread.
        referenced_ids = msg.get_referenced_ids()
        self.db.executemany('INSERT INTO message_ids_to_thread '
                            '(message_id, tuid) VALUES (?, ?)',
                            ((msg_id, tuid)
                             for msg_id in referenced_ids))

        if update_header:
            msg.add_header(TUID_HEADER, tuid.value())

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
            tuid = self._parse_tuid(tuid_hdr)
        except BadMUIDError:
            # FIXME: handle the error
            raise

        # FIXME Make sure this TUID is present in the DB, and add it if not
        raise NotImplementedError()
        return tuid

    def _search_for_tuid_by_muid(self, muid, msg):
        # Check to see if this MUID already has a known thread
        c = self.db.execute('SELECT tuid FROM msg_thread WHERE muid = ?',
                            (muid,))
        results = list(c)
        if results:
            assert len(results) == 1
            return self._create_tuid(results[0][0])

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
        tuids = [self._create_tuid(entry[0]) for entry in cursor]

        if not tuids:
            return None
        if len(tuids) == 1:
            return tuids[0]

        # This messages references several threads that we previously thought
        # were independent.  Join them together, as long as they weren't
        # manually split apart before.

        # FIXME: Exclude threads marked as manually split
        return self.merge_threads(*tuids)

    @committable
    def merge_threads(self, tuid1, tuid2, *args):
        if args:
            self.merge_threads(tuid1, *args)

        # If tuid1 had already been merged into another thread, use that tuid
        tuid1 = tuid1.resolve()

        real_tuid2 = tuid2.resolve()
        if real_tuid2 == tuid1:
            # These threads have already been merged together.
            # Nothing left to do
            return tuid1
        if real_tuid2 != tuid2:
            # tuid2 was already merged into some other thread
            raise MailDBError('atttempted to merge TUID %s into %s, '
                              'after it has already been merged into %s',
                              tuid2, tuid1, real_tuid2)

        # Change all of the messages in tuid2 to point to tuid1
        self.db.execute('UPDATE msg_thread '
                        'SET tuid = ? WHERE tuid = ?',
                        (tuid1, tuid2))
        self.db.execute('UPDATE message_ids_to_thread '
                        'SET tuid = ? WHERE tuid = ?',
                        (tuid1, tuid2))

        # Update merged_threads so that anything previously pointing at tuid2
        # now points directly to tuid.
        self.db.execute('UPDATE merged_threads '
                        'SET merged_to = ? WHERE merged_to = ?',
                        (tuid1, tuid2))

        # Leave an annotation that tuid2 was merged into tuid1
        self.db.execute('INSERT INTO merged_threads '
                        '(merged_from, merged_to) VALUES (?, ?)',
                        (tuid2, tuid1))

        return tuid1

    def _search_for_tuid_by_thread_index(self, muid, msg):
        # TODO: Use the Thread-Index header
        return None

    def _search_for_tuid_by_subject(self, muid, msg, subject_root):
        # Search for threads with similar subjects
        # Only treat them as the same thread if they are close enough together
        # in time.  This new message may be close enough in time to multiple
        # existing TUIDs, in which case we should probably merge them (unless
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
            tuid_value, start_time, end_time, automatic = match
            if (start_time - threshold) <= timestamp <= (end_time + threshold):
                tuid = self._create_tuid(tuid_value)
                for_consideration.append(tuid, automatic)

        if not for_consideration:
            return None
        if len(for_consideration) == 1:
            return for_consideration[0][0]

        # We have multiple matches.  We should merge these threads together,
        # unless they were explicitly separated.
        #
        # FIXME: don't merge explicitly split threads
        tuids = [tuid for tuid, automatic in for_consideration]
        return self.merged_threads(*tuids)

    def _allocate_tuid(self, msg, subject_root=None):
        if subject_root is None:
            subject_root = msg.get_subject_stem()

        timestamp = int(msg.timestamp)
        c = self.db.execute('INSERT INTO threads '
                            '(subject, start_time, end_time, automatic) '
                            'VALUES (?, ?, ?, ?)',
                            (subject_root, timestamp, timestamp, True))
        return self._create_tuid(c.lastrowid)

    def _create_muid(self, internal_id):
        '''
        Convert an internal ID used in the sqlite database to a MUID.
        '''
        return MUID(self, internal_id)

    def _parse_muid(self, value):
        '''
        Convert a MUID string value to an MUID object.
        '''
        if not value.startswith(self.muid_prefix):
            raise BadMUIDError(value, 'must start with "%s"', self.muid_prefix)
        id_suffix = value[len(prefix):]
        return MUID(self, int(id_suffix))

    def _create_tuid(self, internal_id):
        '''
        Convert an internal ID used in the sqlite database to a TUID.
        '''
        return TUID(self, internal_id)

    def _parse_tuid(self, value):
        '''
        Convert a TUID string value to an TUID object.
        '''
        if not value.startswith(self.tuid_prefix):
            raise BadTUIDError(value, 'must start with "%s"', self.tuid_prefix)
        id_suffix = value[len(prefix):]
        return TUID(self, int(id_suffix))


class MUID(interface.MUID):
    def __init__(self, maildb, value):
        assert isinstance(value, int)
        self._maildb = maildb
        self._value = value

    def value(self):
        return self._maildb.muid_prefix + str(self._value)

    def __conform__(self, protocol):
        if protocol is sqlite3.PrepareProtocol:
            return self._value


class TUID(interface.TUID):
    def __init__(self, maildb, value):
        assert isinstance(value, int)
        self._maildb = maildb
        self._value = value

    def value(self):
        return self._maildb.tuid_prefix + str(self._value)

    def __conform__(self, protocol):
        if protocol is sqlite3.PrepareProtocol:
            return self._value

    def resolve(self):
        c = self._maildb.db.execute('SELECT merged_to FROM merged_threads '
                                    'WHERE merged_from = ?', (self,))
        results = list(c)
        if not results:
            return self
        assert len(results) == 1

        merged_to = TUID(self._maildb, results[0][0])

        # merge_threads() should update the merged_threads table to always
        # point directly at the final result.
        assert merged_to.resolve() == merged_to

        return merged_to
