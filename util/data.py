#!/usr/bin/env python

# Utilities for getting data from within the repo

import os.path

# Need to figure out where the data directory is
CURDIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(CURDIR), 'data')

def path(*args):
    return os.path.join(DATA_DIR, *args)

def load(*args):
    with open(path(*args), 'rb') as fp:
        return fp.read()

def save(data, *args):
    with open(path(*args), 'wb') as fp:
        return fp.write(data)
