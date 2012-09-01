#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#


class Attributes:
    def __init__(self, attrs=0, fg=None, bg=None):
        self.attrs = attrs

        if fg is None:
            fg = COLOR_DEFAULT
        self.fg = fg

        if bg is None:
            bg = COLOR_DEFAULT
        self.bg = bg

    def copy(self):
        return Attributes(attrs=self.attrs, fg=self.fg, bg=self.bg)

    def __eq__(self, other):
        if self.attrs != other.attrs:
            return False
        if self.fg != other.fg:
            return False
        if self.bg != other.bg:
            return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def modify(self, modifier):
        new = self.copy()
        new.attrs |= (modifier.attrs & modifier.attrs_mask)
        new.attrs &= (modifier.attrs | ~modifier.attrs_mask)

        if modifier.fg_set:
            new.fg = modifier.fg
        if modifier.bg_set:
            new.bg = modifier.bg

        return new

    def change_esc(self, new, term):
        '''
        Get the escape sequence(s) to send to the terminal to change from
        this set of attributes to the specified new set of attributes.
        '''
        if self.attrs != new.attrs:
            if new.attrs == 0:
                ret = [term.get_cap('sgr0')]
            else:
                ret = self._get_attr_change_esc(new, term)

            # The sgr sequence typically resets the colors
            if new.fg == COLOR_DEFAULT and new.bg == COLOR_DEFAULT:
                return ''.join(ret)

            force_colors = True
        else:
            ret = []
            force_colors = False

        if force_colors or self.fg != new.fg:
            ret.append(new.fg.get_fg_cap(term, new.bg))
        if force_colors or self.bg != new.bg:
            ret.append(new.bg.get_bg_cap(term, new.fg))

        return ''.join(ret)

    def _get_attr_change_esc(self, new, term):
        ret = []
        sgr_flags = self.attrs & ATTR_FLAG_SGR_MASK
        new_sgr_flags = new.attrs & ATTR_FLAG_SGR_MASK
        force_attrs = False
        if sgr_flags != new_sgr_flags:
            force_attrs = True
            v = term.get_cap('sgr',
                             new.attrs & AF_STANDOUT,
                             new.attrs & AF_UNDERLINE,
                             new.attrs & AF_REVERSE,
                             new.attrs & AF_BLINK,
                             new.attrs & AF_DIM,
                             new.attrs & AF_BOLD,
                             new.attrs & AF_INVIS,
                             new.attrs & AF_PROTECT,
                             new.attrs & AF_ALTCHARSET)
            ret.append(v)

        diffs = self.attrs ^ new.attrs
        for attr in ATTR_FLAGS_NON_SGR:
            if new.attrs & attr:
                if not (diffs & attr) and not force_attrs:
                    continue
                cap = ATTR_FLAGS_CAP_ON[attr]
            else:
                if not (diffs & attr):
                    continue
                cap = ATTR_FLAGS_CAP_OFF[attr]
            ret.append(term.get_cap(cap))
        return ret


class AttributeModifier:
    def __init__(self, **kwargs):
        self.attrs = 0
        self.attrs_mask = 0

        self.fg = None
        self.fg_set = False
        self.bg = None
        self.bg_set = False

        for name, value in kwargs.items():
            if name == 'fg':
                self.fg = value
                self.fg_set = True
            elif name == 'bg':
                self.bg = value
                self.bg_set = True
            elif name == 'on':
                self.attrs |= value
                self.attrs_mask |= value
            elif name == 'off':
                self.attrs &= ~value
                self.attrs_mask |= value
            else:
                raise TypeError('invalid keyword argument %r' % (name,))


class Color:
    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return self.value == other.value

    def __ne__(self, other):
        return self.value != other.value

    def get_fg_cap(self, term, bg):
        if self.value < 0:
            cap = term.get_cap('op')
            if bg.value >= 0:
                cap += bg.get_bg_cap(term, self)
            return cap

        # TODO: make sure the terminal supports this many colors
        return term.get_cap('setaf', self.value)

    def get_bg_cap(self, term, fg):
        if self.value < 0:
            cap = term.get_cap('op')
            if fg.value >= 0:
                cap += fg.get_fg_cap(term, self)
            return cap

        # TODO: make sure the terminal supports this many colors
        return term.get_cap('setab', self.value)


class RGBColor:
    def __init__(self, r, g, b):
        self.red = r
        self.green = g
        self.blue = b

    def get_red(self):
        return self.red

    def set_red(self, r):
        self.red = r

    def get_blue(self):
        return self.blue

    def set_blue(self, g):
        self.blue = g

    def get_green(self):
        return self.green

    def set_green(self, b):
        self.green = b

    r = property(get_red, set_red)
    g = property(get_red, set_red)
    b = property(get_red, set_red)


COLOR_DEFAULT = Color(-1)

# 8 basic colors, supported by most terminals
COLOR_BLACK = Color(0)
COLOR_RED = Color(1)
COLOR_GREEN = Color(2)
COLOR_YELLOW = Color(3)
COLOR_BLUE = Color(4)
COLOR_MAGENTA = Color(5)
COLOR_CYAN = Color(6)
COLOR_WHITE = Color(7)
# Supported by 16-color terminals (and also 88- and 256-color terminals)
COLOR_GREY = Color(8)
COLOR_BRIGHT_RED = Color(9)
COLOR_BRIGHT_GREEN = Color(10)
COLOR_BRIGHT_YELLOW = Color(11)
COLOR_BRIGHT_BLUE = Color(12)
COLOR_BRIGHT_MAGENTA = Color(13)
COLOR_BRIGHT_CYAN = Color(14)
COLOR_BRIGHT_WHITE = Color(15)
# 88-color terminals use colors 16-79 as a 4x4x4 RGB color cube,
# and colors 80-88 as a grayscale ramp
#
# 256-color terminals use colors 16-231 as a 6x6x6 RGB color cube,
# and colors 232-255 as a grayscale ramp from black to white

NAMED_COLORS = {
    'black': COLOR_BLACK,
    'red': COLOR_RED,
    'green': COLOR_GREEN,
    'yellow': COLOR_YELLOW,
    'blue': COLOR_BLUE,
    'magenta': COLOR_MAGENTA,
    'cyan': COLOR_CYAN,
    'white': COLOR_WHITE,
    'grey': COLOR_GREY,
    'gray': COLOR_GREY,
    'brightred': COLOR_BRIGHT_RED,
    'brightgreen': COLOR_BRIGHT_GREEN,
    'brightyellow': COLOR_BRIGHT_YELLOW,
    'brightblue': COLOR_BRIGHT_BLUE,
    'brightmagenta': COLOR_BRIGHT_MAGENTA,
    'brightcyan': COLOR_BRIGHT_CYAN,
    'brightwhite': COLOR_BRIGHT_WHITE,
}

AF_STANDOUT = 0x1
AF_UNDERLINE = 0x2
AF_REVERSE = 0x4
AF_BLINK = 0x8
AF_DIM = 0x10
AF_BOLD = 0x20
AF_INVIS = 0x40
AF_PROTECT = 0x80
AF_ALTCHARSET = 0x100
AF_ITALIC = 0x200
AF_SHADOW = 0x400
AF_SUBSCRIPT = 0x800
AF_SUPERSCRIPT = 0x1000

AF_ALL_MASK = 0x1fff
ATTR_FLAG_SGR_MASK = 0x1ff

A_STANDOUT = AttributeModifier(on=AF_STANDOUT)
A_UNDERLINE = AttributeModifier(on=AF_UNDERLINE)
A_REVERSE = AttributeModifier(on=AF_REVERSE)
A_BLINK = AttributeModifier(on=AF_BLINK)
A_DIM = AttributeModifier(on=AF_DIM)
A_BOLD = AttributeModifier(on=AF_BOLD)
A_INVIS = AttributeModifier(on=AF_INVIS)
A_PROTECT = AttributeModifier(on=AF_PROTECT)
A_ALTCHARSET = AttributeModifier(on=AF_ALTCHARSET)
A_ITALIC = AttributeModifier(on=AF_ITALIC)
A_SHADOW = AttributeModifier(on=AF_SHADOW)
A_SUBSCRIPT = AttributeModifier(on=AF_SUBSCRIPT)
A_SUPERSCRIPT = AttributeModifier(on=AF_SUPERSCRIPT)

ATTR_FLAGS_ALL = [
    AF_STANDOUT,
    AF_UNDERLINE,
    AF_REVERSE,
    AF_BLINK,
    AF_DIM,
    AF_BOLD,
    AF_INVIS,
    AF_PROTECT,
    AF_ALTCHARSET,
    AF_ITALIC,
    AF_SHADOW,
    AF_SUBSCRIPT,
    AF_SUPERSCRIPT,
]

ATTR_FLAGS_SGR = [
    AF_STANDOUT,
    AF_UNDERLINE,
    AF_REVERSE,
    AF_BLINK,
    AF_DIM,
    AF_BOLD,
    AF_INVIS,
    AF_PROTECT,
    AF_ALTCHARSET,
]

ATTR_FLAGS_NON_SGR = [
    AF_ITALIC,
    AF_SHADOW,
    AF_SUBSCRIPT,
    AF_SUPERSCRIPT,
]

ATTR_FLAGS_CAP_ON = {
    AF_STANDOUT: 'smso',
    AF_UNDERLINE: 'smul',
    AF_REVERSE: 'rev',
    AF_BLINK: 'blink',
    AF_DIM: 'dim',
    AF_BOLD: 'bold',
    AF_INVIS: 'invis',
    AF_PROTECT: 'prot',
    AF_ALTCHARSET: 'smacs',
    AF_ITALIC: 'sitm',
    AF_SHADOW: 'sshm',
    AF_SUBSCRIPT: 'ssubm',
    AF_SUPERSCRIPT: 'ssupm',
}

ATTR_FLAGS_CAP_OFF = {
    AF_STANDOUT: 'rmso',
    AF_UNDERLINE: 'rmul',
    # AF_REVERSE: None,
    # AF_BLINK: None,
    # AF_DIM: None,
    # AF_BOLD: None,
    # AF_INVIS: None,
    # AF_PROTECT: None,
    AF_ALTCHARSET: 'rmacs',
    AF_ITALIC: 'ritm',
    AF_SHADOW: 'rshm',
    AF_SUBSCRIPT: 'rsubm',
    AF_SUPERSCRIPT: 'rsupm',
}

ATTRIBUTE_MODIFIERS = {
    'normal': AttributeModifier(off=AF_ALL_MASK,
                                fg=COLOR_DEFAULT, bg=COLOR_DEFAULT),
    'standout': A_STANDOUT,
    'underline': A_UNDERLINE,
    'reverse': A_REVERSE,
    'blink': A_BLINK,
    'dim': A_DIM,
    'bold': A_BOLD,
    'invis': A_INVIS,
    'invisible': A_INVIS,
    'protect': A_PROTECT,
    'italic': A_ITALIC,
    'shadow': A_SHADOW,
    'superscript': A_SUPERSCRIPT,
    'subscript': A_SUBSCRIPT,
}
for name, color in NAMED_COLORS.items():
    ATTRIBUTE_MODIFIERS[name] = AttributeModifier(fg=color)
    ATTRIBUTE_MODIFIERS['fg='+name] = AttributeModifier(fg=color)
    ATTRIBUTE_MODIFIERS['bg='+name] = AttributeModifier(bg=color)
