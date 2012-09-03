#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import curses
import errno
import logging
import os
import select
import threading


class EscapedKey:
    def __init__(self, name, cap, description):
        self.name = name.upper()
        self.cap = cap
        self.description = description

    def __str__(self):
        return self.name

    def __repr__(self):
        return 'EscapedKey(%r)' % (self.name,)


class TermInput:
    def __init__(self, fileno, escape_table=None, encoding='utf-8'):
        self.fileno = fileno
        self.read_bufsize = 128

        if escape_table is None:
            escape_table = build_escape_table()
        self.escape_table = escape_table

        self.poll = select.poll()
        self.poll.register(self.fileno, select.POLLIN)
        self._buffer = bytearray()
        self.escape_time = 0.005

        self.on_resize = None
        self._resized = threading.Event()

    def signal_resize(self):
        '''
        Signal that a resize has occurred, and should be processed on the next
        call to getch().
        '''
        self._resized.set()

    def _check_resize(self):
        if self._resized.is_set():
            self._resized.clear()
            if self.on_resize is not None:
                self.on_resize()

    def getch(self, escape_time=None):
        if escape_time is None:
            escape_time = self.escape_time
        self._check_resize()

        # If we already have a full keycode in the buffer,
        # return it without trying to read more data
        ch = self._pop_keycode()
        if ch is not None:
            return ch

        end = None
        timeout = None
        while True:
            try:
                self.poll.poll(timeout)
                data = os.read(self.fileno, self.read_bufsize)
            except IOError as ex:
                if ex.errno != errno.EINTR:
                    raise
                self._check_resize()
                continue

            self._buffer.extend(data)

            # Check to see if we have a full keycode now
            ch = self._pop_keycode()
            if ch is not None:
                return ch

            # Not a full keycode.  We have to wait for more data.
            if end is None:
                if timeout is None or timeout <= 0:
                    # Return whatever data we have immediately
                    break
                end = time.time() + escape_time
                timeout = escape_time
            else:
                now = time.time()
                if now >= end:
                    break
                timeout = end - now

        # We ran out of time.  Just return the first byte we have,
        # even though it isn't a full key code.
        return self._pop_byte()

    def _pop_keycode(self):
        if not self._buffer:
            return None

        k = self._buffer[0]
        # Check for the start of an escape sequence
        if k in self.escape_table:
            return self._pop_escape_seq()

        # TODO: For now, we only support UTF-8.
        # It would be nice to support using an IncrementalDecoder from
        # the codecs module.  Unfortunately, the IncrementalDecoder API doesn't
        # seem to have any way to ensure that the decoder will flush output as
        # soon as it can.  We don't seem to have any easy way to force it to
        # flush whenever it has received a full character.

        # Handle the simple case of an ASCII character
        if k <= 0x7f:
            self._buffer = self._buffer[1:]
            return chr(k)

        # This is the start of a UTF-8 encoded character
        # (For simplicity, at the moment we assume all input is UTF-8.)
        idx = 0
        for idx, k in enumerate(self._buffer):
            if k <= 0x7f:
                assert idx > 0
                # previous data was bogus utf-8 input
                return self._pop(idx, decode=True)
            elif (k & 0xc0) == 0x80:
                return self._pop(idx + 1, decode=True)

        return None

    def _pop_escape_seq(self):
        cur_map = self.escape_table
        for idx, k in enumerate(self._buffer):
            old_map = cur_map
            cur_map = cur_map.get(k)
            if cur_map is None:
                # This doesn't match any escape sequence we know about
                return self._pop_byte()

            key = cur_map.get(None)
            if key is not None:
                self._pop(idx + 1, decode=False)
                return key

        # This is a prefix of a known escape sequence.
        # Return None, to wait for a timeout or the rest of the sequence
        return None

    def _pop_byte(self, decode=True):
        if not self._buffer:
            return None

        return self._pop(1, decode=decode)

    def _pop(self, length, decode):
        ret = self._buffer[:length]
        self._buffer = self._buffer[length:]
        if decode:
            return ret.decode('utf-8', errors='surrogateescape')
        else:
            return ret


def build_escape_table():
    escape_table = {}

    global _escape_keys
    for key in _escape_keys:
        value = curses.tigetstr(key.cap)
        if not value:
            continue

        cur = escape_table
        for c in value:
            if None in cur:
                # We won't ever be able to match the current key,
                # since another key is a prefix of it
                logging.warning('conflicting key strings: %s and %s',
                                cur[None], key)
            cur = cur.setdefault(c, {})

        # We won't ever be able to match any of the keys currently
        # in this mapping, since this key is a prefix of them.
        if cur:
            logging.warning('conflicting key strings: %s and %s',
                            cur[None], ', '.join(str(k) for k in cur.values()))

        cur[None] = key

    return escape_table


_escape_keys = [
    EscapedKey('key_a1', 'ka1', 'upper left of keypad'),
    EscapedKey('key_a3', 'ka3', 'upper right of keypad'),
    EscapedKey('key_b2', 'kb2', 'center of keypad'),
    EscapedKey('key_backspace', 'kbs', 'backspace key'),
    EscapedKey('key_beg', 'kbeg', 'begin key'),
    EscapedKey('key_btab', 'kcbt', 'back-tab key'),
    EscapedKey('key_c1', 'kc1', 'lower left of keypad'),
    EscapedKey('key_c3', 'kc3', 'lower right of keypad'),
    EscapedKey('key_cancel', 'kcan', 'cancel key'),
    EscapedKey('key_catab', 'ktbc', 'clear-all-tabs key'),
    EscapedKey('key_clear', 'kclr', 'clear-screen or erase key'),
    EscapedKey('key_close', 'kclo', 'close key'),
    EscapedKey('key_command', 'kcmd', 'command key'),
    EscapedKey('key_copy', 'kcpy', 'copy key'),
    EscapedKey('key_create', 'kcrt', 'create key'),
    EscapedKey('key_ctab', 'kctab', 'clear-tab key'),
    EscapedKey('key_dc', 'kdch1', 'delete-character key'),
    EscapedKey('key_dl', 'kdl1', 'delete-line key'),
    EscapedKey('key_down', 'kcud1', 'down-arrow key'),
    EscapedKey('key_eic', 'krmir', 'sent by rmir or smir in insert mode'),
    EscapedKey('key_end', 'kend', 'end key'),
    EscapedKey('key_enter', 'kent', 'enter/send key'),
    EscapedKey('key_eol', 'kel', 'clear-to-end-of-line key'),
    EscapedKey('key_eos', 'ked', 'clear-to-end-of-screen key'),
    EscapedKey('key_exit', 'kext', 'exit key'),
    EscapedKey('key_f0', 'kf0', 'F0 function key'),
    EscapedKey('key_f1', 'kf1', 'F1 function key'),
    EscapedKey('key_f10', 'kf10', 'F10 function key'),
    EscapedKey('key_f11', 'kf11', 'F11 function key'),
    EscapedKey('key_f12', 'kf12', 'F12 function key'),
    EscapedKey('key_f13', 'kf13', 'F13 function key'),
    EscapedKey('key_f14', 'kf14', 'F14 function key'),
    EscapedKey('key_f15', 'kf15', 'F15 function key'),
    EscapedKey('key_f16', 'kf16', 'F16 function key'),
    EscapedKey('key_f17', 'kf17', 'F17 function key'),
    EscapedKey('key_f18', 'kf18', 'F18 function key'),
    EscapedKey('key_f19', 'kf19', 'F19 function key'),
    EscapedKey('key_f2', 'kf2', 'F2 function key'),
    EscapedKey('key_f20', 'kf20', 'F20 function key'),
    EscapedKey('key_f21', 'kf21', 'F21 function key'),
    EscapedKey('key_f22', 'kf22', 'F22 function key'),
    EscapedKey('key_f23', 'kf23', 'F23 function key'),
    EscapedKey('key_f24', 'kf24', 'F24 function key'),
    EscapedKey('key_f25', 'kf25', 'F25 function key'),
    EscapedKey('key_f26', 'kf26', 'F26 function key'),
    EscapedKey('key_f27', 'kf27', 'F27 function key'),
    EscapedKey('key_f28', 'kf28', 'F28 function key'),
    EscapedKey('key_f29', 'kf29', 'F29 function key'),
    EscapedKey('key_f3', 'kf3', 'F3 function key'),
    EscapedKey('key_f30', 'kf30', 'F30 function key'),
    EscapedKey('key_f31', 'kf31', 'F31 function key'),
    EscapedKey('key_f32', 'kf32', 'F32 function key'),
    EscapedKey('key_f33', 'kf33', 'F33 function key'),
    EscapedKey('key_f34', 'kf34', 'F34 function key'),
    EscapedKey('key_f35', 'kf35', 'F35 function key'),
    EscapedKey('key_f36', 'kf36', 'F36 function key'),
    EscapedKey('key_f37', 'kf37', 'F37 function key'),
    EscapedKey('key_f38', 'kf38', 'F38 function key'),
    EscapedKey('key_f39', 'kf39', 'F39 function key'),
    EscapedKey('key_f4', 'kf4', 'F4 function key'),
    EscapedKey('key_f40', 'kf40', 'F40 function key'),
    EscapedKey('key_f41', 'kf41', 'F41 function key'),
    EscapedKey('key_f42', 'kf42', 'F42 function key'),
    EscapedKey('key_f43', 'kf43', 'F43 function key'),
    EscapedKey('key_f44', 'kf44', 'F44 function key'),
    EscapedKey('key_f45', 'kf45', 'F45 function key'),
    EscapedKey('key_f46', 'kf46', 'F46 function key'),
    EscapedKey('key_f47', 'kf47', 'F47 function key'),
    EscapedKey('key_f48', 'kf48', 'F48 function key'),
    EscapedKey('key_f49', 'kf49', 'F49 function key'),
    EscapedKey('key_f5', 'kf5', 'F5 function key'),
    EscapedKey('key_f50', 'kf50', 'F50 function key'),
    EscapedKey('key_f51', 'kf51', 'F51 function key'),
    EscapedKey('key_f52', 'kf52', 'F52 function key'),
    EscapedKey('key_f53', 'kf53', 'F53 function key'),
    EscapedKey('key_f54', 'kf54', 'F54 function key'),
    EscapedKey('key_f55', 'kf55', 'F55 function key'),
    EscapedKey('key_f56', 'kf56', 'F56 function key'),
    EscapedKey('key_f57', 'kf57', 'F57 function key'),
    EscapedKey('key_f58', 'kf58', 'F58 function key'),
    EscapedKey('key_f59', 'kf59', 'F59 function key'),
    EscapedKey('key_f6', 'kf6', 'F6 function key'),
    EscapedKey('key_f60', 'kf60', 'F60 function key'),
    EscapedKey('key_f61', 'kf61', 'F61 function key'),
    EscapedKey('key_f62', 'kf62', 'F62 function key'),
    EscapedKey('key_f63', 'kf63', 'F63 function key'),
    EscapedKey('key_f7', 'kf7', 'F7 function key'),
    EscapedKey('key_f8', 'kf8', 'F8 function key'),
    EscapedKey('key_f9', 'kf9', 'F9 function key'),
    EscapedKey('key_find', 'kfnd', 'find key'),
    EscapedKey('key_help', 'khlp', 'help key'),
    EscapedKey('key_home', 'khome', 'home key'),
    EscapedKey('key_ic', 'kich1', 'insert-character key'),
    EscapedKey('key_il', 'kil1', 'insert-line key'),
    EscapedKey('key_left', 'kcub1', 'left-arrow key'),
    EscapedKey('key_ll', 'kll', 'lower-left key (home down)'),
    EscapedKey('key_mark', 'kmrk', 'mark key'),
    EscapedKey('key_message', 'kmsg', 'message key'),
    EscapedKey('key_move', 'kmov', 'move key'),
    EscapedKey('key_next', 'knxt', 'next key'),
    EscapedKey('key_npage', 'knp', 'next-page key'),
    EscapedKey('key_open', 'kopn', 'open key'),
    EscapedKey('key_options', 'kopt', 'options key'),
    EscapedKey('key_ppage', 'kpp', 'previous-page key'),
    EscapedKey('key_previous', 'kprv', 'previous key'),
    EscapedKey('key_print', 'kprt', 'print key'),
    EscapedKey('key_redo', 'krdo', 'redo key'),
    EscapedKey('key_reference', 'kref', 'reference key'),
    EscapedKey('key_refresh', 'krfr', 'refresh key'),
    EscapedKey('key_replace', 'krpl', 'replace key'),
    EscapedKey('key_restart', 'krst', 'restart key'),
    EscapedKey('key_resume', 'kres', 'resume key'),
    EscapedKey('key_right', 'kcuf1', 'right-arrow key'),
    EscapedKey('key_save', 'ksav', 'save key'),
    EscapedKey('key_sbeg', 'kBEG', 'shifted begin key'),
    EscapedKey('key_scancel', 'kCAN', 'shifted cancel key'),
    EscapedKey('key_scommand', 'kCMD', 'shifted command key'),
    EscapedKey('key_scopy', 'kCPY', 'shifted copy key'),
    EscapedKey('key_screate', 'kCRT', 'shifted create key'),
    EscapedKey('key_sdc', 'kDC', 'shifted delete-character key'),
    EscapedKey('key_sdl', 'kDL', 'shifted delete-line key'),
    EscapedKey('key_select', 'kslt', 'select key'),
    EscapedKey('key_send', 'kEND', 'shifted end key'),
    EscapedKey('key_seol', 'kEOL', 'shifted clear-to-end-of-line key'),
    EscapedKey('key_sexit', 'kEXT', 'shifted exit key'),
    EscapedKey('key_sf', 'kind', 'scroll-forward key'),
    EscapedKey('key_sfind', 'kFND', 'shifted find key'),
    EscapedKey('key_shelp', 'kHLP', 'shifted help key'),
    EscapedKey('key_shome', 'kHOM', 'shifted home key'),
    EscapedKey('key_sic', 'kIC', 'shifted insert-character key'),
    EscapedKey('key_sleft', 'kLFT', 'shifted left-arrow key'),
    EscapedKey('key_smessage', 'kMSG', 'shifted message key'),
    EscapedKey('key_smove', 'kMOV', 'shifted move key'),
    EscapedKey('key_snext', 'kNXT', 'shifted next key'),
    EscapedKey('key_soptions', 'kOPT', 'shifted options key'),
    EscapedKey('key_sprevious', 'kPRV', 'shifted previous key'),
    EscapedKey('key_sprint', 'kPRT', 'shifted print key'),
    EscapedKey('key_sr', 'kri', 'scroll-backward key'),
    EscapedKey('key_sredo', 'kRDO', 'shifted redo key'),
    EscapedKey('key_sreplace', 'kRPL', 'shifted replace key'),
    EscapedKey('key_sright', 'kRIT', 'shifted right-arrow key'),
    EscapedKey('key_srsume', 'kRES', 'shifted resume key'),
    EscapedKey('key_ssave', 'kSAV', 'shifted save key'),
    EscapedKey('key_ssuspend', 'kSPD', 'shifted suspend key'),
    EscapedKey('key_stab', 'khts', 'set-tab key'),
    EscapedKey('key_sundo', 'kUND', 'shifted undo key'),
    EscapedKey('key_suspend', 'kspd', 'suspend key'),
    EscapedKey('key_undo', 'kund', 'undo key'),
    EscapedKey('key_up', 'kcuu1', 'up-arrow key'),
    EscapedKey('keypad_local', 'rmkx', 'leave keyboard_transmit mode'),
    EscapedKey('keypad_xmit', 'smkx', 'enter keyboard_transmit mode'),
]


class ControlKey:
    def __init__(self, value, name=None):
        self.value = value
        if name is None:
            char = chr(ord('a') + value - 1)
            name = 'KEY_CTRL_' + char.upper()
        self.name = name


_control_keys = [ControlKey(n) for n in range(1, 27)]
_control_keys.append(ControlKey(27, 'KEY_CTRL_LBRACKET'))
_control_keys.append(ControlKey(28, 'KEY_CTRL_BACKSLASH'))
_control_keys.append(ControlKey(29, 'KEY_CTRL_RBRACKET'))
_control_keys.append(ControlKey(30, 'KEY_CTRL_CARET'))
_control_keys.append(ControlKey(31, 'KEY_CTRL_UNDERSCORE'))


def define_key_constants(namespace):
    for key in _escape_keys:
        namespace[key.name] = key

    for key in _control_keys:
        namespace[key.name] = chr(key.value)

    namespace['KEY_ESCAPE'] = '\x1b'

define_key_constants(globals())
