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
import sys
from contextlib import contextmanager

from ..containers import WeakrefSet
from .attr import *
from . import keys
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
        self.clear_on_resize = True

        self._keypad_on = False
        self._term_modes = []

        self._initterm()
        self._input = keys.TermInput(sys.__stdin__.fileno())
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

    def getch(self, escape_time=None, handle_sig_keys=True):
        while True:
            key = self._input.getch(escape_time)
            if handle_sig_keys:
                if key == keys.KEY_CTRL_Z:
                    self._restore_terminal()
                    os.kill(0, signal.SIGSTOP)
                    self._reenter_term_mode()
                    self.recompute_size()
                    continue
                elif key == keys.KEY_CTRL_C:
                    os.kill(0, signal.SIGINT)
                    continue
                elif key == keys.KEY_CTRL_BACKSLASH:
                    self._restore_terminal()
                    os.kill(0, signal.SIGQUIT)
                    continue
            return key

    def recompute_size(self):
        self._width, self._height = self._get_dimensions()
        self._regions.recompute_sizes()

        # Clear the terminal.  Resizing the terminal will generally cause
        # it to look messed-up, since lines will wrap in unintended ways.
        # We typically need to clear the entire screen, and then let the
        # on_resize() methods redraw everything
        if self.clear_on_resize:
            self.clear()

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

    def _initterm(self):
        curses.setupterm(os.environ.get('TERM', 'dumb'), self.stream.fileno())

    def change_input_mode(self, raw, echo=False, drop_input=True,
                          signal_keys=None, keypad=None):
        orig_attrs = termios.tcgetattr(self.stream.fileno())
        orig_keypad = self._keypad_on

        if keypad is None:
            keypad = raw
        if signal_keys is None:
            signal_keys = not raw

        attrs = orig_attrs[:]
        attrs[3] |= termios.ISIG

        if echo:
            attrs[3] |= termios.ECHO
        else:
            attrs[3] &= ~termios.ECHO

        if signal_keys:
            attrs[3] |= termios.ISIG
        else:
            attrs[3] &= ~termios.ISIG

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

    def restore_input_mode(self, state, drop_input=True):
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
        orig_attrs = None

        def enter_raw_mode():
            nonlocal orig_attrs
            orig_attrs = self.change_input_mode(raw=True, echo=echo,
                                                drop_input=drop_input)

        def restore_term():
            nonlocal orig_attrs
            self.restore_input_mode(orig_attrs, drop_input=drop_input)

        with self._term_mode(enter_raw_mode, restore_term):
            yield

    @contextmanager
    def program_mode(self, height=0, width=0,
                     altscreen=False, cursor=False, echo=False, raw=True):
        orig_attrs = None

        def enter_program_mode():
            nonlocal orig_attrs
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

            return root

        def restore_term_mode():
            nonlocal orig_attrs
            self.move(0, self.height - 1)
            self.write_cap('el')
            self.write_cap('cnorm')
            if altscreen:
                self.write_cap('rmcup')
            self.restore_input_mode(orig_attrs)
            self.flush()

        with self._term_mode(enter_program_mode, restore_term_mode) as root:
            yield root

    @contextmanager
    def shell_mode(self):
        '''
        A contextmanager that restores the terminal to its normal settings,
        then returns back to the current mode when exiting the context.
        '''
        self._restore_terminal()
        term_modes = self._term_modes
        self._term_modes = []
        try:
            yield
        finally:
            self._term_modes = term_modes
            self._reenter_term_mode()
            self.recompute_size()

    @contextmanager
    def _term_mode(self, enter_fn, restore_fn):
        self._term_modes.append((enter_fn, restore_fn))
        result = enter_fn()
        try:
            yield result
        finally:
            restore_fn()
            self._term_modes.pop()

    def _restore_terminal(self):
        for enter_fn, restore_fn in reversed(self._term_modes):
            restore_fn()

    def _reenter_term_mode(self):
        for enter_fn, restore_fn in self._term_modes:
            enter_fn()


class RegionContainer:
    def __init__(self):
        self._regions = WeakrefSet()

    def new_region(self, term, parent, x, y, width, height):
        region = Region(term, parent, x, y, width, height)
        self._regions.add(region)
        return region

    def recompute_sizes(self):
        for region in self._regions:
            region.recompute_size()

    def invoke_on_resize(self):
        for region in self._regions:
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
            self.x = max(self.parent.width + self.desired_x, 0)
        if self.desired_y >= 0:
            self.y = self.desired_y
        else:
            self.y = max(self.parent.height + self.desired_y, 0)

        max_width = self.parent.width - self.x
        if self.desired_width <= 0:
            self.width = max(max_width + self.desired_width, 0)
        else:
            self.width = min(self.desired_width, max_width)

        max_height = self.parent.height - self.y
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

    def clear(self):
        if (self.x == 0 and self.y == 0 and
            self.width == self.term.width and self.height == self.term.height):
            self.term.clear()
            return

        for y in range(self.height):
            self.term.move(self.x, self.y + y)
            self.term.write(' ' * self.width)
