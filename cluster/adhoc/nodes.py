#!/usr/bin/env python

from groupconfig import AdHocGroupConfig
import cluster.util.config as config
import cluster.util.data as data
import cluster.util.arguments as arguments
import cluster.util.sirikata as util_sirikata
import json, os, time, subprocess
import re

def name_and_config(name_or_config):
    '''Get a name and config given either a name or a config.'''
    if isinstance(name_or_config, AdHocGroupConfig):
        return (name_or_config.name, name_or_config)
    else:
        return (name_or_config, AdHocGroupConfig(name_or_config))



def create(*args, **kwargs):
    """adhoc create name user sirikata_path default_work_path default_scratch_path [list of nodes...]

    Create a new cluster. This just creates a record of the cluster and saves
    its properties. default_work_path should be a directory where services can
    be run from and they can store temporary files.
    """

    name, user, default_sirikata_path, default_work_path, default_scratch_path, nodes = arguments.parse_or_die(create, [str, str, str, str, str], rest=True, *args)

    cc = AdHocGroupConfig(name,
                          nodes=nodes,
                          username=user,
                          default_sirikata_path=default_sirikata_path,
                          default_work_path=default_work_path,
                          default_scratch_path=default_scratch_path)
    cc.save()

    return 0



def members_info_data(*args, **kwargs):
    """adhoc members info cluster_name_or_config

    Get a list of members and their properties, in json.
    """

    name_or_config = arguments.parse_or_die(members_info, [object], *args)
    name, cc = name_and_config(name_or_config)

    instances = cc.nodes
    return instances

def members_info(*args, **kwargs):
    """adhoc members info cluster_name_or_config

    Get a list of members and their properties, in json.
    """

    instances = members_info_data(*args, **kwargs)
    print json.dumps(instances, indent=4)



def node_ssh(*args, **kwargs):
    """adhoc node ssh cluster_name_or_config index_or_name_or_node [optional additional arguments give command just like with real ssh]

    Spawn an SSH process that SSHs into the node
    """

    name_or_config, idx_or_name_or_node, remote_cmd = arguments.parse_or_die(node_ssh, [object, object], rest=True, *args)

    name, cc = name_and_config(name_or_config)

    def escape(x):
        '''Escaping rules are confusing...'''
        if x.strip() == '&&' or x.strip() == '||': return x
        return re.escape(x)
    cmd = ["ssh", cc.node_ssh_address(cc.get_node(idx_or_name_or_node))] + [escape(x) for x in remote_cmd]
    return subprocess.call(cmd)


def ssh(*args, **kwargs):
    """adhoc ssh cluster_name_or_config [required additional arguments give command just like with real ssh]

    Run an SSH command on every node in the cluster. Note that this
    currently doesn't parallelize at all, so it can be a bit
    slow. This won't do ssh sessions -- you *must* provide a command
    to execute.
    """

    name_or_config, remote_cmd = arguments.parse_or_die(ssh, [object], rest=True, *args)
    if not remote_cmd:
        print "You need to add a command to execute across all the nodes."
        exit(1)

    name, cc = name_and_config(name_or_config)
    for inst_idx in range(len(cc.nodes)):
        node_ssh(cc, inst_idx, *remote_cmd)


def sync_sirikata(*args, **kwargs):
    """adhoc sync sirikata cluster_name_or_config /path/to/installed/sirikata/or/tbz2

    Synchronize Sirikata binaries by copying the specified data to this cluster's nodes.
    """

    name_or_config, path = arguments.parse_or_die(ssh, [object, str], *args)

    name, cc = name_and_config(name_or_config)

    # If they specify a directory, package it and replace the path with the package
    if os.path.isdir(path):
        retcode = util_sirikata.package(path)
        if retcode != 0: return retcode
        path = os.path.join(path, 'sirikata.tar.bz2')

    sirikata_archive_name = os.path.basename(path)
    node_archive_path = [os.path.join(cc.workspace_path(node), sirikata_archive_name) for node in cc.nodes]

    # Make a single copy onto one of the nodes
    print "Copying data to node 0"
    cmd = ['rsync', '--progress',
           path,
           cc.node_ssh_address(cc.get_node(0)) + ":" + node_archive_path[0]]
    retcode = subprocess.call(cmd)
    if retcode != 0:
        print "Failed to rsync to first node."
        print "Command was:", cmd
        return retcode

    for inst_idx in range(1, len(cc.nodes)):
        print "Copying data to node %d" % (inst_idx)
        cmd = ['rsync', '--progress',
               cc.node_ssh_address(cc.get_node(0)) + ":" + node_archive_path[0],
               cc.node_ssh_address(cc.get_node(inst_idx)) + ":" + node_archive_path[inst_idx]]
        retcode = subprocess.call(cmd)
        if retcode != 0:
            print "Failed to rsync from first node to node %d" % (inst_idx)
            print "Command was:", cmd
            return retcode

    for inst_idx,node in enumerate(cc.nodes):
        print "Extracting data on node %d" % (inst_idx)
        retcode = node_ssh(cc, inst_idx,
                           'cd', cc.sirikata_path(node=node), '&&',
                           'tar', '-xf',
                           node_archive_path[inst_idx])
        if retcode != 0:
            print "Failed to extract archive on node %d" % (inst_idx)
            return retcode

    return 0


def sync_files(*args, **kwargs):
    """adhoc sync files cluster_name_or_config idx_or_name_or_node target local_or_remote:/path local_or_remote:/path

    Synchronize files or directories between a the local host and a cluster node.
    """

    name_or_config, idx_or_name_or_node, src_path, dest_path = arguments.parse_or_die(ssh, [object, object, str, str], *args)

    name, cc = name_and_config(name_or_config)

    node_address = cc.node_ssh_address(cc.get_node(idx_or_name_or_node))

    # Get correct values out for names
    paths = [src_path, dest_path]
    paths = [p.replace('local:', '').replace('remote:', node_address + ":") for p in paths]
    src_path, dest_path = tuple(paths)

    # Make a single copy onto one of the nodes
    retcode = subprocess.call(['rsync',
                               src_path,
                               dest_path])
    return retcode

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

    target_node = cc.get_node(target_node)
    # Can now get default values that depend on the node
    if user is None: user = cc.user(target_node)
    if cwd is None: cwd = cc.default_working_path(target_node)

    service_binary = service_cmd[0]

    pidfile = os.path.join(cc.workspace_path(target_node), 'sirikata_%s.pid' % (service_name) )

    daemon_cmd = ['start-stop-daemon', '--start',
                  '--pidfile', pidfile,
                  '--user', user,
                  '--chdir', cwd,
                  # '--test'
                  ]
    if force_daemonize:
        daemon_cmd += ['--background', '--make-pidfile']
    daemon_cmd += ['--exec', service_binary,
                   '--'] + [arg.replace('PIDFILE', pidfile) for arg in service_cmd[1:]]
    retcode = node_ssh(cc, target_node,
                       *daemon_cmd)
    if retcode != 0:
        print "Failed to add cluster service"
        return retcode

    # Save a record of this service so we can find it again when we need to stop it.
    cc.state['services'][service_name] = {
        'node' : target_node['id'],
        'binary' : service_binary
        }
    cc.save()

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

    target_node = cc.get_node( cc.state['services'][service_name]['node'] )
    pidfile = os.path.join(cc.workspace_path(target_node), 'sirikata_%s.pid' % (service_name) )

    # Remove location constraint
    retcode = node_ssh(cc, target_node,
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



def destroy(*args, **kwargs):
    """adhoc destroy name_or_config

    Terminate an existing cluster
    """

    name_or_config = arguments.parse_or_die(destroy, [object], *args)

    name, cc = name_and_config(name_or_config)

    cc.delete()
