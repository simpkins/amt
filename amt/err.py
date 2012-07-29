#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
class AMTError(Exception):
    def __init__(self, msg, *args):
        if args:
            self.msg = msg % args
        else:
            self.msg = msg

    def __str__(self):
        return self.msg
