#!/usr/bin/env python

from groupconfig import EC2GroupConfig
import cluster.util.config as config
import cluster.util.data as data
import cluster.util.arguments as arguments
from boto.ec2.connection import EC2Connection
import json, os, time, subprocess
import re

def ssh_escape(x):
    '''Escaping rules are confusing... This escapes an argument enough to get it through ssh'''
    if x.strip() == '&&' or x.strip() == '||': return x
    return re.escape(x)


def instance_name(cname, idx):
    return cname + '-' + str(idx)

def name_and_config(name_or_config):
    '''Get a name and config given either a name or a config.'''
    if isinstance(name_or_config, EC2GroupConfig):
        return (name_or_config.name, name_or_config)
    else:
        return (name_or_config, EC2GroupConfig(name_or_config))

def create_security_group(*args, **kwargs):
    """ec2 security create security_group_name security_group_description

    Create a new security group with settings reasonable for a
    Sirikata cluster -- ssh access, corosync and puppet ports open,
    ICMP enabled, and a range of ports commonly used by Sirikata open
    to TCP (6000 - 10000).

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
    # Sirikata: TCP 6000-10000
    ensure_rule('tcp', 6000, 10000, '0.0.0.0/0')
    # Redis
    ensure_rule('tcp', 6379, 6379, '0.0.0.0/0')

    # Also add the node itself as having complete access
    ensure_rule(src_group=sg)


def create(*args, **kwargs):
    """ec2 create name size puppet_master keypair [--instance-type=t1.micro] [--group=security_group] [--ami=i-x7395]

    Create a new cluster. This just creates a record of the cluster
    and saves its properties, it doesn't actually allocate any nodes.
    """

    name, size, puppet_master, keypair = arguments.parse_or_die(create, [str, int, str, str], *args)

    instance_type = config.kwarg_or_get('instance-type', kwargs, 'INSTANCE_TYPE')
    group = config.kwarg_or_get('group', kwargs, 'SECURITY_GROUP')
    ami = config.kwarg_or_get('ami', kwargs, 'BASE_AMI')

    cc = EC2GroupConfig(name,
                           size=size, keypair=keypair,
                           instance_type=instance_type,
                           group=group, ami=ami,
                           puppet_master=puppet_master)
    cc.save()

    # Make sure we have a nodes config for puppet. Not needed here,
    # but it's a convenient place to make sure we have it done since
    # nothing else with the cluster can happen until this is called
    puppet.generate_default_node_config()

    return 0

def boot(*args, **kwargs):
    """ec2 nodes boot name_or_config [--wait-timeout=300 --pem=/path/to/key.pem]

    Boot a cluster's nodes. The command will block for wait-timeout
    seconds, or until all nodes reach a ready state (currently defined
    as being pingable and containing two files indicating readiness of
    Sirikata and Pacemaker). A wait-timeout of 0 disables this. A pem
    file, either passed on the command line or through the environment
    is required for the timeout to work properly. Note that with
    timeouts enabled, this will run 'cluster fix corosync' as well as
    that is required for the nodes to reach a ready state.
    """

    name_or_config = arguments.parse_or_die(boot, [object], *args)
    timeout = config.kwarg_or_default('wait-timeout', kwargs, default=600)
    # Note pemfile is different from other places since it's only required with wait-timeout.
    pemfile = config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE', default=None)
    name, cc = name_and_config(name_or_config)

    if 'reservation' in cc.state or 'spot' in cc.state or 'instances' in cc.state:
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

    return name_and_boot_nodes(cc, conn, pemfile, timeout)

def request_spot_instances(*args, **kwargs):
    """ec2 nodes request spot instances name_or_config price

    Request spot instances to be used in this cluster. Unlike boot,
    this doesn't block because we can't be sure the nodes will
    actually be booted immediately. You should use this in conjunction
    with the import nodes command once the nodes have booted, which
    will complete the setup. The main benefit of using this instead of
    allocating the nodes manually is that all the configuration is
    setup properly, including, importantly, the initial script which
    performs the bootstrapping configuration.
    """

    name_or_config, price = arguments.parse_or_die(request_spot_instances, [object, str], *args)
    name, cc = name_and_config(name_or_config)

    if 'reservation' in cc.state or 'spot' in cc.state or 'instances' in cc.state:
        print "It looks like you already have active nodes for this cluster..."
        exit(1)

    # Load the setup script template, replace puppet master info
    user_data = data.load('ec2-user-data', 'node-setup.sh')
    user_data = user_data.replace('{{{PUPPET_MASTER}}}', cc.puppet_master)

    # Now create the nodes
    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
    request = conn.request_spot_instances(price, cc.ami,
                                          # launch group is just a
                                          # name that causes these to
                                          # only launch if all can be
                                          # satisfied
                                          launch_group=name,
                                          count=cc.size,
                                          key_name=cc.keypair,
                                          instance_type=cc.instance_type,
                                          security_groups=[cc.group],
                                          user_data=user_data
                                          )

    # Indicate that we've done a spot request so we don't try to double-allocate nodes.
    cc.state['spot'] = True
    cc.save()

    print "Requested %d spot instances" % cc.size
    return 0

def import_nodes(*args, **kwargs):
    """ec2 nodes import name_or_config instance1_id instance2_id ... [--wait-timeout=300 --pem=/path/to/key.pem]

    Import instances from a spot reservation and then perform the boot sequence on them.
    The command will block for wait-timeout
    seconds, or until all nodes reach a ready state (currently defined
    as being pingable and containing two files indicating readiness of
    Sirikata and Pacemaker). A wait-timeout of 0 disables this. A pem
    file, either passed on the command line or through the environment
    is required for the timeout to work properly. Note that with
    timeouts enabled, this will run 'cluster fix corosync' as well as
    that is required for the nodes to reach a ready state.
    """

    name_or_config, instances_to_add = arguments.parse_or_die(import_nodes, [object], rest=True, *args)
    timeout = config.kwarg_or_default('wait-timeout', kwargs, default=600)
    # Note pemfile is different from other places since it's only required with wait-timeout.
    pemfile = config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE', default=None)
    name, cc = name_and_config(name_or_config)

    if 'spot' not in cc.state:
        print "It looks like this cluster hasn't made a spot reservation..."
        return 1

    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)

    if len(instances_to_add) == 0:
        print "No instances specified, trying to use full list of account instances..."
        reservations = conn.get_all_instances()
        for res in reservations:
            instances_to_add += list(res.instances)
    if len(instances_to_add) != cc.size:
        print "Number of instances doesn't match the cluster size. Make sure you explicitly specify %d instances" % (cc.size)
        return 1

    cc.state['instances'] = instances_to_add

    # Verify the instances are valid, just checking that we get valid
    # objects back when we look them up with AWS
    print "Verifying instances are valid..."
    instances = get_all_instances(cc, conn);
    if len(instances) != len(instances_to_add):
        print "Only got %d instances back, you'll need to manually clean things up..." % len(instances)
        return 1

    cc.save()

    return name_and_boot_nodes(cc, conn, pemfile, timeout)

def name_and_boot_nodes(cc, conn, pemfile, timeout):
    '''After instances have been allocated to the cluster (by booting
    them directly or importing the instance IDs), this names them and
    runs the boot sequence to get them configured.
    '''

    # Name the nodes
    for idx,inst_id in enumerate(cc.state['instances']):
        conn.create_tags([inst_id], {"Name": instance_name(cc.name, idx)})

    if timeout > 0:
        pem_kwargs = {}
        if pemfile is not None: pem_kwargs['pem'] = pemfile

        print "Waiting for nodes to become pingable..."
        pingable = wait_pingable(cc, timeout=timeout)
        if pingable != 0: return pingable
        # Give a bit more time for the nodes to become ready, pinging
        # may happen before all services are finished starting
        print "Sleeping to allow nodes to finish booting"
        time.sleep(15)
        print "Waiting for initial services and Sirikata binaries to install"
        wait_ready(cc, '/home/ubuntu/ready/corosync-service', '/home/ubuntu/ready/sirikata', timeout=timeout, **pem_kwargs)
        print "Fixing corosync configuration..."
        fix_corosync(cc, **pem_kwargs)

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
    assert( inst.private_dns_name.find('.') != -1 )
    return inst.private_dns_name[:inst.private_dns_name.find('.')]

def get_node_pacemaker_id(cc, conn, node_name):
    return pacemaker_id(get_node(cc, conn, node_name))

def wait_pingable(*args, **kwargs):
    '''Wait for nodes to become pingable, with an optional timeout.'''

    name_or_config = arguments.parse_or_die(wait_pingable, [object], *args)
    timeout = int(config.kwarg_or_get('timeout', kwargs, 'SIRIKATA_PING_WAIT_TIMEOUT', default=0))

    name, cc = name_and_config(name_or_config)

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

    name_or_config, files_to_check = arguments.parse_or_die(wait_ready, [object], rest=True, *args)
    timeout = int(config.kwarg_or_get('timeout', kwargs, 'SIRIKATA_READY_WAIT_TIMEOUT', default=0))
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    name, cc = name_and_config(name_or_config)

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
        remote_cmd = []
        for file_to_check in files_to_check:
            if remote_cmd: remote_cmd.append('&&')
            remote_cmd += ['test', '-f', file_to_check]
        retcode = node_ssh(cc, node_idx, *remote_cmd, pem=pemfile)
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
    """ec2 members address list cluster_name_or_config

    Get a list of members addresses. This is used to seed the list of
    members in a corosync configuration (which you'll do through
    puppet).
    """

    name_or_config = arguments.parse_or_die(members_address, [object], *args)
    name, cc = name_and_config(name_or_config)

    if 'instances' not in cc.state:
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
    data.save(corosync_conf, 'puppet', 'modules', 'sirikata', 'templates', 'corosync.conf')

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


def members_info_data(*args, **kwargs):
    """ec2 members info cluster_name_or_config

    Get a list of members and their properties, in json.
    """

    name_or_config = arguments.parse_or_die(members_info, [object], *args)
    name, cc = name_and_config(name_or_config)

    if 'instances' not in cc.state:
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

    return instances

def members_info(*args, **kwargs):
    """ec2 members info cluster_name_or_config

    Get a list of members and their properties, in json.
    """

    instances = members_info_data(*args, **kwargs)
    print json.dumps(instances, indent=4)


def node_ssh(*args, **kwargs):
    """ec2 node ssh cluster_name_or_config index [--pem=/path/to/key.pem] [optional additional arguments give command just like with real ssh]

    Spawn an SSH process that SSHs into the node
    """

    name_or_config, idx, remote_cmd = arguments.parse_or_die(node_ssh, [object, int], rest=True, *args)
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    name, cc = name_and_config(name_or_config)

    if 'instances' not in cc.state:
        print "It doesn't look like you've booted the cluster yet..."
        exit(1)

    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
    instances_info = conn.get_all_instances(instance_ids = [ cc.state['instances'][idx] ])
    # Should get back a list of one reservation with one instance in it
    instance_info = instances_info[0].instances[0]
    pub_dns_name = instance_info.public_dns_name

    cmd = ["ssh", "-i", pemfile, "ubuntu@" + pub_dns_name] + [ssh_escape(x) for x in remote_cmd]
    return subprocess.call(cmd)


def ssh(*args, **kwargs):
    """ec2 ssh cluster_name_or_config [--pem=/path/to/key.pem] [required additional arguments give command just like with real ssh]

    Run an SSH command on every node in the cluster. Note that this
    currently doesn't parallelize at all, so it can be a bit
    slow. This won't do ssh sessions -- you *must* provide a command
    to execute.
    """

    name_or_config, remote_cmd = arguments.parse_or_die(ssh, [object], rest=True, *args)
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))
    if not remote_cmd:
        print "You need to add a command to execute across all the nodes."
        exit(1)

    name, cc = name_and_config(name_or_config)
    for inst_idx in range(len(cc.state['instances'])):
        node_ssh(cc, inst_idx, *remote_cmd, pem=pemfile)


def sync_files(*args, **kwargs):
    """adhoc sync files cluster_name_or_config idx_or_name_or_node target local_or_remote:/path local_or_remote:/path [--pem=/path/to/key.pem]

    Synchronize files or directories between a the local host and a cluster node.
    """

    name_or_config, idx_or_name_or_node, src_path, dest_path = arguments.parse_or_die(ssh, [object, object, str, str], *args)
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    name, cc = name_and_config(name_or_config)

    if 'instances' not in cc.state:
        print "It doesn't look like you've booted the cluster yet..."
        exit(1)

    # Get remote info
    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
    instances_info = conn.get_all_instances(instance_ids = [ cc.get_node_name(idx_or_name_or_node) ])
    # Should get back a list of one reservation with one instance in it
    instance_info = instances_info[0].instances[0]
    pub_dns_name = instance_info.public_dns_name
    node_address = "ubuntu@" + pub_dns_name + ":"

    # Get correct values out for names
    paths = [src_path, dest_path]
    paths = [p.replace('local:', '').replace('remote:', node_address) for p in paths]
    src_path, dest_path = tuple(paths)

    # Make a single copy onto one of the nodes
    return subprocess.call(["rsync", "-e", "ssh -i " + pemfile, src_path, dest_path])


def fix_corosync(*args, **kwargs):
    """ec2 fix corosync cluster_name_or_config [--pem=/path/to/key.pem]

    Fix the corosync configuration to use the set of nodes that have
    now booted up.
    """

    name_or_config = arguments.parse_or_die(fix_corosync, [object], *args)
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    # Sequence is:
    # 1. Get the updated list of nodes and generate configuration
    members_address(name_or_config)
    # 2. Update our local puppet master
    puppet.master_config('--yes')
    # 3. Touch the indicator file so the puppets know they can proceed with starting corosync
    ssh(name_or_config, 'touch', '/home/ubuntu/ready/corosync-configured', pem=pemfile)
    # 3. Restart slave puppets, making them pick up the new config and
    # restart corosync
    puppet.slaves_restart(name_or_config, pem=pemfile)

    print "Waiting for nodes to become ready with pacemaker..."
    cname, cc = name_and_config(name_or_config)
    pem_kwargs = {}
    if pemfile is not None: pem_kwargs['pem'] = pemfile
    wait_ready(cc, '/home/ubuntu/ready/pacemaker', timeout=300, **pem_kwargs)

    # 4. Verifying good state
    print "Verifying that the cluster is in a good state. If the following command outputs messages, something is wrong..."
    node_ssh(name_or_config, 0, 'sudo', 'crm_verify', '-L', pem=pemfile)


def status(*args, **kwargs):
    """ec2 status cluster_name [--pem=/path/to/key.pem]

    Give status of the cluster. This just runs crm_mon -1 on one of the cluster nodes.
    """

    name_or_config = arguments.parse_or_die(status, [object], *args)
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    return node_ssh(name_or_config, 0, 'sudo', 'crm_mon', '-1', pem=pemfile)



def add_service(*args, **kwargs):
    """ec2 add service cluster_name_or_config service_id target_node|any [--pem=/path/to/pem.key] [--user=ubuntu] [--cwd=/path/to/execute] [--] command to run

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

    name_or_config, service_name, target_node, service_cmd = arguments.parse_or_die(add_service, [object, str, str], rest=True, *args)
    user = config.kwarg_or_default('user', kwargs, default='ubuntu')
    cwd = config.kwarg_or_default('cwd', kwargs, default='/home/ubuntu')
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    if not len(service_cmd):
        print "You need to specify a command for the service"
        return 1
    if not os.path.isabs(service_cmd[0]):
        print "The path to the service's binary isn't absolute (%s)" % service_cmd[0]
        print args
        print service_cmd
        return 1

    cname, cc = name_and_config(name_or_config)
    if target_node != 'any':
        conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
        target_node_pacemaker_id = get_node_pacemaker_id(cc, conn, target_node)

    # Make sure this cluster is in "opt in" mode, i.e. that services
    # won't be run anywhere, only where we say it's ok to
    # (i.e. default rule is -INF score)
    retcode = node_ssh(cc, 0, 'sudo', 'crm_attribute', '--attr-name', 'symmetric-cluster', '--attr-value', 'false')
    if retcode != 0:
        print "Couldn't set cluster to opt-in mode."
        return retcode

    # Clean up arguments
    # node=None because we only have generic versions and don't have a real node object to pass in
    pidfile = os.path.join(cc.workspace_path(node=None), 'sirikata_%s.pid' % (service_name) )
    service_cmd = [ssh_escape(arg.replace('PIDFILE', pidfile)) for arg in service_cmd]
    service_binary = service_cmd[0]
    # Args need to go into a single quoted string parameter
    service_args = ' '.join(service_cmd[1:])

    retcode = node_ssh(cc, 0,
                       'sudo', 'crm', 'configure', 'primitive',
                       service_name, 'ocf:sirikata:anything',
                       'params',
                       'create_pidfile=no',
                       'pidfile=' + pidfile,
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
        retcode = node_ssh(cc, 0,
                           'sudo', 'crm', 'configure', 'location',
                           service_name + '-location', service_name,
                           'rule', '50:', 'defined', '\#uname' # should be defined everywhere
                           )
    else: # force to a particular node
        retcode = node_ssh(cc, 0,
                           'sudo', 'crm', 'configure', 'location',
                           service_name + '-location', service_name,
                           '100:', target_node_pacemaker_id # value is arbitrary != -INF
                           )

    return retcode

def remove_service(*args, **kwargs):
    """ec2 remove service cluster_name_or_config service_id [--pem=/path/to/pem.key]

    Remove a service from the cluster.
    """

    name_or_config, service_name = arguments.parse_or_die(remove_service, [object, str], *args)
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    cname, cc = name_and_config(name_or_config)

    # Stop the service first
    retcode = node_ssh(cc, 0,
                       'sudo', 'crm', 'resource',
                       'stop', service_name
                       )

    if retcode != 0:
        print "Failed to stop process, but still trying to remove the service..."

    # Remove location constraint
    retcode = node_ssh(cc, 0,
                       'sudo', 'crm', 'configure',
                       'delete', service_name + '-location'
                       )
    if retcode != 0:
        print "Failed to remove location constraint, but still trying to remove the service..."

    # Need to give it some time to shut down the process
    time.sleep(6)

    retcode = node_ssh(cc, 0,
                       'sudo', 'crm', 'configure',
                       'delete', service_name
                       )
    if retcode != 0:
        print "Failed to remove service."
    return retcode


def set_node_type(*args, **kwargs):
    """ec2 node set type cluster_name_or_config node nodetype [--pem=/path/to/pem.key]

    Set the given node (by index, hostname, IP, etc) to be of the
    specified node type in Puppet, e.g. setting sirikata_redis to make
    it a Redis server. Setting to 'default' reverts to the original config.
    """

    name_or_config, nodeid, nodetype = arguments.parse_or_die(set_node_type, [object, str, str], *args)
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    # Explicit check for known types so we don't get our config into a bad state
    if nodetype not in ['default', 'sirikata_redis']:
        print "The specified node type (%s) isn't known." % (nodetype)
        return 1

    name, cc = name_and_config(name_or_config)
    if 'instances' not in cc.state:
        print "No active instances were found, are you sure this cluster is currently running?"
        exit(1)

    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)

    # Update entry in local storage so we can update later
    if 'node-types' not in cc.state: cc.state['node-types'] = {}
    inst = get_node(cc, conn, nodeid)
    if nodetype == 'default':
        if pacemaker_id(inst) in cc.state['node-types']:
            del cc.state['node-types'][pacemaker_id(inst)]
    else:
        cc.state['node-types'][pacemaker_id(inst)] = nodetype
    cc.save()

    # Generate config
    node_config = ''.join(["node '%s' inherits %s {}" % (pacemakerid,nt) for pacemakerid,nt in cc.state['node-types'].iteritems()])
    data.save(node_config, 'puppet', 'manifests', 'nodes.pp')

    pem_kwargs = {}
    if pemfile is not None: pem_kwargs['pem'] = pemfile
    return puppet.update(cc, **pem_kwargs)


def terminate(*args, **kwargs):
    """ec2 nodes terminate name_or_config

    Terminate an existing cluster
    """

    name_or_config = arguments.parse_or_die(terminate, [object], *args)

    name, cc = name_and_config(name_or_config)
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

    if 'node-types' in cc.state: del cc.state['node-types']
    del cc.state['instances']
    if 'reservation' in cc.state:
        del cc.state['reservation']
    if 'spot' in cc.state:
        del cc.state['spot']

    cc.save()

def destroy(*args, **kwargs):
    """ec2 destroy name_or_config

    Terminate an existing cluster
    """

    name_or_config = arguments.parse_or_die(destroy, [object], *args)

    name, cc = name_and_config(name_or_config)

    if 'reservation' in cc.state or 'spot' in cc.state or 'instances' in cc.state:
        print "You have an active reservation or nodes, use 'cluster terminate nodes' before destroying this cluster spec."
        exit(1)

    cc.delete()
