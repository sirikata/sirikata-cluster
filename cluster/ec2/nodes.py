#!/usr/bin/env python

from groupconfig import EC2GroupConfig
import cluster.util.config as config
import cluster.util.data as data
import cluster.util.arguments as arguments
from boto.ec2.connection import EC2Connection
import json, os, time, subprocess
import re
import random

def ssh_escape(x):
    '''Escaping rules are confusing... This escapes an argument enough to get it through ssh'''
    if x.strip() in ['&&', '||', '|', '>', '2>', '&>']: return x
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
    Sirikata cluster -- ssh access and puppet ports open,
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
    # Web (local cdn node): TCP 80
    ensure_rule('tcp', 80, 80, '0.0.0.0/0')
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
    as being pingable and containing files indicating readiness.
    A wait-timeout of 0 disables this. A pem
    file, either passed on the command line or through the environment
    is required for the timeout to work properly. Note that with
    timeouts enabled, this will check that the nodes reach a ready
    state.
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

    # Unlike spot instances, where we can easily request that any
    # availability zone be used by that all be in the same AZ, here we
    # have to specify an AZ directly. We just choose one randomly for now...
    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
    zones = conn.get_all_zones()
    zone = random.choice(zones).name

    # Now create the nodes
    reservation = conn.run_instances(cc.ami,
                                     placement=zone,
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
    # Cache some information about the instances which shouldn't
    # change. However, this can take some time to come up properly, so
    # we may need to poll a few times before we get the right info
    print "Collecting node information..."
    while True:
        new_instances = get_all_instances(cc, conn)
        if any([inst.ip_address is None or inst.dns_name is None or inst.private_ip_address is None or inst.private_dns_name is None for inst in new_instances.values()]):
            time.sleep(5)
            continue
        cc.state['instance_props'] = dict(
            [
                (inst.id, {
                        'id' : inst.id,
                        'ip' : inst.ip_address,
                        'hostname' : inst.dns_name,
                        'private_ip' : inst.private_ip_address,
                        'private_hostname' : inst.private_dns_name,
                        }) for inst in new_instances.values()])
        break
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
                                          # availability zone group
                                          # lets use specify a group
                                          # name such that we'll group
                                          # all instances together
                                          availability_zone_group=(name+'_azg'),
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
    as being pingable and containing files indicating readiness.
    A wait-timeout of 0 disables this. A pem
    file, either passed on the command line or through the environment
    is required for the timeout to work properly. Note that with
    timeouts enabled, this will check that the nodes reach a ready
    state.
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

    instances_to_add = list(instances_to_add)
    if len(instances_to_add) == 0:
        print "No instances specified, trying to use full list of account instances..."
        reservations = conn.get_all_instances()
        for res in reservations:
            instances_to_add += [inst.id for inst in res.instances if inst.state == 'running']
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

    # Cache some information about the instances which shouldn't change
    cc.state['instance_props'] = dict(
        [
            (instid, {
                    'id' : instances[instid].id,
                    'ip' : instances[instid].ip_address,
                    'hostname' : instances[instid].dns_name,
                    'private_ip' : instances[instid].private_ip_address,
                    'private_hostname' : instances[instid].private_dns_name,
                    }) for instid in instances_to_add])
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
        wait_kwargs = { 'wait-timeout' : timeout }
        if pemfile is not None: wait_kwargs['pem'] = pemfile

        return wait_nodes_ready(cc, **wait_kwargs)

    return 0

def wait_nodes_ready(*args, **kwargs):
    '''ec2 nodes wait ready name_or_config [--wait-timeout=300 --pem=/path/to/key.pem]

    Wait for nodes to finish booting and become fully ready, i.e. all
    packages to be installed have finished installing. Normally this
    will be invoked during boot or import, but can be useful if those
    run into a problem and you want to make sure all nodes have gotten
    back to a good state.
    '''

    name_or_config = arguments.parse_or_die(wait_pingable, [object], *args)
    timeout = int(config.kwarg_or_get('timeout', kwargs, 'SIRIKATA_PING_WAIT_TIMEOUT', default=300))
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    name, cc = name_and_config(name_or_config)

    print "Waiting for nodes to become pingable..."
    pingable = wait_pingable(cc, timeout=timeout)
    if pingable != 0: return pingable
    # Give a bit more time for the nodes to become ready, pinging
    # may happen before all services are finished starting
    print "Sleeping to allow nodes to finish booting"
    time.sleep(15)
    print "Waiting for initial services and Sirikata binaries to install"
    ready = wait_ready(cc, '/home/ubuntu/ready/sirikata', timeout=timeout, pem=pemfile)
    return ready


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
    can also match the node's id, private or public IP or dns name.
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
    match the node's id, private or public IP or dns name.
    '''
    inst = get_node(cc, conn, node_name).index
    return cc.state['instances'].index(inst.id)

def pacemaker_id(inst):
    if hasattr(inst, 'private_dns_name'):
        private_dns_name = inst.private_dns_name
    else:
        assert('private_dns_name' in inst or 'private_hostname' in inst)
        if 'private_hostname' in inst:
            private_dns_name = inst['private_hostname']
        else:
            private_dns_name = inst['private_dns_name']

    assert( private_dns_name.find('.') != -1 )
    return private_dns_name[:private_dns_name.find('.')]

def get_node_pacemaker_id(cc, conn, node_name):
    return pacemaker_id(get_node(cc, conn, node_name))

def get_node_hostname(cc, conn, node_name):
    return cc.hostname(node=get_node(cc, conn, node_name))

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
    indicators that initial puppet configuration has completed. You
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


def members_info_data(*args, **kwargs):
    """ec2 members info cluster_name_or_config

    Get a list of members and their properties, in json.
    """

    name_or_config = arguments.parse_or_die(members_info, [object], *args)
    name, cc = name_and_config(name_or_config)

    if 'instances' not in cc.state or 'instance_props' not in cc.state:
        print "It doesn't look like you've booted the cluster yet..."
        exit(1)

    # We provide a bit more than what we store in the file
    inst_map = dict([ (instid,cc.state['instance_props'][instid]) for instid in cc.state['instances']])
    instances = [
        {
            'id' : inst['id'],
            'ip' : inst['ip'],
            'hostname' : inst['hostname'],
            'dns_name' : inst['hostname'], # alias
            'private_ip' : inst['private_ip'],
            'private_hostname' : inst['private_hostname'],
            'private_dns_name' : inst['private_hostname'], # alias
            'pacemaker_id' : pacemaker_id(inst), # computed
            }
        for instid,inst in inst_map.iteritems()]

    return instances

def members_info(*args, **kwargs):
    """ec2 members info cluster_name_or_config

    Get a list of members and their properties, in json.
    """

    instances = members_info_data(*args, **kwargs)
    print json.dumps(instances, indent=4)


def node_ssh(*args, **kwargs):
    """ec2 node ssh cluster_name_or_config idx_or_name_or_node [--pem=/path/to/key.pem] [optional additional arguments give command just like with real ssh]

    Spawn an SSH process that SSHs into the node
    """

    name_or_config, idx_or_name_or_node, remote_cmd = arguments.parse_or_die(node_ssh, [object, object], rest=True, *args)
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    name, cc = name_and_config(name_or_config)

    if 'instances' not in cc.state:
        print "It doesn't look like you've booted the cluster yet..."
        exit(1)

    inst_info = cc.state['instance_props'][cc.get_node_name(idx_or_name_or_node)]

    # StrictHostKeyChecking no -- causes the "authenticity of host can't be
    # established" messages to not show up, and therefore not require prompting
    # the user. Not entirely safe, but much less annoying than having each node
    # require user interaction during boot phase
    cmd = ["ssh", "-o", "StrictHostKeyChecking no", "-i", pemfile, cc.user() + "@" + inst_info['hostname']] + [ssh_escape(x) for x in remote_cmd]
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

    name_or_config, idx_or_name_or_node, src_path, dest_path = arguments.parse_or_die(sync_files, [object, object, str, str], *args)
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    name, cc = name_and_config(name_or_config)

    if 'instances' not in cc.state:
        print "It doesn't look like you've booted the cluster yet..."
        exit(1)

    # Get remote info
    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
    if idx_or_name_or_node == 'all':
        instances_info = [ inst_props for instid, inst_props in cc.state['instance_props'].iteritems() ]
    else:
        instances_info = [ cc.state['instance_props'][cc.get_node_name(idx_or_name_or_node)] ]

    results = []
    for instance_info in instances_info:
        node_address = cc.user() + "@" + instance_info['hostname'] + ':'

        # Get correct values out for names
        paths = [src_path, dest_path]
        paths = [p.replace('local:', '').replace('remote:', node_address) for p in paths]
        src_path_final, dest_path_final = tuple(paths)

        # Make a single copy onto one of the nodes
        results.append( subprocess.call(["rsync", "-e", "ssh -i " + pemfile, src_path_final, dest_path_final]) )
        #results.append( subprocess.call(["scp", "-i", pemfile, src_path_final, dest_path_final]) )

    # Just pick one non-zero return value if any failed
    failed = [res for res in results if res != 0]
    if failed:
        return failed[0]
    return 0


def add_service(*args, **kwargs):
    """adhoc add service cluster_name_or_config service_id target_node|any [--user=user] [--cwd=/path/to/execute] [--] command to run

    Add a service to run on the cluster. The service needs to be
    assigned a unique id (a string) and takes the form of a command
    (which should be able to be shutdown via signals). If the command
    requires parameters of the form --setting=value, make sure you add
    -- before the command so they aren't used as arguments to this
    command. You should also be sure that the command's binary is
    specified as a full path.

    user specifies the user account that should execute the service
    cwd sets the working directory for the service

    To make handling PID files easier, any appearance of PIDFILE in
    your command arguments will be replaced with the path to the PID
    file selected. For example, you might add --pid-file=PIDFILE as an
    argument.
    """

    name_or_config, service_name, target_node, service_cmd = arguments.parse_or_die(add_service, [object, str, str], rest=True, *args)
    cname, cc = name_and_config(name_or_config)

    user = config.kwarg_or_default('user', kwargs, default=None)
    cwd = config.kwarg_or_default('cwd', kwargs, default=None)
    force_daemonize = bool(config.kwarg_or_default('force-daemonize', kwargs, default=False))

    if not len(service_cmd):
        print "You need to specify a command for the service"
        return 1

    if 'services' not in cc.state: cc.state['services'] = {}
    if service_name in cc.state['services']:
        print "The requested service already exists."
        return 1

    if not os.path.isabs(service_cmd[0]):
        print "The path to the service's binary isn't absolute (%s)" % service_cmd[0]
        print args
        print service_cmd
        return 1

    conn = EC2Connection(config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY)
    target_node_inst = get_node(cc, conn, target_node)
    target_node_pacemaker_id = get_node_pacemaker_id(cc, conn, target_node)
    target_node_hostname = get_node_hostname(cc, conn, target_node)

    # Can now get default values that depend on the node
    if user is None: user = cc.user(target_node)
    if cwd is None: cwd = cc.default_working_path(target_node)

    service_binary = service_cmd[0]

    pidfile = os.path.join(cc.workspace_path(), 'sirikata_%s.pid' % (service_name) )

    daemon_cmd = ['start-stop-daemon', '--start',
                  '--pidfile', pidfile,
                  '--user', user,
                  '--chdir', cwd,
                  # '--test'
                  ]
    if force_daemonize:
        daemon_cmd += ['--background', '--make-pidfile']
    daemon_cmd += ['--exec', service_binary,
                   '--'] + [arg.replace('PIDFILE', pidfile).replace('FQDN', target_node_hostname) for arg in service_cmd[1:]]
    retcode = node_ssh(cc, target_node_inst.id,
                       *daemon_cmd)
    if retcode != 0:
        print "Failed to add cluster service"
        return retcode

    # Save a record of this service so we can find it again when we need to stop it.
    cc.state['services'][service_name] = {
        'node' : target_node_inst.id,
        'binary' : service_binary
        }
    cc.save()

    return retcode

def service_status(*args, **kwargs):
    """adhoc service status cluster_name_or_config service_id [--pem=/path/to/pem.key]

    Check the status of a service from the cluster. Returns 0 if it is
    active and running, non-zero otherwise.
    """

    name_or_config, service_name = arguments.parse_or_die(service_status, [object, str], *args)

    cname, cc = name_and_config(name_or_config)

    if service_name not in cc.state['services']:
        print "Couldn't find record of service '%s'" % (service_name)
        return 1

    pidfile = os.path.join(cc.workspace_path(), 'sirikata_%s.pid' % (service_name) )

    # Check if the process can respond to signals, i.e. just if it is alive
    retcode = node_ssh(cc, cc.state['services'][service_name]['node'],
                       '/bin/bash', '-c',
                       "kill -0 `grep -o '[0-9]*' %s`" % (pidfile)
                       )

    return retcode



def remove_service(*args, **kwargs):
    """adhoc remove service cluster_name_or_config service_id [--pem=/path/to/pem.key]

    Remove a service from the cluster.
    """

    name_or_config, service_name = arguments.parse_or_die(remove_service, [object, str], *args)

    cname, cc = name_and_config(name_or_config)

    if service_name not in cc.state['services']:
        print "Couldn't find record of service '%s'" % (service_name)
        return 1

    pidfile = os.path.join(cc.workspace_path(), 'sirikata_%s.pid' % (service_name) )

    retcode = node_ssh(cc, cc.state['services'][service_name]['node'],
                       'start-stop-daemon', '--stop',
                       '--retry', 'TERM/6/KILL/5',
                       '--pidfile', pidfile,
                       # oknodo allows a successful return if the
                       # process couldn't actually be found, meaning
                       # it probably crashed
                       '--oknodo'
#                       '--test',
                       )

    if retcode != 0:
        print "Failed to remove service."
        return retcode

    # Destroy the record of the service.
    # Save a record of this service so we can find it again when we need to stop it.
    del cc.state['services'][service_name]
    cc.save()

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
    if 'capabilities' not in cc.state: cc.state['capabilities'] = {}
    inst = get_node(cc, conn, nodeid)
    if nodetype == 'default':
        if pacemaker_id(inst) in cc.state['node-types']:
            del cc.state['node-types'][pacemaker_id(inst)]
        if inst.id in cc.state['capabilities']:
            del cc.state['capabilities'][inst.id]
    else:
        cc.state['node-types'][pacemaker_id(inst)] = nodetype
        # Note currently only 1, the puppet setup doesn't really have composability right now anyway...
        cc.state['capabilities'][inst.id] = 'redis'
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
    if 'capabilities' in cc.state: del cc.state['capabilities']
    del cc.state['instances']
    del cc.state['instance_props']
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
