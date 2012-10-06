#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import readline

from amt.term import widgets

from .err import QuitError, QuitModeError


class MailMode(widgets.Drawable):
    def __init__(self, region):
        super(MailMode, self).__init__(region)

        self.header = self.subregion(0, 0, 0, 1)
        self.footer = self.subregion(0, -2, 0, 1)
        self.msg_area = self.subregion(0, -1, 0, 1)
        self.main_region = self.subdrawable(0, 1, 0, -2)

    def run(self):
        assert self.visible
        self.redraw()

        while True:
            ch = self.term.getch()
            try:
                self.process_key(ch)
            except QuitModeError:
                self.leave_mode()
                self.visible = False
                return

    def leave_mode(self):
        pass

    def process_key(self, key):
        cmd = self.key_bindings.get(key)
        if cmd is None:
            self.user_msg('no binding for key: {!r}', key)
            return

        cmd()

    def set_header(self, fmt, *args, **kwargs):
        self.header.vwriteln(0, fmt, args, kwargs)

    def set_footer(self, fmt, *args, **kwargs):
        self.footer.vwriteln(0, fmt, args, kwargs)

    def clear_msg(self, flush=True):
        self.msg_area.vwriteln(0, '', (), {})
        if flush:
            self.term.flush()

    def user_msg(self, fmt, *args, **kwargs):
        self.msg_area.vwriteln(0, fmt, args, kwargs)
        self.term.flush()

    def readline(self, prompt, first_char=None):
        if first_char is not None:
            def startup_hook():
                readline.insert_text(first_char)
                readline.set_startup_hook(None)
            readline.set_startup_hook(startup_hook)

        with self.term.shell_mode():
            line = input(prompt)

        return line

    def cmd_quit(self):
        raise QuitError()

    def cmd_quit_mode(self):
        raise QuitModeError()
