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
import string

from .attr import *

_ACTION_LITERAL = object()
_ACTION_PADDING = object()
_ACTION_SET_ATTR = object()
_ACTION_PUSH_ATTR = object()
_ACTION_POP_ATTR = object()


def format(term, fmt, *args, **kwargs):
    return vformat(term, fmt, args, kwargs,
                   width=kwargs.get('width'), hfill=kwargs.get('hfill'))


def vformat(term, fmt, args, kwargs, width=None, hfill=False):
    bufs = []
    attrs = []
    pads = []
    len_left = width

    attr_stack = []
    cur_attr = term.default_attr

    for action, value in _FormatParser(fmt, args, kwargs):
        if action == _ACTION_LITERAL:
            attrs.append(cur_attr)
            if len_left is None:
                bufs.append(value)
            elif len(value) > len_left:
                bufs.append(value[:len_left])
                len_left = 0
                break
            else:
                bufs.append(value)
                len_left -= len(value)
        elif action == _ACTION_PADDING:
            attrs.append(cur_attr)
            if len_left is None:
                bufs.append(' ' * value.default)
            else:
                len_left = max(0, len_left - value.min)
                pads.append((value, len(bufs)))
                bufs.append(None)
                if len_left == 0:
                    break
        elif action == _ACTION_PUSH_ATTR:
            attr_stack.append(cur_attr)
        elif action == _ACTION_POP_ATTR:
            assert attr_stack
            cur_attr = attr_stack.pop()
        elif action == _ACTION_SET_ATTR:
            cur_attr = cur_attr.modify(value)
        else:
            raise Exception('unknown action: %r, %r' % (action, value))

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
    elif hfill is not None and len_left is not None:
        attrs.append(cur_attr)
        if not isinstance(hfill, str):
            hfill = ' '
        pad = hfill * len_left
        pad = pad[:len_left]  # in case hfill is more than 1 character
        bufs.append(pad)

    outputs = []
    cur_attr = term.default_attr
    for idx, buf in enumerate(bufs):
        if attrs[idx] != cur_attr:
            outputs.append(cur_attr.change_esc(attrs[idx], term))
            cur_attr = attrs[idx]
        outputs.append(buf)
    if cur_attr != term.default_attr:
        outputs.append(cur_attr.change_esc(term.default_attr, term))
    return ''.join(outputs)


class _FormatParser:
    def __init__(self, fmt, args, kwargs):
        self.results = []
        self.auto_idx = 0

        self.args = args
        self.kwargs = kwargs

        self.formatter = string.Formatter()
        self.fmt_iter = self.formatter.parse(fmt)

    def __iter__(self):
        return self

    def __next__(self):
        if not self.results:
            self.parse_more()

        action, value = self.results.pop(0)
        return action, value

    def add_result(self, action, value):
        self.results.append((action, value))

    def parse_more(self):
        literal, field_name, format_spec, conversion = next(self.fmt_iter)

        if literal:
            self.add_result(_ACTION_LITERAL, literal)
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
            self.add_result(_ACTION_SET_ATTR, term_attrs)
            return

        if field_name.startswith('='):
            # Padding
            pad_kwargs = self.parse_padding_kwargs(field_name[1:])
            padding = Padding(**pad_kwargs)
            self.append_with_attrs(_ACTION_PADDING, padding, term_attrs)
            return

        obj, used_key = self.formatter.get_field(field_name,
                                                 self.args, self.kwargs)
        if isinstance(used_key, int):
            self.auto_idx = None
        self.append_literal(obj, term_attrs, format_spec, conversion)

    def parse_padding_kwargs(self, value):
        if not value:
            return {}

        pad_kwargs = {}
        params = value.split(',')
        for p in params:
            parts = p.split('=', 1)
            if len(parts) != 2:
                raise Exception('padding properties must be of the form '
                                'name=value: %r' % p)
            name, value = parts
            if name in ('min', 'default', 'weight'):
                pad_kwargs[name] = int(value)
            else:
                raise Exception('unknown padding property %r' % (name,))
        return pad_kwargs

    def append_literal(self, value, term_attrs, format_spec, conversion):
        if conversion is not None:
            value = self.formatter.convert_field(value, conversion)
        else:
            value = str(value)

        if format_spec:
            value = value.__format__(format_spec)

        self.append_with_attrs(_ACTION_LITERAL, value, term_attrs)

    def append_with_attrs(self, action, value, term_attrs):
        if term_attrs:
            self.add_result(_ACTION_PUSH_ATTR, None)
            self.add_result(_ACTION_SET_ATTR, term_attrs)
            self.add_result(action, value)
            self.add_result(_ACTION_POP_ATTR, None)
        else:
            self.add_result(action, value)


class Padding:
    def __init__(self, min=1, default=4, weight=1):
        self.min = min
        self.default = default
        self.weight = weight
