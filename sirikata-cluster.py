#!/usr/bin/env python

"""
Usage: sirikata-cluster.py command [args]

This is the driver script for sirikata-cluster.
"""

import cluster.util.config as config
import cluster.ec2 as ec2
import sys

# Parse config options, currently only from the environment variables
config.env()
# Check that basic set of configuration options are available
config.check_config()

# Setup all our command handlers
handlers = ec2.handlers

def usage(code=1):
    print """
Usage: sirikata-cluster.py command [args]

Available commands:
"""
    for k,v in handlers.items():
        print k
    print
    exit(code)



# Parse the command
args = list(sys.argv)
# Get rid of everything up to this script name
while args and args[0].endswith(__file__):
    args.pop(0)
if not args:
    usage()

# Match n next parts to a command
command = None
for nparts in range(1, len(args)+1):
    command = ' '.join(args[0:nparts])
    if command in handlers:
        args = args[nparts:]
        break
if command not in handlers:
    usage()

# Split remaining args as positional and keyword
pargs = []
kwargs = {}
more_kwargs = True
for arg in args:
    # Allows you to stop us from parsing kwargs, leaving them as
    # positional arguments so that when a command is passed along to a
    # subprocess (e.g. ssh) it can just be specified as additional
    # arguments even if the subcommand has --key=value type
    # arguments. We only accept this once so you can 'escape' it if
    # your subcommand *also* needs '--' in it.
    if arg == '--' and more_kwargs:
        more_kwargs = False
        continue
    if more_kwargs and '=' in arg or arg.startswith('--'):
        if '=' in arg:
            k,v = arg.split('=', 1)
        else:
            k,v = (arg,True)
        if k.startswith('--'): k = k[2:]
        kwargs[k] = v
    else:
        pargs.append(arg)
exit(handlers[command](*pargs, **kwargs))
