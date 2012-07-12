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
    """cluster boot nodes name

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
    cc.data['reservation'] = reservation.id
    cc.data['instances'] = [inst.id for inst in reservation.instances]

    # Name the nodes
    for idx,inst in enumerate(reservation.instances):
        conn.create_tags([inst.id], {"Name": instance_name(name, idx)})

def terminate(*args, **kwargs):
    """cluster terminate nodes name

    Terminate an existing cluster
    """
    if len(args) != 1: # name
        print "Incorrect parameters to cluster boot."""
        exit(1)
    name = args[0]

    cc = ClusterConfigFile(name)
    if 'instances' not in cc.data:
        print "No active instances were found, are you sure this cluster is currently running?"
        exit(1)

    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
    terminated = conn.terminate_instances(cc.data['instances'])

    if len(terminated) != len(cc.data['instances']):
        print "The set of terminated nodes doesn't match the complete set of instances, you may need to clean some up manually."
        print "Instances:", cc.data['instances']
        print "Terminated Instances:", terminated
        print "Unterminated:", list(set(cc.data['instances']).difference(set(terminated)))

    del cc.data['instances']
    del cc.data['reservations']

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
