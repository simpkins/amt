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
# - Since curses knows its window buffer state and the current state of the
#   physical screen, it can be smarter about only redrawing the areas that are
#   actually changed, and avoid unnecessarily redrawing unchanged areas.  This
#   doesn't seem like a huge problem these days: most people have relatively
#   fast connections to their terminals and can live with a more characters
#   than necessary being sent.
# - We can't use curses' input processing functionality.  This one is a bit of
#   a hassle: we have to implement our own escape code processing.  However,
#   python doesn't provide get_wch() yet (hopefully a usable version will be
#   coming in 3.3), so we have to do some processing for this anyway to support
#   this in a reasonable manner.  I haven't implemented mouse input yet.

import curses
import errno
import fcntl
import math
import os
import signal
import string
import struct
import termios
import weakref
import sys
from contextlib import contextmanager

from .keys import TermInput


class Terminal:
    def __init__(self, altscreen=False, height=0, width=0,
                 cursor=False, sigwinch=True):
        self.stream = sys.__stdout__
        if not self.stream.isatty():
            raise Exception('output does not appear to be a tty')

        self.use_env_size = True
        self.on_resize = None
        self._regions = {}
        self.root = None

        self._keypad_on = False

        self._initterm()
        self._input = TermInput(sys.__stdin__.fileno())
        self._input.on_resize = self._process_resize

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

        regions = list(self._regions.values())
        for ref in regions:
            region = ref()
            if region is None:
                continue
            region.recompute_size()

        if self.on_resize:
            self.on_resize()

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
            text = self.vformat(text, args, kwargs)

        self.stream.write(text)

    def region(self, x, y, width=0, height=0):
        def _region_destroyed(ref):
            del self._regions[ref_id]

        region = Region(self, x, y, width, height)
        ref = weakref.ref(region, _region_destroyed)
        ref_id = id(ref)
        self._regions[ref_id] = ref
        return region

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
        return self.vformat(fmt, args, kwargs)

    def vformat(self, fmt, args, kwargs, width=None):
        bufs = []
        pads = []
        len_left = width

        for part in self.parse_format(fmt, args, kwargs):
            if isinstance(part, FormattedText):
                bufs.append(part.intro)
                len_left = self._format_append(part.value, len_left,
                                               bufs, pads)
                bufs.append(part.outro)
            else:
                len_left = self._format_append(part, len_left, bufs, pads)

            if len_left == 0:
                break

        if pads:
            total_weight = 0
            for pad, buf_idx in pads:
                total_weight += pad.weight

            for pad, buf_idx in pads:
                extra = math.ceil(pad.weight * float(len_left) / total_weight)
                len_left -= extra
                assert len_left >= 0
                total_weight -= pad.weight
                assert total_weight >= 0
                bufs[buf_idx] = ' ' * (pad.min + extra)

            assert len_left == 0
            assert total_weight == 0

        return ''.join(bufs)

    def _format_append(self, text, len_left, bufs, pads):
        if isinstance(text, Padding):
            if len_left is None:
                bufs.append(' ' * text.default)
                return None
            len_left = max(0, len_left - text.min)
            pads.append((text, len(bufs)))
            bufs.append(None)
            return len_left

        if len_left is None:
            bufs.append(text)
            return None
        elif len(text) > len_left:
            bufs.append(text[:len_left])
            return 0
        else:
            bufs.append(text)
            return len_left - len(text)

    def parse_format(self, fmt, args, kwargs):
        # Supply a default set of field names that can be used in format
        # strings
        all_kwargs = self._default_fields.copy()
        all_kwargs.update(kwargs)

        auto_idx = 0
        f = string.Formatter()
        for literal, field_name, format_spec, conversion in f.parse(fmt):
            if literal:
                yield literal
            if field_name is None:
                continue

            if field_name is '':
                if auto_idx is None:
                    raise Exception('cannot switch between manual field '
                                    'specification and auto-indexing')
                obj = f.get_value(auto_idx, args, all_kwargs)
                auto_idx += 1
            else:
                obj, used_key = f.get_field(field_name, args, all_kwargs)
                if isinstance(used_key, int):
                    auto_idx = None

            if conversion is not None:
                value = f.convert_field(obj, conversion)
            elif isinstance(obj, Padding):
                value = obj
            else:
                value = str(obj)

            if not format_spec:
                yield value
                continue

            # Parse terminal attributes from the format_spec
            # Allow normal string format specifier after a second ':'
            # e.g., {0:red:>30}
            parts = format_spec.split(':', 1)
            if len(parts) > 1:
                value = format(value, parts[1])
            format_spec = parts[0]

            intros = []
            outros = []
            for attr in format_spec.split(','):
                if not attr:
                    continue
                intro, outro = self.attribute_info(attr)
                intros.append(intro)
                outros.append(outro)

            text = FormattedText(value, intro=''.join(intros),
                                 outro=''.join(outros))
            yield text

        # TODO: This is only necessary when some of the internal text
        # changed state and didn't reset it.
        reset = FormattedText('', outro=self.get_cap('sgr0'))
        yield reset

    def attribute_info(self, attr):
        try:
            return self._attributes[attr]
        except KeyError:
            raise Exception('unknown attribute %r' % (attr,))

    def _load_attributes(self):
        # FIXME: Make this more generic
        self._attributes = {
            'red': (self.get_cap('setaf', 1), self.get_cap('sgr0')),
            'white_on_blue': (self.get_cap('setaf', 7) +
                              self.get_cap('setab', 4),
                              self.get_cap('sgr0')),
            'underline': (self.get_cap('smul'), self.get_cap('rmul')),
            'normal': (self.get_cap('sgr0'), ''),
        }

        # Supply a default set of field names for use in format strings
        self._default_fields = {
            'pad': Padding(),
        }
        for attr, (on, off) in self._attributes.items():
            self._default_fields[attr] = on

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
        self._load_attributes()
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


class Region:
    def __init__(self, term, x, y, width, height):
        self.term = term
        self.desired_x = x
        self.desired_y = y
        self.desired_width = width
        self.desired_height = height

        self.recompute_size()

    def recompute_size(self):
        if self.desired_x >= 0:
            self.x = self.desired_x
        else:
            self.x = max(self.term.width -1 + self.desired_x, 0)
        if self.desired_y >= 0:
            self.y = self.desired_y
        else:
            self.y = max(self.term.height -1 + self.desired_y, 0)

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

    def writeln(self, y, text, *args, **kwargs):
        self.write_xy(0, y, text, *args, **kwargs)

    def write_xy(self, x, y, text, *args, **kwargs):
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

        data = self.term.vformat(text, args, kwargs, width=self.width - x)

        self.term.move(self.x + x, self.y + y)
        self.term.write(data)


class FormattedText:
    def __init__(self, value, intro='', outro=''):
        self.value = value
        self.intro = intro
        self.outro = outro


class Padding:
    def __init__(self, min=1, default=2, weight=1):
        self.min = min
        self.default = default
        self.weight = weight
