#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
'''
================================
term.format: Terminal Formatting
================================

This module contains the format string parsing code used by Terminal.format().

The format string syntax used here is based on the `standard library format
string syntax <http://docs.python.org/library/string.html#formatstrings>`_.

The replacement_field syntax is the similar to the standard syntax, but
contains terminal attributes instead of the normal format specifier.  A
standard format specifier can appear after the terminal attributes, separated
by a second colon.

  replacement_field ::= "{" [field_name] [":" term_attrs [":" format_spec]] "}"


Terminal Attributes
*******************

term_attrs is a comma-separated list of attribute names and colors.  The
ATTRIBUTE_MODIFIERS dictionary in the term.attr module contains the full list
of modifier names.

For example:

  format('Please press {key:bold} to {action:fg=white,bg=blue}',
         key='Escape', action='quit')

Will render the text "Please press Escape to quit", with the text "Escape" in
bold, and "quit" in white text on a blue background (on terminals that support
color).


Field Name Syntax
*****************

In addition, the field name has also been extended in several ways.

Literal Text
------------

If the field name is surrounded by double or single quotes, it is interpreted
as literal text to be rendered directly, rather than being expanded as a field
name.  This makes it easier to apply terminal attributes to literal text,
without having to specify it as a separate argument.

For example:

  format('Lorem {"ipsum":standout} dolor sit amet')

Will render "Lorem ipsum dolor sit amet", with "ipsum" displayed in standout
mode.

Note that field name parsing occurs before parsing and stripping off the quote
characters, so this does behave somewhat differently from normal quoted string
semantics.  In particular, the characters ``{``, ``}``, ``!``, and ``:`` are
not allowed inside the quoted text.  Furthermore, while the leading and
trailing quote characters are stripped off, internal quote characters in the
field name are left as-is and do not terminate the text.

This literal text parsing is intended to be a convenience for simple literal
strings.  If you do need to include any of these forbidden special characters,
supply it as an argument and use normal field name substitution.

Inline Attribute Changes
------------------------

If the field name is ``+``, the attributes from the format specifier are
applied to the remainder of the formatting string.

For example:

  format('Attention: {+:underline,fg=black,bg=red}Do not press '
         '{key:bold,bg=blue} while the program is running', key='Ctrl-C')

Will render 'Attention: Do not press Ctrl-C while the program is running'.
Everything after "Attention: " will be shown underlined with black text on a
red background, except for "Ctrl-C", which will be bold, underlined, and with
black text on a blue background.

Padding
-------

If the field name is ``=``, horizontal padding will be inserted to expand the
string to take up the full terminal width.  This makes it easy to write
centered and right-justified text.

For example:

  format('Left Justified{=}Center{=}Right Justified')

Terminal attributes can be applied to padding.  For example, to generate
padding with a red background:

  format('Left Justified{=:bg=red}Center{=:bg=red}Right Justified')

The padding also accepts several attributes to control the amount of padding
inserted.  These are specified as part if the field name, after the ``=``
character.

By default a padding field not shrink smaller than 1 space, even if this
requires truncating the line.  You can specify an alternate minimum width with the ``min`` parameter:

  format('Left{=min=4}Right')

When the terminal width is unknown, padding fields default to 4 spaces wide.
However an alternate default width can be specified with the ``default``
parameter:

  format('Left{=default=8}Right')

Padding parameters can be combined with a comma, can can also be used in
conjunction with terminal attributes:

  format('Left{=min=4,default=8:underline,bg=blue}Right')
'''

import math
import re
import string

from .attr import *


class TextSegment:
    def __init__(self):
        # Required attributes of all TextSegment objects
        self.attr_modifier = None
        self.permanent_attr = False

        self.min_width = 0
        self.max_width = 0
        self.pad_precedence = 0
        self.pad_weight = 0

    def get_value_default_width(self):
        pass

    def get_value_min_width(self, width):
        pass

    def get_value_pad_width(self, width):
        pass

    CTRL_CHR_RE = re.compile('[\x00-\x1f]')
    TAB_STOP = 8

    @classmethod
    def get_displayed_line(self, value):
        '''
        Take a unicode string, and compute info about the line that will be
        displayed.

        Returns a tuple containing (line, num_glyphs).

        The returned line is a truncated version of the input string that
        excludes any text that is not displayed on the same line.  (Any text
        after a newline or other vertical separator is ignored.)

        The num_glyphs contains the number of glyphs in the displayed line.
        This is intended to be used to determine how many printable glyphs will
        be displayed on the terminal line (for determining the line width).
        '''
        # TODO: Python doesn't have a good way to compute how many glyphs will
        # be displayed, and which ones are separators that would move to the
        # next line.
        #
        # To implement this properly we'll probably need to do this in C with
        # ICU.
        #
        # As a best effort for now, just strip out control characters, and
        # ignore anything after a newline, carriage return, form feed, or
        # vertical tab.
        parts = []
        idx = 0

        stripped = ''
        num_glyphs = 0
        while idx < len(value):
            m = self.CTRL_CHR_RE.search(value, idx)
            if not m:
                if idx == 0:
                    # Fast path for the common case
                    stripped = value
                    num_glyphs = len(value)
                else:
                    rest = value[idx:]
                    parts.append(rest)
                    num_glyphs += len(rest)
                    stripped = ''.join(parts)
                break

            prefix = value[idx:m.start()]
            parts.append(prefix)
            num_glyphs += len(prefix)
            idx = m.start() + 1

            char = m.group(0)
            if char in ('\n', '\v', '\f'):
                stripped = ''.join(parts)
                break
            elif char == '\t':
                # Append spaces until num_glyphs is a multiple of TAB_STOP
                next_stop = ((1 + int(num_glyphs / self.TAB_STOP)) *
                             self.TAB_STOP)
                num_spaces = next_stop - num_glyphs
                parts.append(' ' * num_spaces)
                num_glyphs += num_spaces

        return (stripped, num_glyphs)

    @staticmethod
    def truncate_value(value, width):
        '''
        Truncate the specified unicode string to the specified width (specified
        as a number of displayed glyphs rather than number of characters).
        '''
        assert width <= len(value)
        if width >= len(value):
            return value
        return value[:width]


class FixedTextSegment(TextSegment):
    def __init__(self, value):
        super(FixedTextSegment, self).__init__()

        self.value, num_glyphs = self.get_displayed_line(value)
        self.min_width = num_glyphs
        self.max_width = num_glyphs

        self.pad_precedence = 0
        self.pad_weight = 0

    def get_value_default_width(self):
        return self.value

    def get_value_min_width(self, width):
        return self.truncate_value(self.value, width)

    def get_value_pad_width(self, width):
        assert width == len(self.value)
        return self.value


class VariableTextSegment(TextSegment):
    def __init__(self, value, attr, min_width=None, pad_weight=1):
        super(VariableTextSegment, self).__init__(attr)

        self.value, num_glyphs = self.get_displayed_line(value)

        if min_width is None:
            min_width = num_glyphs
        self.min_width = min(min_width, num_glyphs)
        self.max_width = num_glyphs

        self.pad_precedence = 0
        self.pad_weight = pad_weight

    def get_value_default_width(self):
        return self.value

    def get_value_min_width(self, width):
        assert width <= self.min_width
        return self.truncate_value(self.value, width)

    def get_value_pad_width(self, width):
        assert width >= self.min_width
        return self.truncate_value(self.value, width)


class PaddingSegment(TextSegment):
    def __init__(self, value=None, min_width=1, default_width=4,
                 max_width=None, pad_weight=1, precedence=1):
        super(PaddingSegment, self).__init__()

        if value is None:
            self.value = ' '
            self.value_width = 1
        else:
            self.value, self.value_width = self.get_displayed_line(value)

        self.min_width = min_width
        self.max_width = max_width
        self.default_width = default_width

        self.pad_precedence = precedence
        self.pad_weight = pad_weight

    def get_value_default_width(self):
        return self.get_value(self.default_width)

    def get_value_min_width(self, width):
        return self.get_value(self.min_width)

    def get_value_pad_width(self, width):
        return self.get_value(width)

    def get_value(self, width):
        if self.value_width == 1:
            return self.value * width
        else:
            repititions = 1 + (width / self.value_width)
            return self.truncate_value(self.value * repititions, width)


class TextLine:
    def __init__(self):
        self.segments = []

    def render(self, term, width):
        # If we don't have a line width, use the default widths
        if width is None:
            return self._render(term, self.get_default_widths())

        # Compute the length if we just used the minimum widths
        min_width = 0
        pad_weights = {}
        widths = [0] * len(self.segments)
        for idx, segment in enumerate(self.segments):
            widths[idx] = segment.min_width
            min_width += segment.min_width
            if min_width >= width:
                # The line doesn't fit.  Render as much as we can
                # using the minimum widths.
                return self._render(term, self.get_min_widths(width))

            pad_weights.setdefault(segment.pad_precedence, 0)
            pad_weights[segment.pad_precedence] += segment.pad_weight

        # We have room left over after the minimum widths.
        # Compute how much extra space should be allocated to each segment,
        # based on their weights.
        len_left = width - min_width
        # Different segments may have different padding precedences.
        # This allows text segments to fully expand before we start inserting
        # more whitespace padding.
        #
        # Iterate through each precedence level, and allocate as much padding
        # as possible to each level before preceding to the next level.
        sorted_weights = sorted(pad_weights.items(), key=lambda x: x[0])
        for precedence, total_weight in sorted_weights:
            while len_left > 0:
                padding_allocated = 0
                weight_left = total_weight
                for idx, segment in enumerate(self.segments):
                    if weight_left <= 0:
                        break
                    extra = math.ceil(segment.pad_weight *
                                      float(len_left) / weight_left)
                    cur_width = widths[idx]
                    new_width = cur_width + extra
                    if segment.max_width is not None:
                        new_width = min(segment.max_width, new_width)
                        extra = new_width - cur_width
                    widths[idx] = new_width

                    weight_left -= segment.pad_weight
                    assert weight_left >= 0
                    len_left -= extra
                    assert len_left >= 0
                    padding_allocated += extra

                if padding_allocated == 0:
                    break
            if len_left == 0:
                break

        pieces = self.get_pad_widths(widths)
        return self._render(term, pieces)

    def _render(self, term, pieces):
        outputs = []
        cur_attr = term.default_attr
        last_attr = term.default_attr
        attr_stack = []

        for segment, value in pieces:
            if segment.attr_modifier is None:
                new_attr = cur_attr
            else:
                new_attr = cur_attr.modify(segment.attr_modifier)

            if new_attr != last_attr:
                outputs.append(last_attr.change_esc(new_attr, term))
                last_attr = new_attr
            if segment.permanent_attr:
                cur_attr = new_attr

            outputs.append(value)

        if last_attr != term.default_attr:
            outputs.append(last_attr.change_esc(term.default_attr, term))

        return ''.join(outputs)

    def get_default_widths(self):
        for segment in self.segments:
            yield segment, segment.get_value_default_width()

    def get_min_widths(self, width):
        len_left = width
        for segment in self.segments:
            segment_width = min(segment.min_width, len_left)
            value = segment.get_value_min_width(segment_width)
            len_left -= len(value)
            assert len_left >= 0

            yield segment, value
            if len_left <= 0:
                return

    def get_pad_widths(self, widths):
        for segment, width in zip(self.segments, widths):
            value = segment.get_value_pad_width(width)
            assert len(value) == width
            yield segment, value


def format(term, fmt, *args, **kwargs):
    return vformat(term, fmt, args, kwargs,
                   width=kwargs.get('width'), hfill=kwargs.get('hfill'))


def vformat(term, fmt, args, kwargs, width=None, hfill=False):
    line = vformat_line(fmt, args, kwargs, hfill=hfill)
    return line.render(term, width)


def format_line(fmt, *args, **kwargs):
    return vformat_line(fmt, args, kwargs, hfill=kwargs.get('hfill'))


def vformat_line(fmt, args, kwargs, hfill=False):
    line = TextLine()
    for segment in _FormatParser(fmt, args, kwargs):
        line.segments.append(segment)

    if hfill:
        if not isinstance(hfill, str):
            hfill = ' '
        pad = PaddingSegment(hfill, min_width=0, default_width=0, precedence=2)
        line.segments.append(pad)
    return line


class _FormatParser:
    def __init__(self, fmt, args, kwargs):
        self.segments = []
        self.auto_idx = 0

        self.args = args
        self.kwargs = kwargs

        self.formatter = string.Formatter()
        self.fmt_iter = self.formatter.parse(fmt)

    def __iter__(self):
        return self

    def __next__(self):
        if not self.segments:
            self.parse_more()

        return self.segments.pop(0)

    def add_segment(self, segment):
        self.segments.append(segment)

    def parse_more(self):
        literal, field_name, format_spec, conversion = next(self.fmt_iter)

        if literal:
            self.add_segment(FixedTextSegment(literal))
        if field_name is None:
            return

        term_attrs, format_spec = self.parse_format_spec(format_spec)
        self.parse_field(field_name, term_attrs, format_spec, conversion)

    def parse_format_spec(self, value):
        if not value:
            return None, None

        # Interpret the format_spec field as terminal attributes,
        # followed by an optional standard format_spec after another colon.
        # e.g., {0:red:>30}
        parts = value.split(':', 1)
        term_attrs_str = parts[0]
        if len(parts) == 1:
            format_spec = None
        else:
            format_spec = parts[1]

        if term_attrs_str:
            term_attrs = self.parse_term_attrs(term_attrs_str)
        else:
            term_attrs = None
        return term_attrs, format_spec

    def parse_term_attrs(self, value):
        modifier = AttributeModifier()
        for attr in value.split(','):
            if not attr:
                continue

            try:
                attr_modifier = ATTRIBUTE_MODIFIERS[attr]
            except KeyError:
                raise Exception('unknown attribute %r' % (attr,))
            modifier.combine_in_place(attr_modifier)
        return modifier

    def parse_field(self, field_name, term_attrs, format_spec, conversion):
        if field_name is '':
            if self.auto_idx is None:
                raise Exception('cannot switch between manual field '
                                'specification and auto-indexing')
            obj = self.formatter.get_value(self.auto_idx,
                                           self.args, self.kwargs)
            self.auto_idx += 1
            self.append_literal(obj, term_attrs, format_spec, conversion)
            return

        if field_name.startswith('"') or field_name.startswith("'"):
            # Note that we still rely on string.Formatter() to parse the field
            # name, so this isn't really quite like a normal quoted string.
            # The characters '!', ':', '{', and '}' cannot appear inside the
            # quoted string.  Additionally, other quote characters inside the
            # field name will not terminate the string.
            quote = field_name[0]
            if not field_name.endswith(quote):
                raise Exception('mismatched %s in field_name: %r' %
                                (quote, field_name))
            value = field_name[1:-1]
            self.append_literal(value, term_attrs, format_spec, None)
            return

        if field_name == '+':
            segment = FixedTextSegment('')
            segment.attr_modifier = term_attrs
            segment.permanent_attr = True
            self.add_segment(segment)
            return

        if field_name.startswith('='):
            # Padding
            segment = self.parse_padding(field_name[1:])
            segment.attr_modifier = term_attrs
            self.add_segment(segment)
            return

        obj, used_key = self.formatter.get_field(field_name,
                                                 self.args, self.kwargs)
        if isinstance(used_key, int):
            self.auto_idx = None
        self.append_literal(obj, term_attrs, format_spec, conversion)

    def parse_padding(self, value):
        segment = PaddingSegment()
        if not value:
            return segment

        params = value.split(',')
        for p in params:
            parts = p.split('=', 1)
            if len(parts) != 2:
                raise Exception('padding properties must be of the form '
                                'name=value: %r' % p)
            name, value = parts
            if name == 'min':
                segment.min_width = int(value)
            elif name == 'default':
                segment.default_width = int(value)
            elif name == 'weight':
                segment.pad_weight = int(value)
            else:
                raise Exception('unknown padding property %r' % (name,))
        return segment

    def append_literal(self, value, term_attrs, format_spec, conversion):
        if conversion is not None:
            value = self.formatter.convert_field(value, conversion)
        else:
            value = str(value)

        if format_spec:
            value = value.__format__(format_spec)

        segment = FixedTextSegment(value)
        segment.attr_modifier = term_attrs
        self.add_segment(segment)
