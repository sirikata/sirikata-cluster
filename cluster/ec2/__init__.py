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
handlers = {
    'cluster security create' : nodes.create_security_group,
    'cluster create' : nodes.create,
    'cluster nodes boot' : nodes.boot,
    'cluster members address list' : nodes.members_address,
    'cluster members info' : nodes.members_info,
    'cluster node ssh' : nodes.node_ssh,
    'cluster ssh' : nodes.ssh,
    'cluster fix corosync' : nodes.fix_corosync,
    'cluster add service' : nodes.add_service,
    'cluster remove service' : nodes.remove_service,
    'cluster node set type' : nodes.set_node_type,
    'cluster status' : nodes.status,
    'cluster nodes terminate' : nodes.terminate,
    'cluster destroy' : nodes.destroy,

    'puppet master config' : puppet.master_config,
    'puppet slaves restart' : puppet.slaves_restart,
    'puppet update' : puppet.update,

    'sirikata package' : sirikata.package
}
