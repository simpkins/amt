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
from amt.term.widgets import Drawable


class QuitError(Exception):
    pass


class QuitModeError(Exception):
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


class MailPager(Drawable):
    def __init__(self, region, msg):
        super(MailPager, self).__init__(region)
        self.msg = msg

    def _redraw(self):
        self.region.clear()


class MailMode(Drawable):
    def __init__(self, region):
        super(MailMode, self).__init__(region)

        self.header = self.subregion(0, 0, 0, 1)
        self.footer = self.subregion(0, -2, 0, 1)
        self.msg_area = self.subregion(0, -1, 0, 1)
        self.main_region = self.subdrawable(0, 1, 0, -2)

    def run(self):
        assert self.visible
        self.redraw()

        while True:
            ch = self.term.getch()
            try:
                self.process_key(ch)
            except QuitModeError:
                return

    def process_key(self, key):
        cmd = self.key_bindings.get(key)
        if cmd is None:
            self.user_msg('no binding for key: {!r}', key)
            return

        cmd()

    def set_header(self, fmt, *args, **kwargs):
        self.header.vwriteln(0, fmt, args, kwargs)

    def set_footer(self, fmt, *args, **kwargs):
        self.footer.vwriteln(0, fmt, args, kwargs)

    def clear_msg(self, flush=True):
        self.msg_area.vwriteln(0, '', (), {})
        if flush:
            self.term.flush()

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

    def cmd_quit_mode(self):
        raise QuitModeError()


class MessageMode(MailMode):
    def __init__(self, region, mdb, msg):
        super(MessageMode, self).__init__(region)
        self.mdb = mdb
        self.msg = msg
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
            term.KEY_CTRL_L: self.cmd_redraw,
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
        with self.term.program_mode(altscreen=self.args.altscreen) as region:
            index_mode = IndexMode(region, self.mdb)
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
