# Sanity check dependencies
try:
    from boto.ec2.connection import EC2Connection
except:
    print "Couldn't find required dependency: boto. Check the README for how to install dependencies."
    exit(1)

import nodes
import puppet
import sirikata

# "Export" command handlers
handlers = [
    ('ec2 security create', nodes.create_security_group),
    ('ec2 create', nodes.create),
    ('ec2 nodes boot', nodes.boot),
    ('ec2 members address list', nodes.members_address),
    ('ec2 members info', nodes.members_info),
    ('ec2 node ssh', nodes.node_ssh),
    ('ec2 ssh', nodes.ssh),
    ('ec2 fix corosync', nodes.fix_corosync),
    ('ec2 add service', nodes.add_service),
    ('ec2 remove service', nodes.remove_service),
    ('ec2 node set type', nodes.set_node_type),
    ('ec2 status', nodes.status),
    ('ec2 nodes terminate', nodes.terminate),
    ('ec2 destroy', nodes.destroy),

    ('puppet master config', puppet.master_config),
    ('puppet slaves restart', puppet.slaves_restart),
    ('puppet update', puppet.update),

    ('sirikata package', sirikata.package)
]
