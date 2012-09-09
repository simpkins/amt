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
from .interface import MUID, TUID, MUID_HEADER, TUID_HEADER
from .location import Location
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
        self.db = sqlite3.connect(sqlite_path, isolation_level='DEFERRED')

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

        # Set the isolation_level to None.
        # Otherwise the python sqlite3 module will commit before each
        # CREATE TABLE statement, which makes things slow.
        db = sqlite3.connect(sqlite_path, isolation_level=None)

        db.execute('BEGIN EXCLUSIVE TRANSACTION')
        db.execute('CREATE TABLE metadata '
                   '(key TEXT PRIMARY KEY ON CONFLICT REPLACE, value TEXT)')

        db.execute('CREATE TABLE messages ('
                   'muid INTEGER PRIMARY KEY AUTOINCREMENT, '
                   'tuid INTEGER, '
                   'message_id BLOB, subject BLOB, '
                   'timestamp DATETIME, fingerprint BLOB)')
        db.execute('CREATE INDEX messages_by_message_id '
                   'ON messages (message_id)')
        db.execute('CREATE INDEX messages_by_fingerprint '
                   'ON messages (fingerprint)')
        db.execute('CREATE INDEX thread_msgs ON messages (tuid)')

        db.execute('CREATE TABLE msg_locations ('
                   'muid INTEGER, location BLOB, '
                   'UNIQUE (location))')
        db.execute('CREATE INDEX locations_by_muid ON msg_locations (muid)')
        db.execute('CREATE INDEX muids_by_location ON msg_locations '
                   '(location)')

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

        db.execute('CREATE TABLE threads ('
                   'tuid INTEGER PRIMARY KEY AUTOINCREMENT, '
                   'subject STRING, '
                   'start_time INTEGER, end_time INTEGER)')
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
                        (muid, location.serialize()))

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

    def get_muid_by_location(self, loc):
        cursor = self.db.execute('SELECT muid FROM msg_locations '
                                 'WHERE location = ?', (loc.serialize(),))
        results = [self._muid_from_db(entry[0]) for entry in cursor]
        if not results:
            raise KeyError(loc)
        assert len(results) == 1
        return results[0]

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

        # FIXME: implement indexing
        pass

    def search(self, query):
        raise NotImplementedError()

    def get_thread_msgs(self, tuid):
        assert isinstance(tuid, TUID)
        tuid = tuid.resolve()
        cursor = self.db.execute('SELECT muid FROM messages '
                                 'WHERE tuid = ?', (tuid,))
        return [self._muid_from_db(entry[0]) for entry in cursor]

    @committable
    def import_msg(self, msg, update_header=True, dup_check=True):
        muid, tuid = self._get_muid_tuid(msg, dup_check=dup_check)
        assert isinstance(muid, MUID)
        assert isinstance(tuid, TUID)

        # TODO: index the message

        if update_header:
            msg.remove_header(MUID_HEADER)
            msg.remove_header(TUID_HEADER)
            msg.add_header(MUID_HEADER, muid.value())
            msg.add_header(TUID_HEADER, tuid.value())

        return muid, tuid

    def _get_muid_tuid(self, msg, dup_check=True):
        muid = None
        tuid = None

        muid_hdr = msg.get(MUID_HEADER)
        if muid_hdr is not None:
            muid, tuid = self._handle_existing_muid_header(muid_hdr, msg)
        if muid is not None:
            assert tuid is not None
            return muid, tuid

        fingerprint = None
        if dup_check:
            fingerprint = msg.binary_fingerprint()
            muid, tuid = self._search_for_existing_muid(msg, fingerprint)
        if muid is not None:
            assert tuid is not None
            return muid, tuid

        # We don't have an existing MUID for this message, so we need to
        # create a new entry.
        assert tuid is None
        return self._insert_message(msg, fingerprint=fingerprint)

    def _handle_existing_muid_header(self, muid_hdr, msg):
        # Convert this into an internal ID.
        try:
            muid = self._parse_muid(muid_hdr)
        except BadMUIDError:
            # This doesn't look like a valid MUID for this MailDB.
            # Just ignore it.
            return None, None

        cursor = self.db.execute(
            'SELECT tuid, message_id, subject, timestamp, fingerprint '
            'FROM messages WHERE muid = ?',
            (muid,))
        results = list(cursor)
        if not results:
            # Hmm.  The message has a MUID we don't know about.
            # Maybe someone is rebuilding the database?
            return self._handle_unknown_existing_muid(muid, msg)

        assert(len(results) == 1)
        entry = results[0]

        db_tuid = self._tuid_from_db(entry[0])
        db_fingerprint = entry[4]
        msg_fingerprint = msg.binary_fingerprint()
        if db_fingerprint == msg_fingerprint:
            # This message matches the information we have stored in the
            # database.
            return muid, db_tuid

        # The MUID stored in the header does not look like the message
        # in the database.
        db_msg_id = entry[1]
        db_subject = entry[2]
        db_timestamp = entry[3]

        msg_id = msg.get_message_id()
        msg_timestamp = int(msg.timestamp)

        db_fingerprint_b64 = base64.b64encode(db_fingerprint)
        msg_fingerprint_b64 = base64.b64encode(msg_fingerprint)

        self._log.warning('found existing MUID header on message, '
                          'but does not match information in DB: '
                          'MUID: %s, '
                          'DB Message-ID: "%s", '
                          'new Message-ID: "%s"; '
                          'DB Subject: "%s", new Subject: "%s"; '
                          'DB timestamp: %s, new timestamp: %s; '
                          'DB fingerprint: %s, new fingerpring: %s',
                          muid, db_msg_id, msg.get_message_id(),
                          db_subject, msg.subject, db_timestamp, msg_timestamp,
                          db_fingerprint_b64, msg_fingerprint_b64)

        # TODO: If the Subject and Message-ID match, perhaps we should just
        # use this MUID and TUID even though the fingerprint doesn't fully
        # match?
        #
        # For now, just return None, None so our caller will continue
        # with the normal MUID allocation code, as if the MUID header
        # wasn't present.
        return None, None

    def _handle_unknown_existing_muid(self, muid, msg):
        # Look for a TUID header in the message
        hdr_tuid = None
        tuid_hdr_value = msg.get(MUID_HEADER)
        if tuid_hdr_value is not None:
            try:
                tuid_from_hdr = self._parse_tuid(tuid_hdr_value)
            except BadTUIDError:
                # This doesn't look like a valid TUID for this MailDB.
                # Just ignore it.
                pass

        if hdr_tuid is None:
            # No existing TUID.  Just call _insert_message() and let
            # it find an appropriate TUID to use.
            return self._insert_message(msg, muid=muid)

        msg_subject_root = msg.get_subject_stem()

        # Look to see if hdr_tuid exists in the DB.  If so, check to see
        # if the thread information matches the TUID in the DB.
        cursor = self.db.execute('SELECT subject FROM threads '
                                 'WHERE tuid = ?',
                                 (hdr_tuid,))
        results = list(cursor)
        if not results:
            hdr_tuid_known = False
            hdr_tuid_match = False
        else:
            assert len(results) == 1
            hdr_tuid_known = True
            existing_subject = results[0][0]
            hdr_tuid_match = (existing_subject == msg_subject_root)

        # If the header TUID already exists in the database, and the thread
        # subject matches, use this TUID, even if it isn't the one we would
        # have picked in the absence of the header.
        if hdr_tuid_known and hdr_tuid_match:
            return self._insert_message(msg, muid=muid, tuid=tuid)

        # If the header TUID exists in the database but isn't a match, ignore
        # it.  (This can happen if we are rebuilding the database, but messages
        # were imported in a different order, so the new TUID values don't
        # match.)
        #
        # Let _insert_message() pick an appropriate TUID to use
        if hdr_tuid_known and not hdr_tuid_match:
            return self._insert_message(msg, muid=muid)

        # If we are still here, hdr_tuid doesn't exist in the database
        assert not hdr_tuid_known

        # Perform the normal TUID search to find a TUID for this message
        # Do this before adding hdr_tuid to the threads table,
        # so we won't find hdr_tuid
        db_tuid = self._search_for_tuid(msg, allocate=False)
        assert db_tuid != hdr_tuid

        # If we found an existing match, use that TUID, and add an entry
        # to the database indicating that hdr_tuid has been merged into
        # db_tuid.
        if db_tuid is not None:
            # Add hdr_tuid to the threads table
            self._allocate_tuid(msg, subject_root=msg_subject_root,
                                tuid=hdr_tuid)
            # Indicate that hdr_tuid is merged into db_tuid
            self.db.execute('INSERT INTO merged_threads '
                            '(merged_from, merged_to) VALUES (?, ?)',
                            (hdr_tuid, db_tuid))
            return self._insert_message(msg, muid=muid, tuid=db_tuid)

        # No existing match found.  Add hdr_tuid to the database,
        # and use it.
        self._allocate_tuid(msg, subject_root=msg_subject_root, tuid=hdr_tuid)
        return self._insert_message(msg, muid=muid, tuid=hdr_tuid)

    def _search_for_existing_muid(self, msg, fingerprint=None):
        if fingerprint is None:
            fingerprint = msg.binary_fingerprint()
        cursor = self.db.execute(
            'SELECT muid, tuid, message_id, subject, timestamp '
            'FROM messages WHERE fingerprint = ?',
            (fingerprint,))
        results = list(cursor)
        if not results:
            return None, None

        # In case there were multiple matches, just pick the first one
        # with a matching timestamp.  If there are no matching timestamps,
        # Just use the first entry anyway.
        # (Other matching entries are possibly just duplicates somehow.)
        best_match = results[0]
        if len(results) > 1:
            timestamp = int(msg.timestamp)
            for entry in results:
                if entry[4] == timestamp:
                    best_match = entry
                    break

        muid = self._muid_from_db(best_match[0])
        tuid = self._tuid_from_db(best_match[1])
        return muid, tuid

    def _insert_message(self, msg, muid=None, tuid=None, fingerprint=None):
        msg_id = msg.get_message_id()
        timestamp = int(msg.timestamp)

        if fingerprint is None:
            fingerprint = msg.binary_fingerprint()

        if tuid is None:
            # Find a TUID for the message, and allocate a new TUID if
            # necessary.
            tuid = self._search_for_tuid(msg, allocate=True)
        assert isinstance(tuid, TUID)

        # Insert the message into the messages table
        if muid is None:
            cursor = self.db.execute(
                'INSERT INTO messages '
                '(tuid, message_id, subject, timestamp, fingerprint) '
                'VALUES (?, ?, ?, ?, ?)',
                (tuid, msg_id, msg.subject, timestamp, fingerprint))
            muid = self._muid_from_db(cursor.lastrowid)
        else:
            cursor = self.db.execute(
                'INSERT INTO messages '
                '(muid, tuid, message_id, subject, timestamp, fingerprint) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (muid, tuid, msg_id, msg.subject, timestamp, fingerprint))

        # Insert the Message-ID and all IDs referenced by this message
        # into the message_ids_to_thread table
        msg_ids = msg.get_referenced_ids()
        msg_id = msg.get_message_id()
        if msg_id is not None:
            msg_ids.append(msg_id)
        self.db.executemany('INSERT INTO message_ids_to_thread '
                            '(message_id, tuid) VALUES (?, ?)',
                            ((msg_id, tuid)
                             for msg_id in msg_ids))

        return muid, tuid

    def _search_for_tuid(self, msg, allocate):
        # Search for a TUID by Message-ID
        tuid = self._search_for_tuid_by_message_id(msg)
        if tuid is not None:
            return tuid

        # Search for a TUID by the Thread-Index header
        tuid = self._search_for_tuid_by_thread_index(msg)
        if tuid is not None:
            return tuid

        # Search for a TUID by Subject
        subject_root = msg.get_subject_stem()
        tuid = self._search_for_tuid_by_subject(msg, subject_root)
        if tuid is not None:
            return tuid

        # No existing TUID found
        if allocate:
            # No known thread looks like a good match for this message.
            # Allocate a new TUID.
            return self._allocate_tuid(msg, subject_root=subject_root)
        else:
            return None

    def _search_for_tuid_by_message_id(self, msg):
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
        tuids = [self._tuid_from_db(entry[0]) for entry in cursor]

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
        self.db.execute('UPDATE messages '
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

    def _search_for_tuid_by_thread_index(self, msg):
        # TODO: Use the Thread-Index header
        return None

    def _search_for_tuid_by_subject(self, msg, subject_root):
        # FIXME: We need to keep track of whether or not we have seen
        # the "root message" for each thread.  We should never merge together
        # two threads that both have the same root.  When looking just by
        # subject, we should treat the message as the root if the subject
        # is the same as the subject_root.
        #
        # In other words, allow two messages to be part of the same thread
        # if at least one of them has a subject of "Re: foo".  However, if both
        # subjects are just "foo", we should still treat them as separate
        # threads.

        # Search for threads with similar subjects
        # Only treat them as the same thread if they are close enough together
        # in time.  This new message may be close enough in time to multiple
        # existing TUIDs, in which case we should probably merge them (unless
        # they were explicitly separated before...)
        cursor = self.db.execute('SELECT tuid, start_time, end_time '
                                 'FROM threads WHERE subject = ?',
                                 (subject_root,))

        # Only consider threads that occurred within 7 days of this message
        threshold = 60*60*24*7
        timestamp = int(msg.timestamp)

        matching_tuids = []
        for match in cursor:
            tuid_value, start_time, end_time = match
            if (start_time - threshold) <= timestamp <= (end_time + threshold):
                tuid = self._tuid_from_db(tuid_value)
                matching_tuids.append(tuid)

        if not matching_tuids:
            return None
        if len(matching_tuids) == 1:
            return matching_tuids[0]

        # We have multiple matches.  We should merge these threads together,
        # unless they were explicitly separated.
        #
        # FIXME: don't merge explicitly split threads
        return self.merged_threads(*matching_tuids)

    def _allocate_tuid(self, msg, subject_root=None, tuid=None):
        if subject_root is None:
            subject_root = msg.get_subject_stem()

        timestamp = int(msg.timestamp)
        if tuid is None:
            c = self.db.execute('INSERT INTO threads '
                                '(subject, start_time, end_time) '
                                'VALUES (?, ?, ?)',
                                (subject_root, timestamp, timestamp))
            tuid = self._tuid_from_db(c.lastrowid)
        else:
            assert isinstance(tuid, TUID)
            self.db.execute('INSERT INTO threads '
                            '(tuid, subject, start_time, end_time) '
                            'VALUES (?, ?, ?, ?)',
                            (tuid, subject_root, timestamp, timestamp))

        return tuid

    def _muid_from_db(self, internal_id):
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
        id_suffix = value[len(self.muid_prefix):]
        return MUID(self, int(id_suffix))

    def _tuid_from_db(self, internal_id):
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
        id_suffix = value[len(self.tuid_prefix):]
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

    def __eq__(self, other):
        return isinstance(other, MUID) and self._value == other._value

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self._value)


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

    def __eq__(self, other):
        return isinstance(other, TUID) and self._value == other._value

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self._value)
