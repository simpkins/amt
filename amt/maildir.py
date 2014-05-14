#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
'''
Module to provide access to maildir mailboxes.

Python includes maildir support in the standard mailbox module, but it doesn't
provide quite enough control over the files and refreshing mechanisms for my
purposes.
'''

import email.generator
import errno
import itertools
import logging
import os
import re
import socket
import stat
import struct
import time

# A count of how many maildir messages this process has used
# We use itertools.count() since it is thread-safe
global_delivery_count = itertools.count()
next(global_delivery_count) # Start at 1 rather than 0


class MaildirError(Exception):
    pass


class Maildir:
    def __init__(self, path, create=False):
        self.path = path
        self._hostname = None

        try:
            s = os.stat(path)
            if not stat.S_ISDIR(s.st_mode):
                raise MaildirError('%s is not a directory' % path)
            exists = True
        except OSError as ex:
            if ex.errno == errno.ENOENT:
                exists = False
            else:
                raise

        if exists:
            self._check_subdirs()
        else:
            if not create:
                raise MaildirError('%s does not exist' % path)
            self._create()

    def _create(self):
        os.makedirs(self.path)
        for subdir in ('cur', 'new', 'tmp'):
            os.mkdir(os.path.join(self.path, subdir))

    def _check_subdirs(self):
        for subdir in ('cur', 'new', 'tmp'):
            full_subdir = os.path.join(self.path, subdir)
            try:
                s = os.lstat(full_subdir)
            except OSError as ex:
                raise MaildirError('error checking subdirectory %s: %s' %
                                   (full_subdir, ex))
            if not stat.S_ISDIR(s.st_mode):
                raise MaildirError('error checking subdirectory %s: %s' %
                                   (full_subdir, 'must be a directory'))

    def list(self):
        '''
        maildir.list() --> [(key --> filename)]

        Return a dictionary with one entry per message in the mailbox.
        The keys are the unique portion of the maildir filename, and the values
        are the full path to the message (with maildir.path as a prefix).

        list() scans the filesystem each time it is called; it does not perform
        any caching.
        '''
        for subdir in ('new', 'cur'):
            full_subdir = os.path.join(self.path, subdir)
            for entry in os.listdir(full_subdir):
                full_entry = os.path.join(full_subdir, entry)
                key = entry.split(':', 1)[0]
                yield key, full_entry

    def list_dict(self):
        return dict(self.list())

    def add(self, msg):
        key, tmp_path, tmp_file = self.get_tmp_file()
        dest_path = self._get_dest_path(msg, key)

        msg.serialize_bytes(tmp_file)
        tmp_file.flush()
        os.fsync(tmp_file.fileno())

        if msg.timestamp:
            os.utime(tmp_path, (os.path.getatime(tmp_path), msg.timestamp))

        tmp_file.close()

        os.link(tmp_path, dest_path)
        os.unlink(tmp_path)

        logging.debug('added maildir message %s at path %s', key, dest_path)
        return dest_path

    def copy(self, msg, path):
        '''
        Copy a message into this maildir from another maildir.
        '''
        # Since the message is already fully written in the other maildir,
        # we link directly into the desired cur or new subdirectory.
        attempt = 0
        while True:
            attempt += 1
            if attempt > 3:
                raise MaildirError('unable to deliver new file for copy: '
                                   'too many collisions')
            key = self.get_new_key()
            dest_path = self._get_dest_path(msg, key)
            try:
                os.link(path, dest_path)
                break
            except OSError as ex:
                if ex.errno != errno.EEXIST:
                    raise

        logging.debug('copied maildir message %s at path %s', key, dest_path)
        return dest_path

    def _get_dest_path(self, msg, key):
        if msg.FLAG_NEW in msg.flags:
            subdir = 'new'
        else:
            subdir = 'cur'

        info = msg.compute_maildir_info()
        if info:
            dest_name = '%s:%s' % (key, info)
        else:
            dest_name = key

        return os.path.join(self.path, subdir, dest_name)

    def get_tmp_file(self):
        '''
        get_tmp_file() --> (key, path, file)

        Create a new file in the tmp subdirectory for writing a new message.
        '''
        attempt = 0
        while True:
            attempt += 1
            if attempt > 3:
                raise MaildirError('unable to create new temporary file: '
                                   'too many collisions')

            key = self.get_new_key()
            path = os.path.join(self.path, 'tmp', key)
            try:
                fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o666)
                break
            except OSException as ex:
                if ex.errno == errno.EEXIST:
                    time.sleep(2)
                    continue
                else:
                    raise

        logging.debug('new tmp file: %d --> %s', fd, path)
        return key, path, os.fdopen(fd, 'wb')

    def get_new_key(self):
        '''
        Get a new unique key for storing a maildir message.
        '''
        # See instructions from http://cr.yp.to/proto/maildir.html
        now = time.time()
        left = str(int(now))
        right = self._get_hostname()
        middle = self._get_key_middle(now)

        return '.'.join((left, middle, right))

    def _get_hostname(self):
        if self._hostname is None:
            hostname = socket.gethostname()
            hostname = re.sub('/', '\\057', hostname)
            hostname = re.sub(':', '\\072', hostname)
            self._hostname = hostname

        return self._hostname

    def _get_key_middle(self, now):
        parts = []

        # M: microseconds
        usecs = (now % 1) * 1000000
        parts.append('M%d' % usecs)

        # P: process ID
        parts.append('P%d' % os.getpid())

        # Q: process delivery count
        global global_delivery_count
        parts.append('Q%d' % next(global_delivery_count))

        # R: OS-generated pseudo-random number
        try:
            rand = struct.unpack('I', os.urandom(4))[0]
            parts.append('R%d' % rand)
        except NotImplementedError:
            # os.urandom() is not available
            pass

        return ''.join(parts)
