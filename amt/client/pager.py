#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import time

from amt.term import widgets

from .mode import MailMode
from .msg import MsgListSubscriber


class MailPager(widgets.Pager):
    def __init__(self, region, msg):
        super(MailPager, self).__init__(region)
        self.change_msg(msg)

    def change_msg(self, msg):
        self.msg = msg
        self.clear_lines()

        self.add_line('{+:red}From: {}', self.msg.from_addr)
        self.add_line('{+:red}To: {}', self.msg.to)
        self.add_line('{+:red}Cc: {}', self.msg.cc)
        time_str = time.ctime(self.msg.timestamp)
        self.add_line('{+:cyan}Date: {}', time_str)
        self.add_line('{+:green}Subject: {}', self.msg.subject)
        self.add_line('')
        for line in self.msg.body_text.splitlines():
            self.add_line('{}', line)

        self.redraw()


class MessageMode(MailMode, MsgListSubscriber):
    def __init__(self, region, mdb, msgs):
        super(MessageMode, self).__init__(region)
        self.mdb = mdb
        self.msgs = msgs
        self.msgs.add_subscriber(self)

        self.idx_msg = self.msgs.current_msg()
        full_msg = self.idx_msg.msg

        self.pager = MailPager(self.main_region, full_msg)
        self.init_bindings()

    def init_bindings(self):
        self.default_bindings = {
            'i': self.cmd_quit_mode,
            'j': self.cmd_next_msg,
            'k': self.cmd_prev_msg,
            'q': self.cmd_quit,
        }
        self.key_bindings = self.default_bindings.copy()

    def cmd_next_msg(self):
        self.msgs.move(1)

    def cmd_prev_msg(self):
        self.msgs.move(-1)

    def msg_list_changed(self):
        self.msg_changed()

    def msg_index_changed(self):
        self.msg_changed()

    def msg_changed(self):
        if not self.visible:
            return

        cur_msg = self.msgs.current_msg()
        if cur_msg is None:
            self.pager.clear_lines()
            return
        self.pager.change_msg(cur_msg.msg)

    def _redraw(self):
        self.set_header('{+:fg=white,bg=blue}Msg Mode{=}AMT')
        self.pager.redraw()
        self.set_footer('{+:fg=white,bg=blue}Msg Mode{=}AMT')
        self.clear_msg(flush=False)

    def leave_mode(self):
        self.msgs.rm_subscriber(self)
