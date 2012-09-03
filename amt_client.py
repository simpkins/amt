#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import sys

# Import readline if it is available, so input() will have
# nicer line editing functionality.
try:
    import readline
except ImportError:
    pass

import amt.config
from amt.maildb import MailDB, MaildirLocation, Location
from amt.maildir import Maildir
from amt.message import Message
from amt import term
from amt.term import widgets


class MailIndex(widgets.ListSelection):
    def __init__(self, region, mdb):
        super(MailIndex, self).__init__(region)
        self.mdb = mdb

        cursor = mdb.db.execute('SELECT muid, tuid, subject, timestamp '
                                'FROM messages '
                                'ORDER BY tuid')
        self.msgs = list(cursor)

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



class MUA:
    def __init__(self, args, mdb):
        self.args = args
        self.mdb = mdb
        self.term = term.Terminal()

    def on_resize(self):
        self.draw_headers()

    def redraw(self, flush=True):
        self.draw_headers()
        self.mail_index.redraw()
        if flush:
            self.term.flush()

    def draw_headers(self):
        self.header.writeln(0, '{+:fg=white,bg=blue}AMT{=}AMT')
        self.footer.writeln(0, '{+:fg=white,bg=blue}AMT{=}AMT')

    def run(self):
        with self.term.program_mode(altscreen=self.args.altscreen) as root:
            self.term.on_resize = self.on_resize
            self.root = root
            self.header = root.region(0, 0, 0, 1)
            self.main_region = root.region(0, 1, 0, -2)
            self.footer = root.region(0, -2, 0, 1)
            self.msg_area = root.region(0, -1, 0, 1)

            self.mail_index = MailIndex(self.main_region, self.mdb)
            self.redraw()

            while True:
                ch = self.term.getch()
                if ch == 'q':
                    break
                elif ch == 'j':
                    self.mail_index.move_down()
                elif ch == 'k':
                    self.mail_index.move_up()
                elif ch == 'J':
                    self.mail_index.page_down()
                elif ch == 'K':
                    self.mail_index.page_up()
                elif ch == '*':
                    self.mail_index.goto(-1)
                elif ch == '\r':
                    pass
                elif ch == term.KEY_CTRL_L:
                    self.redraw()
                elif ch in ('0', '1', '2', '3', '4', '5', '6', '7', '8', '9'):
                    def startup_hook():
                        readline.insert_text(ch)
                        readline.set_startup_hook(None)
                    readline.set_startup_hook(startup_hook)

                    with self.term.shell_mode():
                        line = input('Go To: ')

                    try:
                        idx = int(line)
                        if idx < 0 or idx >= self.mail_index.get_num_items():
                            raise ValueError()
                    except ValueError:
                        self.msg_area.writeln(0, 'Invalid message number {}',
                                              line)
                        self.term.flush()
                        continue
                    self.mail_index.goto(idx)
                elif ch == ':':
                    self.term.flush()
                    with self.term.shell_mode():
                        line = input(': ')
                        pass
                    self.msg_area.writeln(0, 'got line: {!r}', line)
                    self.term.flush()


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
