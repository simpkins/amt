#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import os
from distutils.core import setup

def find_packages(directory):
    # setuptools.find_packages() doesn't appear to exist any more in
    # python 3.3.
    results = []
    for entry in os.listdir(directory):
        if entry == '__init__.py':
            results.append(directory)
            continue
        full_path = os.path.join(directory, entry)
        if os.path.isdir(full_path):
            results.extend(find_packages(full_path))

    return results

setup(
    name='amt',
    version='0.1',
    description='Adam\'s Mail Tools',
    author='Adam Simpkins',
    author_email='adam@adamsimpkins.net',
    packages=find_packages('amt'),
    scripts=[
        'amt_client.py',
        'amt_init.py',
        'amt_import.py',
        'amt_fetchmail.py',
    ],
)
