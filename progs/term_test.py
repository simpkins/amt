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


def draw(region):
    term = region.term

    region.writeln(0, '{"ABCDEF":red,underline}{=:underline}one {+:blue}third'
                   '{=weight=2}{"Right Justified":red} Text!')
    region.writeln(1, '{+:white,bg=blue}This is {:underline} text',
                   'some test')
    region.writeln(2, "This is a {'long':italic} line: {:red}",
                   '123456' * 200)
    for n in range(3, region.height - 1):
        region.writeln(n, 'Line {}', n)
    region.writeln(region.height - 1, 'Long final line: {}',
                   'abcdef_' * 100)


def full_screen_example(args):
    def on_resize():
        term.clear()
        draw(region)
        term.flush()

    term = Terminal()
    with term.program_mode(altscreen=args.altscreen) as root:
        term.on_resize = on_resize
        region = term.region(20, 5)
        draw(region)
        term.flush()

        history = []
        while True:
            c = term.getch()
            history.append(c)
            if len(history) > 10:
                history.pop(0)

            for n, c in enumerate(history):
                root.writeln(n, 'Got: {!r::<10}', c)
            term.flush()


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
