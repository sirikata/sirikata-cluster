#!/usr/bin/env python

import config, data
from boto.ec2.connection import EC2Connection
import json, os

def instance_name(cname, idx):
    return cname + '-' + str(idx)

class ClusterConfigFile(object):
    '''Tracks info about a cluster, backed by a json file'''

    param_names = ['name', 'size', 'keypair', 'instance_type', 'group', 'ami', 'puppet_master', 'state']

    def __init__(self, name,
                 size=None, keypair=None, instance_type=None, group=None, ami=None, puppet_master=None):
        '''Specify either a name only, which loads from a file, or *all* the parameters'''
        if not size: # if one other value isn't defined, must have file
            values = json.load(open(self._filename(name), 'r'))
            for name in self.param_names:
                setattr(self, name, values[name])
        else:
            assert(name and size and keypair and instance_type and group and ami and puppet_master)
            self.name = name
            self.size = size
            self.keypair = keypair
            self.instance_type = instance_type
            self.group = group
            self.ami = ami
            self.puppet_master = puppet_master

            # Everything else is temporary/mutable state that we just
            # want to keep track of for future operations
            self.state = {}

    def _filename(self, newname=None):
        return '.cluster-config-' + (newname or self.name) + '.json'

    def save(self):
        data = dict([(name, getattr(self, name)) for name in self.param_names])
        json.dump(data, open(self._filename(), 'w'), indent=4)

    def delete(self):
        os.remove(self._filename())


def create(*args, **kwargs):
    """cluster create name size puppet_master keypair [--instance-type=t1.micro] [--group=security_group] [--ami=i-x7395]

    Create a new cluster. This just creates a record of the cluster
    and saves its properties, it doesn't actually allocate any nodes.
    """
    # Get parameters
    if len(args) != 4: # name size puppet_master keypair
        print "Incorrect parameters to create cluster."""
        exit(1)
    name = args[0]
    size = int(args[1])
    puppet_master = args[2]
    keypair = args[3]

    instance_type = config.kwarg_or_get('instance-type', kwargs, 'INSTANCE_TYPE')
    group = config.kwarg_or_get('group', kwargs, 'SECURITY_GROUP')
    ami = config.kwarg_or_get('ami', kwargs, 'BASE_AMI')

    cc = ClusterConfigFile(name,
                           size=size, keypair=keypair,
                           instance_type=instance_type,
                           group=group, ami=ami,
                           puppet_master=puppet_master)
    cc.save()

def boot(*args, **kwargs):
    """cluster nodes boot name

    Boot a cluster's nodes.
    """
    # Get parameters
    if len(args) != 1: # name
        print "Incorrect parameters to cluster boot."""
        exit(1)
    name = args[0]

    cc = ClusterConfigFile(name)

    if 'reservation' in cc.state or 'instances' in cc.state:
        print "It looks like you already have active nodes for this cluster..."
        exit(1)

    # Load the setup script template, replace puppet master info
    user_data = data.load('ec2-user-data', 'node-setup.sh')
    user_data = user_data.replace('{{{PUPPET_MASTER}}}', cc.puppet_master)

    # Now create the nodes
    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
    reservation = conn.run_instances(cc.ami,
                                     min_count=cc.size, max_count=cc.size,
                                     key_name=cc.keypair,
                                     instance_type=cc.instance_type,
                                     security_groups=[cc.group],
                                     user_data=user_data
                                     )

    # Save reservation, instance info
    cc.state['reservation'] = reservation.id
    cc.state['instances'] = [inst.id for inst in reservation.instances]

    # Name the nodes
    for idx,inst in enumerate(reservation.instances):
        conn.create_tags([inst.id], {"Name": instance_name(name, idx)})

def members_address(*args, **kwargs):
    """cluster members address list cluster_name

    Get a list of members addresses. This is used to seed the list of
    members in a corosync configuration (which you'll do through
    puppet).
    """
    # Get parameters
    if len(args) != 1: # name
        print "Incorrect parameters to cluster members address list."""
        exit(1)
    name = args[0]

    cc = ClusterConfigFile(name)

    if 'reservation' not in cc.state or 'instances' not in cc.state:
        print "It doesn't look like you've booted the cluster yet..."
        exit(1)

    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
    instances_info = conn.get_all_instances(instance_ids = cc.state['instances'])
    # Should get back a list of one reservation
    instances_info = instances_info[0].instances
    ips = [inst.ip_address for inst in instances_info]

    corosync_conf = data.load('corosync', 'corosync.conf.template')
    member_section = ""
    for ip in ips:
        member_section += """
                member {
                        memberaddr: %s
                }""" % (ip)

    corosync_conf = corosync_conf.replace('{{{MEMBERS}}}', member_section)
    data.save(corosync_conf, 'puppet', 'templates', 'corosync.conf')

    print
    print "These are the addresses I found:", ips
    print """
I've generated a configuration template that Puppet needs to use to
configure clients. I've saved it in
data/puppet/templates/corosync.conf. You need to put it into your
Puppet master's configuration
directory. If you're running the Puppet master locally, run

  sudo cp data/puppet/templates/corosync.conf /etc/puppet/templates/corosync.conf

"""

def node_ssh(*args, **kwargs):
    """cluster node ssh name cluster_name index pemfile

    Spawn an SSH process that SSHs into the node
    """
    # Get parameters
    if len(args) != 3: # name, index, pemfile
        print "Incorrect parameters to cluster node ssh."""
        exit(1)
    name = args[0]
    idx = int(args[1])
    pemfile = args[2]

    cc = ClusterConfigFile(name)

    if 'reservation' not in cc.state or 'instances' not in cc.state:
        print "It doesn't look like you've booted the cluster yet..."
        exit(1)

    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
    instances_info = conn.get_all_instances(instance_ids = [ cc.state['instances'][idx] ])
    # Should get back a list of one reservation with one instance in it
    instance_info = instances_info[0].instances[0]
    pub_dns_name = instance_info.public_dns_name

    cmd = os.execl("/usr/bin/ssh", "ssh", "-i", pemfile, "ubuntu@" + pub_dns_name)

def terminate(*args, **kwargs):
    """cluster nodes terminate name

    Terminate an existing cluster
    """
    if len(args) != 1: # name
        print "Incorrect parameters to cluster boot."""
        exit(1)
    name = args[0]

    cc = ClusterConfigFile(name)
    if 'instances' not in cc.state:
        print "No active instances were found, are you sure this cluster is currently running?"
        exit(1)

    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
    terminated = conn.terminate_instances(cc.state['instances'])

    if len(terminated) != len(cc.state['instances']):
        print "The set of terminated nodes doesn't match the complete set of instances, you may need to clean some up manually."
        print "Instances:", cc.state['instances']
        print "Terminated Instances:", terminated
        print "Unterminated:", list(set(cc.state['instances']).difference(set(terminated)))

    del cc.state['instances']
    del cc.state['reservation']

    cc.save()

def destroy(*args, **kwargs):
    """cluster destroy name

    Terminate an existing cluster
    """

    if len(args) != 1: # name
        print "Incorrect parameters to cluster boot."""
        exit(1)
    name = args[0]

    cc = ClusterConfigFile(name)
    if 'reservation' in cc.state or 'instances' in cc.state:
        print "You have an active reservation or nodes, use 'cluster terminate nodes' before destroying this cluster spec."
        exit(1)

    cc.delete()
