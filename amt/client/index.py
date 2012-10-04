#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import datetime
import functools

import amt.term
from amt.term import widgets

from .mode import MailMode
from .pager import MessageMode


class IndexMode(MailMode):
    def __init__(self, region, mdb):
        super(IndexMode, self).__init__(region)
        self.mdb = mdb
        self.mail_index = MailIndex(self.main_region, self.mdb)
        self.init_bindings()

    def init_bindings(self):
        self.default_bindings = {
            'q': self.cmd_quit,
            'j': self.cmd_move_down,
            'k': self.cmd_move_up,
            'J': self.cmd_page_down,
            'K': self.cmd_page_up,
            '*': self.cmd_goto_last,
            '\r': self.cmd_show_msg,
            amt.term.KEY_CTRL_L: self.cmd_redraw,
            ':': self.cmd_read_cmd
        }
        for key in ('0', '1', '2', '3', '4', '5', '6', '7', '8', '9'):
            self.default_bindings[key] = functools.partial(self.cmd_goto,
                                                           first_char=key)

        self.key_bindings = self.default_bindings.copy()

    def _redraw(self):
        self.set_header('{+:fg=white,bg=blue}AMT{=}AMT')
        self.mail_index.redraw()
        self.set_footer('{+:fg=white,bg=blue}AMT{=}AMT')
        self.clear_msg(flush=False)

    def cmd_move_down(self):
        self.mail_index.move_down()

    def cmd_move_up(self):
        self.mail_index.move_up()

    def cmd_page_down(self):
        self.mail_index.page_down()

    def cmd_page_up(self):
        self.mail_index.page_up()

    def cmd_goto_last(self):
        self.mail_index.goto(-1)

    def cmd_redraw(self):
        self.redraw()

    def cmd_show_msg(self):
        self.set_visible(False)

        msg_mode = MessageMode(self.region.region(0, 0), self.mdb,
                               self.mail_index.current_muid())
        msg_mode.run()

        self.set_visible(True)

    def cmd_goto(self, first_char=None):
        line = self.readline(prompt='Go To: ', first_char=first_char)

        try:
            idx = int(line)
        except ValueError:
            self.user_msg('Invalid message number {!r}', line)
            return

        if idx < 0 or idx >= self.mail_index.get_num_items():
            self.user_msg('Invalid message number {}', idx)
            return

        self.mail_index.goto(idx)

    def cmd_read_cmd(self, first_char=None):
        line = self.readline(': ')
        # TODO: support actually parsing and running commands
        self.user_msg('got line: {!r}', line)


class MailIndex(widgets.ListSelection):
    def __init__(self, region, mdb):
        super(MailIndex, self).__init__(region)
        self.mdb = mdb

        cursor = mdb.db.execute(
                'SELECT muid, tuid, subject, from_name, from_addr, timestamp '
                'FROM messages '
                'ORDER BY tuid')
        self.msgs = [IndexMsg(*items) for items in cursor]

    def current_muid(self):
        return self.msgs[self.cur_idx].muid

    def get_num_items(self):
        return len(self.msgs)

    def get_item_format(self, item_idx, selected):
        msg = self.msgs[item_idx]

        num_width = len(str(len(self.msgs)))
        fmt = '{idx:red:>%d} {date::<6} {from::20.20} {subject}' % (num_width,)
        kwargs = MsgFormatArgs(item_idx, msg)

        if selected:
            fmt = '{+:reverse}' + fmt
        return fmt, kwargs


class IndexMsg:
    def __init__(self, muid, tuid, subject, from_name, from_addr, timestamp):
        self.muid = muid
        self.tuid = tuid
        self.subject = subject
        self.from_name = from_name
        self.from_addr = from_addr
        self.timestamp = timestamp
        self._datetime = None

    def datetime(self):
        if self._datetime is None:
            self._datetime = datetime.datetime.fromtimestamp(self.timestamp)
        return self._datetime


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
