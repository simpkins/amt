#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import imp
import os


def load_config(path):
    # Import the configuration from the specified path
    # Always import it using the 'amt_config' module name, so that it
    # won't conflict with any system modules or any of our own module names.
    dirname, basename = os.path.split(path)
    info = imp.find_module(basename, [dirname])
    config = imp.load_module('amt_config', *info)
    return config
