#!/usr/bin/env python

import cluster.util.config as config
import cluster.util.data as data
import cluster.util.arguments as arguments
import cluster.util.sirikata as util_sirikata
import os, subprocess
import puppet

def sync_sirikata(*args, **kwargs):
    """ec2 sync sirikata /path/to/installed/sirikata [--puppet-path=/etc/puppet] [--notify-puppets=cluster_name_or_config]

    Package a version of Sirikata installed in the given path and set
    it up with Puppet for distribution to puppet agent nodes.

    If you already have puppets running, add
    --notify-puppets=cluster_name to trigger a puppet update (runs the
    equivalent of sirikata-cluster.py puppet slaves restart cluster_name)
    """

    installed_path = arguments.parse_or_die(package, [str], *args)
    puppet_base_path = config.kwarg_or_get('puppet-path', kwargs, 'PUPPET_PATH', default='/etc/puppet')
    notify_puppets = config.kwarg_or_default('notify-puppets', kwargs)
    # Note pemfile is different from other places since it's only required with notify-puppets.
    pemfile = config.kwarg_or_get('pem', kwargs, 'SIRIKATA_CLUSTER_PEMFILE', default=None)

    # Generate the archive if given a directory)
    gen_file = installed_path
    if os.path.isdir(installed_path):
        retcode = util_sirikata.package(installed_path)
        if retcode != 0: return retcode
        gen_file = os.path.join(installed_path, 'sirikata.tar.bz2')

    # Make sure we have a place to put the file
    dest_dir = os.path.join(puppet_base_path, 'modules', 'sirikata', 'files', 'home', 'ubuntu')
    if not os.path.exists(dest_dir):
        # Need root for this, so we have to do it through subprocess
        subprocess.call(['sudo', 'mkdir', '-p', dest_dir])

    # And copy it into place
    print "Copying archive into puppet"
    dest_file = os.path.join(dest_dir, 'sirikata.tar.bz2')
    subprocess.call(['sudo', 'cp', gen_file, dest_file])

    if notify_puppets:
        print "Notifying puppets"
        slaves_restart_kwargs = {}
        if pemfile is not None: slaves_restart_kwargs['pem'] = pemfile
        # notify_puppets == cluster name
        puppet.slaves_restart(notify_puppets, **slaves_restart_kwargs)
