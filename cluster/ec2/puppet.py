#!/usr/bin/env python

import cluster.util.config as config
import cluster.util.data as data
import cluster.util.arguments as arguments
import nodes
import os.path, subprocess, sys

# This is gross, but addresses the run-time circular dependency
# between cluster.py and puppet.py
setattr(nodes, 'puppet', sys.modules[__name__])

def generate_default_node_config():
    """Generates a default empty node configuration (all nodes as default class) if a node config doesn't exist yet."""

    if not data.exists('puppet', 'manifests', 'nodes.pp'):
        data.save('', 'puppet', 'manifests', 'nodes.pp')

def master_config(*args, **kwargs):
    """puppet master config [--path=/etc/puppet/] [--yes]

    Configure (or reconfigure) a local puppet master based on the data
    generated so far. This can be used for the initial setup of the
    Puppet master or to updated it based on changes from the cluster
    (e.g. new generated corosync files).

    The commands this executes will require sudo, but it will be
    invoked for you -- don't run this command under sudo.

    With --yes, 'yes' is assumed for all questions. Note that this
    still isn't fully automated in some cases since some subcommands
    still require user input, e.g. generating an initial auth key.
    """

    puppet_base_path = config.kwarg_or_get('path', kwargs, 'PUPPET_PATH', default='/etc/puppet')
    always_yes = bool(config.kwarg_or_get('yes', kwargs, default=False))

    # Some useful paths starting from the base path
    autosign_path = os.path.join(puppet_base_path, 'autosign.conf')
    fileserver_conf_path = os.path.join(puppet_base_path, 'fileserver.conf')
    manifests_path = os.path.join(puppet_base_path, 'manifests')
    templates_path = os.path.join(puppet_base_path, 'templates')
    files_path = os.path.join(puppet_base_path, 'files')

    # You need some mechanism of for signing new puppets. You can set
    # something up yourself, or you can take the very easy path of
    # just autosigning everything, regardless of where it's coming
    # from
    if not os.path.exists(autosign_path):
        if always_yes or config.ask_user_bool('Autosigning config not found. Create (very unsafe) autosign.conf?'):
            subprocess.call(['sudo', '/bin/bash', '-c', 'echo "*" > %s' % (autosign_path)])

    # There needs to be some access to files. Sanity check is that we
    # have at least one uncommented allow line
    existing_fileserver_conf = ''
    existing_fileserver_conf_lines = []
    if os.path.exists(fileserver_conf_path):
        with open(fileserver_conf_path, 'r') as fp: existing_fileserver_conf = fp.read()
        existing_fileserver_conf_lines = existing_fileserver_conf.split('\n')
    has_allow_line = any([line.strip().startswith('allow') for line in existing_fileserver_conf_lines])
    if not has_allow_line and  \
            (always_yes or config.ask_user_bool("You haven't allowed any access to files, should I enable access to the default location, %s?" % (files_path))):
        # If we already have a [files] section, we just want to add the line
        try:
            files_idx = [line.strip().startswith('[files]') for line in existing_fileserver_conf_lines].index(True)
            existing_fileserver_conf_lines.insert(files_idx+1, '  allow 0.0.0.0/0')
        except:
            # Otherwise we need to create the file from scratch -- just append [files] and the allow line
            existing_fileserver_conf_lines += [ '[files]', '  allow 0.0.0.0/0']
        # We need root to write the file...
        subprocess.call(['sudo', '/bin/bash', '-c', 'echo "%s" > %s' % ('\n'.join(existing_fileserver_conf_lines), fileserver_conf_path)])

    # Make sure we have a nodes configuration
    generate_default_node_config()

    # We need to add/replace data. Here we don't ask the user, we just copy all the data into place
    print "Copying data %s -> %s" % ('data/puppet/', puppet_base_path)
    subprocess.call(['sudo', '/bin/bash', '-c', 'cp -r data/puppet/* %s/' % (puppet_base_path)])

    # And restart the puppet master
    print "Restarting puppetmaster"
    subprocess.call(['sudo', 'service', 'puppetmaster', 'restart'])

def slaves_restart(*args, **kwargs):
    """puppet slaves restart cluster_name [--pem=/path/to/key.pem]

    Restart puppet on a slave node. This is useful to force it to
    reconfigure itself since Puppet doesn't seem to have a good way of
    kicking all slaves to reconfigure and re-run their settings.
    """

    name = arguments.parse_or_die(slaves_restart, [str], *args)
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    nodes.ssh(name, 'sudo', 'service', 'puppet', 'restart', pem=pemfile)


def update(*args, **kwargs):
    """puppet update cluster_name [--pem=/path/to/key.pem]

    Performs both master configuration and slave restart.
    """

    name = arguments.parse_or_die(update, [str], *args)
    pemfile = os.path.expanduser(config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE'))

    master_config('--yes')
    slaves_restart(name, pem=pemfile)
