#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import datetime
import functools

import amt.term
from amt.term import widgets

from .mode import MailMode
from .msg import MsgFormatArgs, MsgListSubscriber
from .pager import MessageMode


class IndexMode(MailMode):
    def __init__(self, region, mdb, msgs):
        super(IndexMode, self).__init__(region)
        self.mdb = mdb
        self.msgs = msgs
        self.mail_index = MailIndex(self.main_region, self.msgs)
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
        self.msgs.move(1)

    def cmd_move_up(self):
        self.msgs.move(-1)

    def cmd_page_down(self):
        amount = self.mail_index.get_page_lines()
        self.msgs.move(amount)

    def cmd_page_up(self):
        amount = -self.mail_index.get_page_lines()
        self.msgs.move(amount)

    def cmd_goto_last(self):
        self.msgs.goto(-1)

    def cmd_redraw(self):
        self.redraw()

    def cmd_show_msg(self):
        self.set_visible(False)

        msg_mode = MessageMode(self.region.region(0, 0), self.mdb, self.msgs)
        msg_mode.run()

        self.set_visible(True)

    def cmd_goto(self, first_char=None):
        line = self.readline(prompt='Go To: ', first_char=first_char)

        try:
            idx = int(line)
        except ValueError:
            self.user_msg('Invalid message number {!r}', line)
            return

        if idx < 0 or idx >= len(self.msgs):
            self.user_msg('Invalid message number {}', idx)
            return

        self.msgs.goto(idx)

    def cmd_read_cmd(self, first_char=None):
        line = self.readline(': ')
        # TODO: support actually parsing and running commands
        self.user_msg('got line: {!r}', line)


class MailIndex(widgets.ListSelection, MsgListSubscriber):
    def __init__(self, region, msgs):
        super(MailIndex, self).__init__(region)
        self.msgs = msgs
        self.msgs.add_subscriber(self)

    def current_muid(self):
        return self.msgs[self.cur_idx].muid

    def get_num_items(self):
        return len(self.msgs)

    def get_item_format(self, item_idx, selected):
        msg = self.msgs[item_idx]

        num_width = len(str(len(self.msgs)))
        fmt = '{idx:red:>%d} {date::<6} {from::20.20} {subject}' % (num_width,)

        if selected:
            fmt = '{+:reverse}' + fmt
        return fmt, MsgFormatArgs(item_idx, msg)

    def msg_index_changed(self):
        self.goto(self.msgs.cur_idx, flush=True)

    def msg_list_changed(self):
        pass
