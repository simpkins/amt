#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
# Helper module for interacting with a terminal.  Aims to be more user-friendly
# than curses.
#
# I've played around a bit with using curses versus directly writing to the
# terminal.  For now, this code accesses the terminal directly rather than
# using curses.
#
# Pros of writing directly to the terminal:
# - Can choose whether to use smcup/rmcup (alternate screen mode in xterm)
# - The same API can be used to write programs that want to set text attributes
#   and perform some simple cursor motion, but don't want fullscreen mode.
#
# The downsides:
# - You lose curses' window buffering functionality.  This doesn't seem like
#   that big of a problem--it simply requires that applications know how to
#   redraw themselves when needed.  This seems like it is necessary anyway
#   to handle terminal resizing.
# - We have to implement a bit more of our own code for knowing how to change
#   the terminal state from one set of attributes to another.
# - We can't use curses' input processing functionality.  This one is a bit of
#   a hassle: we have to implement our own escape code processing.  However,
#   python doesn't provide get_wch() yet (hopefully a usable version will be
#   coming in 3.3), so we have to do some processing for this anyway to support
#   this in a reasonable manner.  I haven't implemented mouse input yet.

import curses
import errno
import fcntl
import os
import signal
import struct
import termios
import weakref
import sys
from contextlib import contextmanager

from .attr import *
from .keys import TermInput
from . import format


class Terminal:
    _ATTR_PUSH = object()
    _ATTR_POP = object()
    _ATTR_SET = object()

    def __init__(self, altscreen=False, height=0, width=0,
                 cursor=False, sigwinch=True):
        self.stream = sys.__stdout__
        if not self.stream.isatty():
            raise Exception('output does not appear to be a tty')

        self.use_env_size = True
        self.on_resize = None
        self._regions = RegionContainer()
        self.root = None

        self._keypad_on = False

        self._initterm()
        self._input = TermInput(sys.__stdin__.fileno())
        self._input.on_resize = self._process_resize

        self.default_attr = Attributes()

        if sigwinch:
            self.register_sigwinch()

    def register_sigwinch(self):
        signal.signal(signal.SIGWINCH, self._sigwinch_handler)

    def _sigwinch_handler(self, signum, frame):
        # Just record that we were resized.  getch() will then call
        # recompute_size() in the main thread.  This avoids any problems with
        # non-reentrant functions being used inside a signal handler.
        self._input.signal_resize()

    def _process_resize(self):
        self.recompute_size()

    def get_escape_time(self):
        return self._input.escape_time

    def set_escape_time(self, seconds):
        self._input.escape_time = seconds

    def getch(self, escape_time=None):
        return self._input.getch(escape_time)

    def recompute_size(self):
        self._width, self._height = self._get_dimensions()
        self._regions.recompute_sizes()

        # Call the on_resize() callback after our size and all of the
        # regions sizes have been updated.
        if self.on_resize:
            self.on_resize()
        self._regions.invoke_on_resize()
        self.flush()

    def _get_dimensions(self):
        if self.use_env_size:
            # Use $LINES and $COLUMNS if they are set
            width = os.environ.get('COLUMNS')
            height = os.environ.get('LINES')
            if width is not None and height is not None:
                return width, height

        # Otherwise fall back and query the terminal
        ret = fcntl.ioctl(self.stream.fileno(), termios.TIOCGWINSZ, bytes(8))
        rows, cols, xpixel, ypixel = struct.unpack('hhhh', ret)
        return cols, rows

    def flush(self):
        self.stream.flush()

    def write(self, text, *args, **kwargs):
        if args or kwargs:
            text = format.format(text, *args, **kwargs)

        self.stream.write(text)

    def region(self, x, y, width=0, height=0):
        return self._regions.new_region(self, self, x, y, width, height)

    @property
    def height(self):
        return self._height

    @property
    def width(self):
        return self._width

    def move(self, x, y):
        self.write_cap('cup', y, x)

    def clear(self):
        self.write_cap('clear')

    def get_cap(self, cap, *args):
        attr = curses.tigetstr(cap)
        if attr is None:
            return ''

        if args:
            attr = curses.tparm(attr, *args)
        return attr.decode('utf-8')

    def write_cap(self, cap, *args):
        self.write(self.get_cap(cap, *args))

    def format(self, fmt, *args, **kwargs):
        return format.format(fmt, *args, **kwargs)

    def vformat(self, fmt, args, kwargs, width=None, hfill=None):
        return format.vformat(self, fmt, args, kwargs,
                              width=width, hfill=hfill)

    @contextmanager
    def restore_term_attrs(self):
        current_attrs = termios.tcgetattr(self.stream.fileno())
        termios.tcsetattr(self.stream.fileno(), termios.TCSAFLUSH,
                          self._orig_term_attrs)

        try:
            yield
        finally:
            termios.tcsetattr(self.stream.fileno(), termios.TCSAFLUSH,
                              current_attrs)

    def _initterm(self):
        curses.setupterm(os.environ.get('TERM', 'dumb'), self.stream.fileno())
        self._orig_term_attrs = termios.tcgetattr(self.stream.fileno())

    def change_input_mode(self, raw, echo=False, drop_input=True, keypad=None):
        orig_attrs = termios.tcgetattr(self.stream.fileno())
        orig_keypad = self._keypad_on

        if keypad is None:
            keypad = raw

        attrs = orig_attrs[:]
        attrs[3] |= termios.ISIG

        if echo:
            attrs[3] |= termios.ECHO
        else:
            attrs[3] &= ~termios.ECHO

        if raw:
            attrs[0] &= ~termios.ICRNL
            attrs[3] &= ~termios.ICANON
            attrs[6][termios.VMIN] = 0
            attrs[6][termios.VTIME] = 0
        else:
            attrs[0] |= termios.ICRNL
            attrs[3] |= termios.ICANON

        if drop_input:
            how = termios.TCSAFLUSH
        else:
            how = termios.TCSANOW

        self.set_keypad(keypad)
        termios.tcsetattr(self.stream.fileno(), how, attrs)
        return orig_attrs, orig_keypad

    def restore_input_mode(self, state=None, drop_input=True):
        if state is None:
            state = (self._orig_term_attrs, False)

        attrs = state[0]
        keypad = state[1]

        if drop_input:
            how = termios.TCSAFLUSH
        else:
            how = termios.TCSANOW
        termios.tcsetattr(self.stream.fileno(), how, attrs)

        self.set_keypad(keypad)

    def set_keypad(self, on, flush=True):
        if on == self._keypad_on:
            return

        self._keypad_on = on
        if on:
            self.write_cap('smkx')
        else:
            self.write_cap('rmkx')

        if flush:
            self.flush()

    @contextmanager
    def raw_input(self, echo=False, drop_input=True):
        orig_attrs = self.change_input_mode(raw=True, echo=echo,
                                            drop_input=drop_input)
        try:
            yield
        finally:
            self.restore_input_mode(orig_attrs, drop_input=drop_input)

    @contextmanager
    def program_mode(self, height=0, width=0,
                     altscreen=False, cursor=False, echo=False, raw=True):
        orig_attrs = self.change_input_mode(raw=raw, echo=echo)
        if altscreen:
            self.write_cap('smcup')
        if not cursor:
            self.write_cap('civis')

        self.recompute_size()

        root = self.region(0, -height, -width, 0)
        if root.height == self.height:
            self.clear()
        else:
            self.write(self.get_cap('ind') * root.height)

        self.move(0, self.height - 1)
        self.flush()

        try:
            yield root
        finally:
            self.move(0, self.height - 1)
            self.write_cap('el')
            self.write_cap('cnorm')
            if altscreen:
                self.write_cap('rmcup')
            self.restore_input_mode(orig_attrs)
            self.flush()


class RegionContainer:
    def __init__(self):
        self._regions = {}

    def new_region(self, term, parent, x, y, width, height):
        def _region_destroyed(ref):
            del self._regions[ref_id]

        region = Region(term, parent, x, y, width, height)
        ref = weakref.ref(region, _region_destroyed)
        ref_id = id(ref)
        self._regions[ref_id] = ref
        return region

    def all_regions(self):
        for ref in self._regions.values():
            region = ref()
            if region is not None:
                yield region

    def recompute_sizes(self):
        for region in self.all_regions():
            region.recompute_size()

    def invoke_on_resize(self):
        for region in self.all_regions():
            region.invoke_on_resize()


class Region:
    def __init__(self, term, parent, x, y, width, height):
        self.term = term
        self.parent = parent
        self.desired_x = x
        self.desired_y = y
        self.desired_width = width
        self.desired_height = height

        self._regions = RegionContainer()
        self.on_resize = None

        self.recompute_size()

    def region(self, x, y, width=0, height=0):
        return self._regions.new_region(self.term, self, x, y, width, height)

    def recompute_size(self):
        if self.desired_x >= 0:
            self.x = self.desired_x
        else:
            self.x = max(self.term.width + self.desired_x, 0)
        if self.desired_y >= 0:
            self.y = self.desired_y
        else:
            self.y = max(self.term.height + self.desired_y, 0)

        max_width = self.term.width - self.x
        if self.desired_width <= 0:
            self.width = max(max_width + self.desired_width, 0)
        else:
            self.width = min(self.desired_width, max_width)

        max_height = self.term.height - self.y
        if self.desired_height <= 0:
            self.height = max(max_height + self.desired_height, 0)
        else:
            self.height = min(self.desired_height, max_height)

        self._regions.recompute_sizes()

    def invoke_on_resize(self):
        if self.on_resize:
            self.on_resize()

        self._regions.invoke_on_resize()

    def writeln(self, y, text, *args, **kwargs):
        self.vwriteln(y, text, args, kwargs,
                      hfill=kwargs.get('hfill', True))

    def vwriteln(self, y, text, args, kwargs, hfill=True):
        self.vwrite_xy(0, y, text, args, kwargs, hfill=hfill)

    def write_xy(self, x, y, text, *args, **kwargs):
        self.vwrite_xy(x, y, text, args, kwargs,
                       hfill=kwargs.get('hfill', True))

    def vwrite_xy(self, x, y, text, args, kwargs, hfill=True):
        if y >= self.height:
            return
        elif y < 0:
            y = self.height - y
            if y < 0:
                return

        if x >= self.width:
            # Out of the region
            return
        elif x < 0:
            x = self.width - x
            if x < 0:
                return

        width = self.width - x
        data = self.term.vformat(text, args, kwargs, width=width, hfill=hfill)

        self.term.move(self.x + x, self.y + y)
        self.term.write(data)
