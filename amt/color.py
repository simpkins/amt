#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import curses

DEFAULT = -1
BLACK = 0
RED = 1
GREEN = 2
YELLOW = 3
BLUE = 4
MAGENTA = 5
CYAN = 6
WHITE = 7


def init():
    curses.start_color()
    curses.use_default_colors()

    global BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE
    BLACK = curses.COLOR_BLACK
    RED = curses.COLOR_RED
    GREEN = curses.COLOR_GREEN
    YELLOW = curses.COLOR_YELLOW
    BLUE = curses.COLOR_BLUE
    MAGENTA = curses.COLOR_MAGENTA
    CYAN = curses.COLOR_CYAN
    WHITE = curses.COLOR_WHITE
