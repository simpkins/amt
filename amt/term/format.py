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
from . import unicode


class LineSegment:
    def __init__(self):
        # Required attributes of all LineSegment objects
        self.attr_modifier = None
        self.permanent_attr = False

        self.min_width = 0
        self.max_width = 0
        self.pad_precedence = 0
        self.pad_weight = 0

    def get_value_default_width(self):
        '''
        Return the value using the default width.

        This function should return a tuple of (value, value_width),
        where value_width is the width of the returned value.
        '''
        raise NotImplementedError('get_value_default_width() must be '
                                  'implemented by subclasses')

    def get_value(self, width):
        '''
        Return the value using the specified width.

        This function should return a tuple of (value, value_width),
        where value_width is the actual width of the returned value.

        If self.max_width is not None, the specified width will never be
        greater than the max width.

        The formatting code will attempt to honor self.min_width, but may pass
        in a value smaller than self.min_width when there is not enough room to
        display the full value.

        The returned width must never be larger than the input width.  As much
        as possible it should equal the input width, but it may be smaller by a
        few cells in cases where the string must be truncated before a
        multi-cell wide character.
        '''
        raise NotImplementedError('get_value() must be '
                                  'implemented by subclasses')


class TextSegment(LineSegment):
    def __init__(self, value, min_width=None, pad_weight=None):
        super(TextSegment, self).__init__()
        self.value, self.rendered_width = unicode.renderable_line(value)
        self.min_width = self.rendered_width
        self.max_width = self.rendered_width

        self.pad_precedence = 0
        self.pad_weight = 0

        # If min_width is specified, this text segment can be truncated to
        # allow other fields to take up more room.
        #
        # It will expand with other fields according to the pad weight
        # and precedence.  (By default, truncated text fields have a pad
        # precedence of 0, so they will fully expand before normal padding
        # fields start expanding.)
        if min_width is not None:
            self.min_width = max(min(min_width, width), 0)
            if pad_weight is None:
                self.pad_weight = 1
            else:
                self.pad_weight = pad_weight

    def get_value_default_width(self):
        return self.value, self.rendered_width

    def get_value(self, width):
        if width >= self.rendered_width:
            return self.value, self.rendered_width
        return unicode.renderable_line(self.value, max_width=width)


class PaddingSegment(LineSegment):
    def __init__(self, value=None, min_width=1, default_width=4,
                 max_width=None, pad_weight=1, precedence=1):
        super(PaddingSegment, self).__init__()

        if value is None:
            value = ' '
        self.value, self.value_width = unicode.renderable_line(value)

        self.min_width = min_width
        self.max_width = max_width
        self.default_width = default_width

        self.pad_precedence = precedence
        self.pad_weight = pad_weight

    def get_value_default_width(self):
        return self.get_value(self.default_width)

    def get_value(self, width):
        if self.value_width == 1:
            # common case
            return self.value * width, width

        num_repititions = width / self.value_width
        if int(num_repititions) == num_repititions:
            return self.value * int(num_repititions)
        line = self.value * (1 + int(num_repititions))
        return unicode.renderable_line(line, width)


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
            value, width = segment.get_value_default_width()
            yield segment, value

    def get_min_widths(self, width):
        width_left = width
        for segment in self.segments:
            segment_width = min(segment.min_width, width_left)
            value, value_width = segment.get_value(segment_width)
            width_left -= value_width
            assert width_left >= 0

            yield segment, value
            if width_left <= 0:
                return

    def get_pad_widths(self, widths):
        for segment, width in zip(self.segments, widths):
            value, actual_width = segment.get_value(width)
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
            self.add_segment(TextSegment(literal))
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
            segment = TextSegment('')
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

        segment = TextSegment(value)
        segment.attr_modifier = term_attrs
        self.add_segment(segment)
