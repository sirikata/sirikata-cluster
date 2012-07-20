# Sanity check dependencies
try:
    from boto.ec2.connection import EC2Connection
except:
    print "Couldn't find required dependency: boto. Check the README for how to install dependencies."
    exit(1)

# The important export
from nodegroup import NodeGroup
