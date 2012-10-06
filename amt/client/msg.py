#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import datetime

from ..containers import WeakrefSet


class IndexMsg:
    def __init__(self, mdb, muid, tuid, subject,
                 from_name, from_addr, timestamp):
        self.mdb = mdb
        self.muid = muid
        self.tuid = tuid
        self.subject = subject
        self.from_name = from_name
        self.from_addr = from_addr
        self.timestamp = timestamp
        self._datetime = None

        self.__msg = None

    @property
    def msg(self):
        if self.__msg is None:
            locations = self.mdb.get_locations(self.muid)
            self.__msg = locations[0].load_msg()

        return self.__msg

    def datetime(self):
        if self._datetime is None:
            self._datetime = datetime.datetime.fromtimestamp(self.timestamp)
        return self._datetime


class IndexThread:
    def __init__(self, msg):
        self.tuid = msg.tuid
        self.start_time = msg.timestamp
        self.end_time = msg.timestamp
        self.msgs = [msg]

    def add_msg(self, msg):
        assert msg.tuid == self.tuid
        self.start_time = min(self.start_time, msg.timestamp)
        self.end_time = max(self.end_time, msg.timestamp)
        self.msgs.append(msg)

    def resolve_msg_tree(self):
        # TODO: figure out parent/child and sibling relationships
        self.msgs.sort(key=lambda m: m.timestamp)


class MsgListSubscriber:
    def msg_list_changed(self):
        '''
        Called when the message list changes (is resorted, has a message
        added or removed, etc).
        '''
        pass

    def msg_index_changed(self):
        '''
        Called when the current message index changes.
        '''
        pass


class MsgList:
    def __init__(self, mdb):
        self.mdb = mdb
        self.__cur_idx = 0
        self.subscribers = WeakrefSet()

        self._load_msgs()

    def _load_msgs(self):
        cursor = self.mdb.db.execute(
                'SELECT muid, tuid, subject, from_name, from_addr, timestamp '
                'FROM messages '
                'ORDER BY tuid')
        msgs = [IndexMsg(self.mdb, *items) for items in cursor]
        self.threads = []

        current_thread = None
        for msg in msgs:
            if current_thread is None:
                current_thread = IndexThread(msg)
            elif msg.tuid == current_thread.tuid:
                current_thread.add_msg(msg)
            else:
                self.threads.append(current_thread)
                current_thread = IndexThread(msg)

        if current_thread is not None:
            self.threads.append(current_thread)

        self.threads.sort(key=lambda t: t.end_time)
        self.msgs = []
        for thread in self.threads:
            thread.resolve_msg_tree()
            for msg in thread.msgs:
                self.msgs.append(msg)

    @property
    def cur_idx(self):
        return self.__cur_idx

    def current_msg(self):
        if not self.msgs:
            return None
        return self.msgs[self.__cur_idx]

    def __len__(self):
        return len(self.msgs)

    def __iter__(self):
        return iter(self.msgs)

    def __getitem__(self, idx):
        return self.msgs[idx]

    def add_subscriber(self, subscriber):
        self.subscribers.add(subscriber)

    def rm_subscriber(self, subscriber):
        self.subscribers.remove(subscriber)

    def move(self, amount, throw_on_error=False):
        '''
        Adjust the message index by the specified amount.
        '''
        idx = self.cur_idx + amount
        if idx < 0:
            if throw_on_error:
                raise IndexError('attempted to move the current index by %d '
                                 'to a negative location: %d' %
                                 (amount, idx))
            idx = 0
        elif idx >= len(self.msgs):
            if throw_on_error:
                raise IndexError('attempted to move the current index by %d '
                                 'to %d, which is too large (num_msgs=%d)' %
                                 (amount, idx, len(self.msgs)))
            idx = len(self.msgs) - 1

        self.__update_idx(idx)

    def goto(self, idx, throw_on_error=False):
        '''
        Move the current message index to the specified location
        '''
        orig_idx = idx
        if idx < 0:
            idx = len(self.msgs) + idx

        if idx < 0:
            if throw_on_error:
                raise IndexError('attempted to move the current index to %d, '
                                 'which is a negative location (num_msgs=%d)' %
                                 (orig_idx, len(self.msgs)))
            idx = 0
        elif idx >= len(self.msgs):
            if throw_on_error:
                raise IndexError('attempted to move the current index '
                                 'to %d, which is too large (num_msgs=%d)' %
                                 (orig_idx, len(self.msgs)))
            idx = len(self.msgs) - 1

        self.__update_idx(idx)

    def __update_idx(self, idx):
        self.__cur_idx = idx
        for subscriber in self.subscribers:
            subscriber.msg_index_changed()


class MsgFormatArgs:
    DOESNT_EXIST = object()
    SHORT_MONTHS = [
        'INVALID',
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
    ]

    def __init__(self, idx, idx_msg):
        self.idx = idx
        self.idx_msg = idx_msg

    def __getitem__(self, name):
        result = getattr(self, name, self.DOESNT_EXIST)
        if result != self.DOESNT_EXIST:
            return result

        result = self._compute_item(name)

        setattr(self, name, result)
        return result

    def _compute_item(self, name):
        if name == 'from':
            result = self.idx_msg.from_name
            if result:
                return result
            return self.idx_msg.from_addr
        if name == 'subject':
            # Replace folding whitespace with a single space
            # TODO: We probably should have the message code do this
            # automatically when parsing headers, since we want to do this in
            # more places than just here.
            return self.idx_msg.subject.replace('\n ', ' ')
        if name == 'date':
            return self._compute_date()

        raise KeyError('no such item "%s"' % (name,))

    def _compute_date(self):
        dt = self.idx_msg.datetime()
        return '%s %02d' % (self.SHORT_MONTHS[dt.month], dt.day)
