#!/usr/bin/env python

import config, data, arguments
from boto.ec2.connection import EC2Connection
import json, os, time, subprocess

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


def create_security_group(*args, **kwargs):
    """cluster security create security_group_name security_group_description

    Create a new security group with settings reasonable for a
    Sirikata cluster -- ssh access, corosync and puppet ports open,
    ICMP enabled, and a range of ports commonly used by Sirikata open
    to TCP (7000 - 10000).

    Note that you really only need one of these unless you want to
    customize something -- multiple clusters can use the same security
    group.

    This security group is relatively lax, opening ports to more
    sources than really necessary and opening more ports than
    necessary to cover different ports that might be used by differen
    Sirikata deployments. Ideally you'd create one customized for your
    deployment, but this is a good starting point.
    """

    group_name, group_desc = arguments.parse_or_die(create_security_group, [str, str], *args)

    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
    # We may already have a security group with this name that needs updating
    sgs = conn.get_all_security_groups()
    matches = [sg for sg in sgs if sg.name == group_name]
    sg = None
    if len(matches) == 1:
        sg = matches[0]
    else:
        sg = conn.create_security_group(group_name, group_desc)

    def ensure_rule(ip_protocol=None, from_port=None, to_port=None, cidr_ip=None, src_group=None):
        '''Makes sure a rule exists, only sending the authorize request if it isn't already present'''
        if src_group is not None:
            if not any([ ((src_group.name + '-' + src_group.owner_id) in [str(g) for g in rule.grants]) for rule in sg.rules]):
                sg.authorize(src_group=src_group)
            return

        if not any([ (rule.ip_protocol == unicode(ip_protocol) and rule.from_port == unicode(from_port) and rule.to_port == unicode(to_port) and unicode(cidr_ip) in [str(g) for g in rule.grants]) for rule in sg.rules]):
            sg.authorize(ip_protocol, from_port, to_port, cidr_ip)

    # Ping etc: ICMP all
    ensure_rule('icmp', -1, -1, '0.0.0.0/0')
    # SSH: TCP 22
    ensure_rule('tcp', 22, 22, '0.0.0.0/0')
    # Corosync: TCP + UDP 5405
    ensure_rule('tcp', 5405, 5405, '0.0.0.0/0')
    ensure_rule('udp', 5405, 5405, '0.0.0.0/0')
    # Puppet: TCP 8139
    ensure_rule('tcp', 8139, 8139, '0.0.0.0/0')
    # Sirikata: TCP 7000-10000
    ensure_rule('tcp', 7000, 10000, '0.0.0.0/0')

    # Also add the node itself as having complete access
    ensure_rule(src_group=sg)


def create(*args, **kwargs):
    """cluster create name size puppet_master keypair [--instance-type=t1.micro] [--group=security_group] [--ami=i-x7395]

    Create a new cluster. This just creates a record of the cluster
    and saves its properties, it doesn't actually allocate any nodes.
    """

    name, size, puppet_master, keypair = arguments.parse_or_die(create, [str, int, str, str], *args)

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

    name = arguments.parse_or_die(boot, [str], *args)
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
    cc.save()

    # Name the nodes
    for idx,inst in enumerate(reservation.instances):
        conn.create_tags([inst.id], {"Name": instance_name(name, idx)})

def members_address(*args, **kwargs):
    """cluster members address list cluster_name

    Get a list of members addresses. This is used to seed the list of
    members in a corosync configuration (which you'll do through
    puppet).
    """

    name = arguments.parse_or_die(members_address, [str], *args)
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
    quorum_member_section = """
                nodelist {"""
    for idx,ip in enumerate(ips):
        quorum_member_section += """
                        node {
                                ring0_addr: %s
                                nodeid: %d
                        }""" % (ip, idx)
    quorum_member_section += """
                }"""

    corosync_conf = corosync_conf.replace('{{{MEMBERS}}}', member_section)
    corosync_conf = corosync_conf.replace('{{{QUORUM_MEMBERS}}}', quorum_member_section)
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
    """cluster node ssh cluster_name index [--pem=/path/to/key.pem] [optional additional arguments give command just like with real ssh]

    Spawn an SSH process that SSHs into the node
    """

    name, idx, remote_cmd = arguments.parse_or_die(node_ssh, [str, int], rest=True, *args)
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    cc = ClusterConfigFile(name)

    if 'reservation' not in cc.state or 'instances' not in cc.state:
        print "It doesn't look like you've booted the cluster yet..."
        exit(1)

    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
    instances_info = conn.get_all_instances(instance_ids = [ cc.state['instances'][idx] ])
    # Should get back a list of one reservation with one instance in it
    instance_info = instances_info[0].instances[0]
    pub_dns_name = instance_info.public_dns_name

    cmd = ["ssh", "-i", pemfile, "ubuntu@" + pub_dns_name] + list(remote_cmd)
    subprocess.call(cmd)


def ssh(*args, **kwargs):
    """cluster ssh cluster_name [--pem=/path/to/key.pem] [required additional arguments give command just like with real ssh]

    Run an SSH command on every node in the cluster. Note that this
    currently doesn't parallelize at all, so it can be a bit
    slow. This won't do ssh sessions -- you *must* provide a command
    to execute.
    """

    name, remote_cmd = arguments.parse_or_die(ssh, [str], rest=True, *args)
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))
    if not remote_cmd:
        print "You need to add a command to execute across all the nodes."
        exit(1)

    cc = ClusterConfigFile(name)
    for inst_idx in range(len(cc.state['instances'])):
        node_ssh(name, inst_idx, *remote_cmd, pem=pemfile)


def fix_corosync(*args, **kwargs):
    """cluster fix corosync cluster_name [--pem=/path/to/key.pem]

    Fix the corosync configuration to use the set of nodes that have
    now booted up.
    """

    name = arguments.parse_or_die(fix_corosync, [str], *args)
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    # Sequence is:
    # 1. Get the updated list of nodes and generate configuration
    members_address(name)
    # 2. Update our local puppet master
    puppet.master_config('--yes')
    # 3. Restart slave puppets, making them pick up the new config and
    # restart corosync
    puppet.slaves_restart(name, pem=pemfile)
    print "Sleeping for 30 seconds to give the slave puppets a chance to recover..."
    time.sleep(30)
    # 4. Verifying good state
    print "Verifying that the cluster is in a good state. If the following command outputs messages, something is wrong..."
    node_ssh(name, 0, 'sudo', 'crm_verify', '-L', pem=pemfile)

def terminate(*args, **kwargs):
    """cluster nodes terminate name

    Terminate an existing cluster
    """

    name = arguments.parse_or_die(terminate, [str], *args)

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

    name = arguments.parse_or_die(destroy, [str], *args)

    cc = ClusterConfigFile(name)
    if 'reservation' in cc.state or 'instances' in cc.state:
        print "You have an active reservation or nodes, use 'cluster terminate nodes' before destroying this cluster spec."
        exit(1)

    cc.delete()
