#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import ctypes
import ctypes.util

# Python doesn't expose wcwidth() or wcswidth() (yet).
# Some background (including descriptions of common terminal behaviors) is
# here: http://bugs.python.org/issue12568
#
# This seems to be a pretty common reference implementation of wcwidth():
# http://www.cl.cam.ac.uk/~mgk25/ucs/wcwidth.c

_libc = None
_VERTICAL_SEPARATORS = set(['\n', '\v', '\f', '\r',
                            '\u0084', '\u0085', '\u008d',
                            '\u2028', '\u2029'])

DEFAULT_TAB_STOP = 8


def get_libc():
    global _libc
    if _libc is None:
        libc_name = ctypes.util.find_library('c')
        _libc = ctypes.CDLL(libc_name)
    return _libc


def renderable_line(value, tab_stop=DEFAULT_TAB_STOP, max_width=None):
    '''
    Convert a unicode string into a line that can be rendered on the
    terminal, and also compute the line width as it will be displayed on the
    terminal.

    Returns the renderable line, and the line width.

    The renderable line is the line with any non-printing control characters
    stripped out, and stopping at the first character that would cause the
    terminal to change lines (such as a newline or other vertical spacing
    character).  Tabs are expanded with spaces, using the specified tab stop
    width.

    The returned width indicates how many columns the line will take up on the
    terminal, and accounts for 0-width characters and multi-cell wide
    characters.  Note that not all terminals render characters the same way, so
    this may not be 100% accurate for all terminals.
    '''
    libc = get_libc()

    result = []
    width = 0
    for char in value:
        if max_width is not None and width >= max_width:
            break

        char_width = libc.wcwidth(ctypes.c_wchar(char))
        if char_width >= 0:
            # Common case: not a control character
            new_width = width + char_width
            # If we have a multi-cell character that would make us
            # exceed the width, stop before appending it.
            if max_width is not None and new_width > max_width:
                break
            result.append(char)
            width = new_width
            continue

        # This is a control character.  If it is a vertical separator
        # (that would cause the terminal to move forwards or backwards a
        # line), truncate the line here.
        if char in _VERTICAL_SEPARATORS:
            break

        # Expand tabs to spaces
        if char == '\t':
            next_width = next_tab_stop(width, tab_stop)
            if max_width is not None:
                next_width = max(next_width, max_width)
            num_spaces = next_width - width
            result.extend([' '] * num_spaces)
            width = next_width
            continue

        # If we are still here this is a non-printing control character.
        # Just skip it.
        continue

    return ''.join(result), width


def truncate_line(value, max_width):
    '''
    Return the renderable version of the specified string, truncated at the
    specified maximum width.
    '''
    line, width = renderable_line(value, max_width=max_width)
    return line


def next_tab_stop(pos, tab_stop=DEFAULT_TAB_STOP):
    return (1 + int(pos / tab_stop)) * tab_stop
