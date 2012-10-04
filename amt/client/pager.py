#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import time

from amt.term import widgets

from .mode import MailMode


class MailPager(widgets.Pager):
    def __init__(self, region, msg):
        super(MailPager, self).__init__(region)
        self.msg = msg

        self.add_line('{+:red}From: {}', self.msg.from_addr)
        self.add_line('{+:red}To: {}', self.msg.to)
        self.add_line('{+:red}Cc: {}', self.msg.cc)
        time_str = time.ctime(self.msg.timestamp)
        self.add_line('{+:cyan}Date: {}', time_str)
        self.add_line('{+:green}Subject: {}', self.msg.subject)
        self.add_line('')
        for line in self.msg.body_text.splitlines():
            self.add_line('{}', line)


class MessageMode(MailMode):
    def __init__(self, region, mdb, muid):
        super(MessageMode, self).__init__(region)
        self.mdb = mdb

        locations = self.mdb.get_locations(muid)
        self.msg = locations[0].load_msg()

        self.pager = MailPager(self.main_region, self.msg)
        self.init_bindings()

    def init_bindings(self):
        self.default_bindings = {
            'i': self.cmd_quit_mode,
            'q': self.cmd_quit,
        }
        self.key_bindings = self.default_bindings.copy()

    def _redraw(self):
        self.set_header('{+:fg=white,bg=blue}Msg Mode{=}AMT')
        self.pager.redraw()
        self.set_footer('{+:fg=white,bg=blue}Msg Mode{=}AMT')
        self.clear_msg(flush=False)
