#!/usr/bin/env python

# Configuration options for interacting with AWS.

import os, sys

_config_names = [
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY',

    'BASE_AMI', # base AMI used for installation
    'INSTANCE_TYPE', # instance type, e.g. t1.micro
    'SECURITY_GROUP', # EC2 security group, affects firewall settings

    'SIRIKATA_CLUSTER_PEMFILE' # pemfile key for ssh'ing into nodes
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
    if name is not None:
        if hasattr(sys.modules[__name__], name) and getattr(sys.modules[__name__], name):
            return getattr(sys.modules[__name__], name)
    if default is not None: return default
    print "Couldn't find required configuration parameter: %s" % (name)
    exit(1)


def kwarg_or_get(kwarg_key, kwargs, config=None, default=None):
    if kwarg_key in kwargs: return kwargs[kwarg_key]
    return get(config, default=default)




def ask_user_bool(msg, default=False):
    print msg,
    while True:
        resp = raw_input().strip().lower()
        if len(resp) == 0: return default
        if resp in [ 'n', 'no', '0' ]: return False
        if resp in [ 'y', 'yes', '1' ]: return True
        print 'Invalid response, try again:',
