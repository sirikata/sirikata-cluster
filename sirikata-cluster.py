#!/usr/bin/env python

"""
Usage: sirikata-cluster.py command [args]

This is the driver script for sirikata-cluster.
"""

# Sanity check dependencies
try:
    from boto.ec2.connection import EC2Connection
except:
    print "Couldn't find required dependency: boto. Check the README for how to install dependencies."
    exit(1)

import util.config as config
import util.cluster as cluster
import sys

# Parse config options, currently only from the environment variables
config.env()
# Check that basic set of configuration options are available
config.check_config()


# Setup all our command handlers
handlers = {
    'cluster create' : cluster.create,
    'cluster boot nodes' : cluster.boot,
    'cluster terminate nodes' : cluster.terminate,
    'cluster destroy' : cluster.destroy
}

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
for arg in args:
    if '=' in arg:
        k,v = arg.split('=', 1)
        if k.startswith('--'): k = k[2:]
        kwargs[k] = v
    else:
        pargs.append(arg)
exit(handlers[command](*pargs, **kwargs))
