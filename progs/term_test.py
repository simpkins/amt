#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(sys.path[0]))
from amt.term import Terminal
import amt.term.widgets as term_widgets
import amt.term.keys as term_keys


class CatchallDrawable(term_widgets.Drawable):
    def _redraw(self):
        region = self.region

        # Test some simple attributes and padding
        region.writeln(0, '{"ABCDEF":red,underline}{=:underline}one '
                       '{+:blue}third {=weight=2}'
                       '{"Right Justified":red} Text!')
        region.writeln(1, '{+:white,bg=blue}This is {:underline} text',
                       'some test')
        region.writeln(2, "This is a {'long':italic} line: {:red}",
                       '123456' * 200)

        # Test multi-cell characters
        multicell = 'fullwidth'
        multicell = ''.join(chr(0xfee0 + ord(c)) for c in multicell)
        region.writeln(4, 'This line has {} characters:\t{:green}',
                       multicell, 'abcdef' * 100)
        # Test truncation on multicell characters.  Write two lines,
        # where the multicell characters are off by one character on each.
        # This way one of the lines will have to be truncated in the middle of
        # a character.
        region.writeln(5, 'truncate on {"fullwidth":underline}: {:cyan}',
                       multicell * 100)
        region.writeln(6, 'truncate on {"fullwidth2":bold}: {:cyan}',
                       multicell * 100)

        region.writeln(8, 'writeln() will truncate after a newline\n'
                       'this text should not appear')

        for n in range(10, region.height - 2):
            region.writeln(n, 'Line {}', n)
        region.writeln(region.height - 1, 'Long final line: {}',
                       'abcdef_' * 100)


class HistoryDrawable(term_widgets.Drawable):
    def __init__(self, param):
        super().__init__(param)
        self.history = []

    def _redraw(self):
        for n, c in enumerate(self.history):
            self.region.writeln(n, 'Got: {!r}', c)

    def append(self, entry):
        self.history.append(entry)
        if len(self.history) > self.region.height:
            self.history.pop(0)

        self.redraw()


def catchall_example(root):
    num_hist_lines = 5
    history = HistoryDrawable(root.region(0, 0, height=num_hist_lines))
    drawable = CatchallDrawable(root.region(20, 5))
    drawable.redraw()

    while True:
        c = root.term.getch()
        if c == 'q' or c == term_keys.KEY_ESCAPE:
            return

        history.append(c)


def input_example(root):
    history = HistoryDrawable(root)
    history.redraw()
    while True:
        c = root.term.getch()
        if c == 'q' or c == term_keys.KEY_ESCAPE:
            return

        history.append(c)


def full_screen_example(args):
    examples = [
        ('Input', input_example),
        ('Catch-All', catchall_example),
    ]
    example_names = [entry[0] for entry in examples]

    term = Terminal()
    with term.program_mode(altscreen=args.altscreen) as root:
        l = term_widgets.FixedListSelection(root, example_names)
        l.redraw()
        while True:
            c = term.getch()
            if c == 'q':
                return
            elif c == 'j' or c == term_keys.KEY_DOWN:
                l.move_down()
            elif c == 'k' or c == term_keys.KEY_UP:
                l.move_up()
            elif c == '\n' or c == '\r':
                l.set_visible(False)
                term.clear()
                example_fn = examples[l.cur_idx][1]
                example_fn(root)
                l.set_visible(True)


def partial_screen_example(args):
    term = Terminal()
    with term.program_mode(altscreen=args.altscreen, height=4) as root:
        root.writeln(0, 'The time is now:')
        while True:
            root.writeln(2, '  {}', time.ctime())
            term.flush()
            time.sleep(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-p', '--partial', action='store_true', default=False,
                    help='Run the partial screen example')
    ap.add_argument('-a', '--altscreen', action='store_true', default=False,
                    help='Enable alternate screen mode')
    args = ap.parse_args()

    try:
        if args.partial:
            partial_screen_example(args)
        else:
            full_screen_example(args)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
