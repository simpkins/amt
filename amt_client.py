#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import functools
import readline
import sys

import amt.config
from amt.maildb import MailDB, MaildirLocation, Location
from amt.maildir import Maildir
from amt.message import Message
from amt import term
from amt.term import widgets


class QuitError(Exception):
    pass


class MailIndex(widgets.ListSelection):
    def __init__(self, region, mdb):
        super(MailIndex, self).__init__(region)
        self.mdb = mdb

        cursor = mdb.db.execute('SELECT muid, tuid, subject, timestamp '
                                'FROM messages '
                                'ORDER BY tuid')
        self.msgs = list(cursor)

    def current_msg(self):
        return self.msgs[self.cur_idx]

    def get_num_items(self):
        return len(self.msgs)

    def get_item_format(self, item_idx, selected):
        msg = self.msgs[item_idx]

        num_width = len(str(len(self.msgs)))
        fmt = '{idx:red:>%d} {msg}' % (num_width,)
        kwargs = {'idx': item_idx, 'msg': msg}

        if selected:
            fmt = '{+:reverse}' + fmt
        return fmt, kwargs


class MailPager:
    def __init__(self, region, msg):
        self.visible = True
        self.region = region
        self.msg = msg
        self.region.on_resize = self._on_resize

    def _on_resize(self):
        if not self.visible:
            return
        self.redraw(flush=False)

    def redraw(self, flush=True):
        assert self.visible

        self.region.clear()

        if flush:
            self.region.term.flush()


class MessageMode:
    def __init__(self, region, mdb, msg):
        self.visible = True
        self.root = region
        self.term = self.root.term
        self.mdb = mdb
        self.msg = msg

        self.header = self.root.region(0, 0, 0, 1)
        self.footer = self.root.region(0, -2, 0, 1)
        self.msg_area = self.root.region(0, -1, 0, 1)

        main_region = self.root.region(0, 1, 0, -2)
        self.pager = MailPager(main_region, self.msg)

        self.root.on_resize = self.on_resize

    def run(self):
        assert self.visible

        self.redraw()

        while True:
            ch = self.term.getch()
            # self.process_key(ch)
            return

    def on_resize(self):
        if not self.visible:
            return

        # Just redraw the headers.
        # self.pager will redraw itself automatically
        self.draw_headers()

    def draw_headers(self):
        assert self.visible
        self.header.writeln(0, '{+:fg=white,bg=blue}Msg Mode{=}AMT')
        self.footer.writeln(0, '{+:fg=white,bg=blue}Msg Mode{=}AMT')

    def redraw(self, flush=True):
        assert self.visible
        self.draw_headers()
        self.pager.redraw()
        if flush:
            self.term.flush()


class IndexMode:
    def __init__(self, region, mdb):
        self.visible = True
        self.root = region
        self.term = self.root.term
        self.mdb = mdb

        self.init_bindings()

        self.header = self.root.region(0, 0, 0, 1)
        self.footer = self.root.region(0, -2, 0, 1)
        self.msg_area = self.root.region(0, -1, 0, 1)

        main_region = self.root.region(0, 1, 0, -2)
        self.mail_index = MailIndex(main_region, self.mdb)

        self.root.on_resize = self.on_resize

    def init_bindings(self):
        self.default_bindings = {
            'q': self.cmd_quit,
            'j': self.cmd_move_down,
            'k': self.cmd_move_up,
            'J': self.cmd_page_down,
            'K': self.cmd_page_up,
            '*': self.cmd_goto_last,
            '\r': self.cmd_show_msg,
            term.KEY_CTRL_L: self.cmd_redraw,
            ':': self.cmd_read_cmd
        }
        for key in ('0', '1', '2', '3', '4', '5', '6', '7', '8', '9'):
            self.default_bindings[key] = functools.partial(self.cmd_goto,
                                                           first_char=key)

        self.bindings = self.default_bindings.copy()

    def set_visible(self, visible):
        if visible == self.visible:
            return

        self.visible = visible
        self.mail_index.visible = visible
        if self.visible:
            self.redraw()

    def run(self):
        assert self.visible

        self.redraw()

        while True:
            ch = self.term.getch()
            self.process_key(ch)

    def on_resize(self):
        if not self.visible:
            return

        # Just redraw the headers.
        # self.mail_index will redraw itself automatically
        self.draw_headers()

    def draw_headers(self):
        assert self.visible
        self.header.writeln(0, '{+:fg=white,bg=blue}AMT{=}AMT')
        self.footer.writeln(0, '{+:fg=white,bg=blue}AMT{=}AMT')

    def redraw(self, flush=True):
        assert self.visible
        self.draw_headers()
        self.mail_index.redraw()
        if flush:
            self.term.flush()

    def process_key(self, key):
        cmd = self.bindings.get(key)
        if cmd is None:
            self.user_msg('no binding for key: {!r}', key)
            return

        cmd()

    def user_msg(self, fmt, *args, **kwargs):
        self.msg_area.vwriteln(0, fmt, args, kwargs)
        self.term.flush()

    def readline(self, prompt, first_char=None):
        if first_char is not None:
            def startup_hook():
                readline.insert_text(first_char)
                readline.set_startup_hook(None)
            readline.set_startup_hook(startup_hook)

        with self.term.shell_mode():
            line = input(prompt)

        return line

    def cmd_quit(self):
        raise QuitError()

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

        msg_mode = MessageMode(self.root.region(0, 0), self.mdb,
                               self.mail_index.current_msg())
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



class MUA:
    def __init__(self, args, mdb):
        self.args = args
        self.mdb = mdb
        self.term = term.Terminal()

    def run(self):
        with self.term.program_mode(altscreen=self.args.altscreen) as root:
            self.root = root

            index_mode = IndexMode(self.root, self.mdb)
            try:
                index_mode.run()
            except QuitError:
                return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-m', '--maildb', metavar='PATH',
                    help='The path to the MailDB')
    ap.add_argument('-a', '--altscreen', action='store_true', default=False,
                    help='Use the terminal\'s alternate screen mode')
    args = ap.parse_args()

    if not args.maildb:
        args.maildb = amt.config.default_maildb_path()

    mdb = MailDB.open_db(args.maildb)

    mua = MUA(args, mdb)
    mua.run()


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
