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
    """cluster nodes boot name target_node [--wait-timeout=300 --pem=/path/to/key.pem]

    Boot a cluster's nodes. The command will block for wait-timeout
    seconds, or until all nodes reach a ready state (currently defined
    as being pingable and containing two files indicating readiness of
    Sirikata and Pacemaker). A wait-timeout of 0 disables this. A pem
    file, either passed on the command line or through the environment
    is required for the timeout to work properly. Note that with
    timeouts enabled, this will run 'cluster fix corosync' as well as
    that is required for the nodes to reach a ready state.
    """

    name, target_node = arguments.parse_or_die(boot, [str, str], *args)
    timeout = config.kwarg_or_default('wait-timeout', kwargs, default=300)
    # Note pemfile is different from other places since it's only required with wait-timeout.
    pemfile = config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE', default=None)
    cc = ClusterConfigFile(name)

    if 'reservation' in cc.state or 'instances' in cc.state:
        print "It looks like you already have active nodes for this cluster..."
        exit(1)

    if timeout > 0 and not pemfile:
        print "You need to specify a pem file to use timeouts."
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

    if timeout > 0:
        print "Waiting for nodes to become pingable..."
        pingable = wait_pingable(name, timeout=timeout)
        if pingable != 0: return pingable
        # Give a bit more time for the nodes to become ready, pinging
        # may happen before all services are finished starting
        print "Sleeping to allow nodes to finish booting"
        time.sleep(15)
        print "Fixing corosync..."
        pem_kwargs = {}
        if pemfile is not None: pem_kwargs['pem'] = pemfile
        fix_corosync(name, **pem_kwargs)
        print "Waiting for nodes to become ready..."
        return wait_ready(name, timeout=timeout, **pem_kwargs)

    return 0


def get_all_instances(cc, conn):
    '''Get instance info for all nodes as a dict of instance id -> instance info'''
    reservations = conn.get_all_instances(instance_ids = cc.state['instances'])
    # This could return a bunch of reservations, each with instances in them
    instances = []
    for res in reservations:
        instances += list(res.instances)
    return dict([(inst.id, inst) for inst in instances])

def get_all_ips(cc, conn):
    '''Returns a dict of instance id -> IP address. Note that the IP
    address can be None if the node hasn't finished booting/being
    configured'''
    instances = get_all_instances(cc, conn)
    return dict([(inst.id, inst.ip_address) for inst in instances.values()])

def get_node(cc, conn, node_name):
    '''Returns a node's instance info based on any of a number of
    'names'. A pure number will be used directly as an index. The name
    can also match the node's id, private or public IP or dns name, or
    it's pacemaker ID (which is based on the internal IP).
    '''

    instances = get_all_instances(cc, conn)
    try:
        idx = int(node_name)
        return instances[cc.state['instances'][idx]]
    except:
        pass
    for inst in instances.values():
        if inst.private_dns_name.startswith(node_name) or \
                node_name == inst.ip_address or \
                node_name == inst.private_ip_address or \
                node_name == inst.dns_name or \
                node_name == inst.id:
            return inst
    raise Exception("Couldn't find node '" + node_name + "'")

def get_node_index(cc, conn, node_name):
    '''Returns a node index based on any of a number of 'names'. A
    pure number will be used directly as an index. The name can also
    match the node's id, private or public IP or dns name, or it's
    pacemaker ID (which is based on the internal IP).
    '''
    inst = get_node(cc, conn, node_name).index
    return cc.state['instances'].index(inst.id)

def pacemaker_id(inst):
    assert( inst.private_dns_name.endswith('compute-1.internal') )
    return inst.private_dns_name.replace('.compute-1.internal', '')

def get_node_pacemaker_id(cc, conn, node_name):
    return pacemaker_id(get_node(cc, conn, node_name))

def wait_pingable(*args, **kwargs):
    '''Wait for nodes to become pingable, with an optional timeout.'''

    name = arguments.parse_or_die(wait_pingable, [str], *args)
    timeout = int(config.kwarg_or_get('timeout', kwargs, 'SIRIKATA_PING_WAIT_TIMEOUT', default=0))

    cc = ClusterConfigFile(name)

    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
    # We need to loop until we can get IPs for all nodes
    waited = 0
    while (timeout == 0 or waited < timeout):
        instances_ips = get_all_ips(cc, conn)
        not_pinged = set(instances_ips.keys())

        # If none are missing IPs, we can exit
        if not any([ip is None for ip in instances_ips.values()]):
            break
        # Otherwise sleep awhile and then try again
        time.sleep(10)

    # Just loop, waiting on any (i.e. the first) node in the set, reset our timeout
    waited = 0
    while not_pinged and (timeout == 0 or waited < timeout):
        node_id = next(iter(not_pinged))
        ip = instances_ips[node_id]
        print 'Waiting on %s (%s)' % (node_id, str(ip))
        # One of those rare instances we just want to dump the output
        retcode = 0
        with open('/dev/null', 'w') as devnull:
            retcode = subprocess.call(['ping', '-c', '2', str(ip)], stdout=devnull, stderr=devnull)
        if retcode == 0: # ping success
            not_pinged.remove(node_id)
            continue
        time.sleep(5)
        waited += 5

    if not_pinged:
        print "Failed to ping %s" % (next(iter(not_pinged)))
        exit(1)
    print "Success"
    return 0

def wait_ready(*args, **kwargs):
    '''Wait for nodes to become ready, with an optional timeout. Ready
    means that puppet has finished configuring packages and left
    indicators that both Sirikata and Pacemaker are available. You
    should make sure all nodes are pingable before running this.'''

    name = arguments.parse_or_die(wait_ready, [str], *args)
    timeout = int(config.kwarg_or_get('timeout', kwargs, 'SIRIKATA_READY_WAIT_TIMEOUT', default=0))
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    cc = ClusterConfigFile(name)

    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)

    instances_ips = get_all_ips(cc, conn)
    not_ready = set(instances_ips.keys())

    # Just loop, waiting on any (i.e. the first) node in the set, reset our timeout
    waited = 0
    while not_ready and (timeout == 0 or waited < timeout):
        node_id = next(iter(not_ready))
        ip = instances_ips[node_id]
        print 'Waiting on %s (%s)' % (node_id, str(ip))
        node_idx = cc.state['instances'].index(node_id)
        remote_cmd = ['test', '-f', '/home/ubuntu/ready/pacemaker', '&&', 'test', '-f', '/home/ubuntu/ready/sirikata']
        retcode = node_ssh(name, node_idx, *remote_cmd, pem=pemfile)
        if retcode == 0: # command success
            not_ready.remove(node_id)
            continue
        time.sleep(5)
        waited += 5

    if not_ready:
        print "Failed to find readiness indicators for %s" % (next(iter(not_ready)))
        exit(1)
    print "Success"
    return 0



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
    ips = get_all_ips(cc, conn).values()

    corosync_conf = data.load('corosync', 'corosync.conf.template')
    # Cluster members
    member_section = ""
    for ip in ips:
        member_section += """
                member {
                        memberaddr: %s
                }""" % (ip)
    # Quorum members
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


def members_info(*args, **kwargs):
    """cluster members info cluster_name

    Get a list of members and their properties, in json.
    """

    name = arguments.parse_or_die(members_info, [str], *args)
    cc = ClusterConfigFile(name)

    if 'reservation' not in cc.state or 'instances' not in cc.state:
        print "It doesn't look like you've booted the cluster yet..."
        exit(1)

    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
    instances = get_all_instances(cc, conn)

    instances = [
        {
            'id' : inst.id,
            'pacemaker_id' : pacemaker_id(inst),

            'ip' : inst.ip_address,
            'dns_name' : inst.dns_name,
            'private_ip' : inst.private_ip_address,
            'private_dns_name' : inst.private_dns_name,

            'state' : inst.state,
            'instance_type' : inst.instance_type,
            }
        for instid, inst in instances.iteritems()]

    print json.dumps(instances, indent=4)


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
    return subprocess.call(cmd)


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


def status(*args, **kwargs):
    """cluster status cluster_name [--pem=/path/to/key.pem]

    Give status of the cluster. This just runs crm_mon -1 on one of the cluster nodes.
    """

    name = arguments.parse_or_die(status, [str], *args)
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    return node_ssh(name, 0, 'sudo', 'crm_mon', '-1', pem=pemfile)



def add_service(*args, **kwargs):
    """cluster add service cluster_name service_id target_node|any [--pem=/path/to/pem.key] [--user=ubuntu] [--cwd=/path/to/execute] [--] command to run

    Add a service to run on the cluster. The service needs to be
    assigned a unique id (a string) and takes the form of a command
    (which should be able to be shutdown via signals). If the command
    requires parameters of the form --setting=value, make sure you add
    -- before the command so they aren't used as arguments to this
    command. You should also be sure that the command's binary is
    specified as a full path.

    user specifies the user account that should execute the service
    cwd sets the working directory for the service
    """

    cname, service_name, target_node, service_cmd = arguments.parse_or_die(add_service, [str, str, str], rest=True, *args)
    user = config.kwarg_or_default('user', kwargs, default='ubuntu')
    cwd = config.kwarg_or_default('cwd', kwargs, default='/home/ubuntu')
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    if not len(service_cmd):
        print "You need to specify a command for the service"
        exit(1)
    if not os.path.isabs(service_cmd[0]):
        print "The path to the service's binary isn't absolute."
        exit(1)

    if target_node != 'any':
        cc = ClusterConfigFile(cname)
        conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
        target_node_pacemaker_id = get_node_pacemaker_id(cc, conn, target_node)

    # Make sure this cluster is in "opt in" mode, i.e. that services
    # won't be run anywhere, only where we say it's ok to
    # (i.e. default rule is -INF score)
    retcode = node_ssh(cname, 0, 'sudo', 'crm_attribute', '--attr-name', 'symmetric-cluster', '--attr-value', 'false')
    if retcode != 0:
        print "Couldn't set cluster to opt-in mode."
        return retcode

    service_binary = service_cmd[0]
    # Args need to go into a single quoted string parameter, they need
    # quotes escaped.
    # FIXME this doesn't properly handle already escaped quotes...
    service_args = (' '.join(service_cmd[1:])).replace('"', '\"')

    retcode = node_ssh(cname, 0,
                       'sudo', 'crm', 'configure', 'primitive',
                       service_name, 'ocf:sirikata:anything',
                       'params',
                       'binfile=' + service_binary,
                       'user=' + user,
                       'cwd=' + cwd,
                       'cmdline_options="' + service_args + '"',
                       )
    if retcode != 0:
        print "Failed to add cluster service"
        return retcode

    # Add a location constraint. Nothing gets instantiated until here
    # because we're set in opt-in mode. Without the location
    # constraint, everything gets -INF score.
    if target_node == 'any': # allow it to run on any node
        retcode = node_ssh(cname, 0,
                           'sudo', 'crm', 'configure', 'location',
                           service_name + '-location', service_name,
                           'rule', '50:', 'defined', '\#uname' # should be defined everywhere
                           )
    else: # force to a particular node
        retcode = node_ssh(cname, 0,
                           'sudo', 'crm', 'configure', 'location',
                           service_name + '-location', service_name,
                           '100:', target_node_pacemaker_id # value is arbitrary != -INF
                           )

    return retcode

def remove_service(*args, **kwargs):
    """cluster remove service cluster_name service_id [--pem=/path/to/pem.key]

    Remove a service from the cluster.
    """

    cname, service_name = arguments.parse_or_die(remove_service, [str, str], *args)
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    # Remove location constraint
    retcode = node_ssh(cname, 0,
                       'sudo', 'crm', 'configure',
                       'delete', service_name + '-location'
                       )
    if retcode != 0:
        print "Failed to remove location constraint, but still trying to remove the service..."

    # Need to give it some time to shut down the process
    time.sleep(6)

    retcode = node_ssh(cname, 0,
                       'sudo', 'crm', 'configure',
                       'delete', service_name
                       )
    if retcode != 0:
        print "Failed to remove service."
    return retcode


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
