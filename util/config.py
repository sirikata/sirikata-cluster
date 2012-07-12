#!/usr/bin/env python

# Configuration options for interacting with AWS.

import os, sys

_config_names = [
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY',

    'BASE_AMI' # base AMI used for installation
    'INSTANCE_TYPE' # instance type, e.g. t1.micro
    'SECURITY_GROUP' # EC2 security group, affects firewall settings
]
_required_config_names = [
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY'
]


def check_env(varname):
    if varname in os.environ:
        setattr(sys.modules[__name__], varname, os.environ[varname])

def env():
    for name in _config_names:
        check_env(name)



def check_config():
    '''Validate the configuration for required configuration options.'''
    for name in _required_config_names:
        if not hasattr(sys.modules[__name__], name) or not getattr(sys.modules[__name__], name):
            print "Couldn't find configuration parameter %s" % (name)
            exit(1)


def get(name, default=None):
    if hasattr(sys.modules[__name__], name) and getattr(sys.modules[__name__], name):
        return getattr(sys.modules[__name__], name)
    if default: return default
    print "Couldn't find required configuration parameter: %s" % (name)
    exit(1)


def kwarg_or_get(kwarg_key, kwargs, config, default=None):
    if kwarg_key in kwargs: return kwargs[kwarg_key]
    get(config, default=default)
