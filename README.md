sirikata-cluster
================

A set of scripts and node configurations that help you get a cluster
of nodes running Sirikata services. It deals with allocation and basic
configuration of nodes, adding/removing services to run on the nodes,
and failing services over when nodes faile. Aside from some initial
account configuration, deploying a full cluster should be a single
command, and running each service should be just one more command
each.

Currently this is specific to EC2. The basic setup should look like
this:

* Allocate nodes we need on EC2. (Currently we're going to work with a
  fixed set of nodes because of issues with the rest of the stack,
  which newer versions resolve). Get basic node configuration through
  EC2's setup.
* Use puppet to configure the nodes. This requires a master node which
  we can run ourselves on our own machine, or run on EC2. This step
  does more than just installing the software, it also sets up a bunch
  of configuration. Using puppet is much nicer than trying to force it
  all into the EC2 initialization and allows the configuration to be
  updated after the nodes are created.
* Puppet sets up our core set of software: the Sirikata binaries
  (which we can specify the location of) and corosync+pacemaker for
  managing the cluster member set and mapping service requests to
  specific ndoes. It can also deal with failover if we want it. Note
  that this doesn't require any head node -- the only "head node" is
  the puppet master providing configuration.
* Once that's all setup, we just need to add/remove services from the
  cluster. Helper scripts are aware of the specifics of Sirikata to
  make adding services simpler.


Installation
------------

The only real dependency is Boto. This would setup the dependencies on
Ubuntu:

    sudo apt-get install python python-pip
    sudo pip install -U boto


Configuration
-------------

Currently only configuration by environment variables is supported,
much like AWS scripts. A few values are required for EC2 API access:

* AWS_ACCESS_KEY_ID
* AWS_SECRET_ACCESS_KEY


Puppet Master Configuration
---------------------------

You'll need to do some Puppet master node setup. You want to do this
and have the master ready before starting any nodes. Make sure you
have Puppet installed. Then, copy the config files into place:

    sudo cp -r data/puppet/* /etc/puppet/

Note that you may also need to adjust your /etc/puppet/fileserver.conf
to allow loading files from the agent nodes. The data is under
/etc/puppet/files and you should enable access in the [files] section,
e.g. for a complete whitelist add the line

    allow 0.0.0.0/0


Corosync One-time Configuration
-------------------------------

You'll also need to setup an authkey for corosync. All nodes need to
use the same key -- they just check it to make sure they're talking to
who they are supposed to be talking to. You need to generate the key
manually:

    sudo corosync-keygen

which will leave it in /etc/corosync/authkey. We're going to copy it
to the nodes automatically, we just need to deposit it in the right
location:

    mkdir -p /etc/puppet/files/etc/corosync
    cp /etc/corosync/authkey /etc/puppet/files/etc/corosync/



Clusters
--------

This script isolates different clusters by using unique,
human-readable names for each cluster, e.g. 'myworld'. All commands
will take the cluster name as part of the command.

You can create a cluster specification:

    ./sirikata-cluster.py cluster create mycluster 2 ahoy.stanford.edu my_key_pair --instance-type=t1.micro --group=default --ami=ami-82fa58eb

The specification includes the name of the cluster (mycluster), number
of nodes, puppet master host, a key pair used for ssh access, the
instance type, EC2 security group and the base AMI to install on. This
step just creates a cluster specification locally -- you haven't
actually created any nodes yet.

For that, just ask for the nodes to be booted:

    ./sirikata-cluster.py cluster nodes boot mycluster

While they're active, you can get an ssh prompt into one of the nodes:

    ./sirikata-cluster.py cluster nodes ssh mycluster 1 my_ec2_ssh_key.pem

where the number is the node index (starting at 0) and the pem file is
the key pair file corresponding to the key pair name you specified in
the creation stage for ssh access.


Unfortunately, because the version of corosync available, the nodes
can't just figure out which other nodes are available by
themselves. We need to provide each node with a list. After th enodes
have booted, we can do:

    ./sirikata-cluster.py cluster members address list mycluster

The output of this is an updated configuration file that Puppet needs
to distribute to the nodes. We can get it into place with:

    sudo cp data/puppet/templates/corosync.conf /etc/puppet/templates/corosync.conf

but unfortunately we have to manually log into each of the nodes and
force their puppet agents to update:

    # On each node
    sudo /etc/init.d/puppet restart

At this point, you should have the nodes ready for executing pacemaker
resources (i.e. services).

When you're done with the nodes, terminate them:

    ./sirikata-cluster.py cluster nodes terminate mycluster

You could revive the cluster by booting again, the cluster spec isn't
destroyed when you terminat the nodes.

Finally, you can actually destroy the cluster.

    ./sirikata-cluster.py cluster destroy mycluster

This step checks to make sure you haven't left the cluster running: it
will notify you if it looks like something is still active. If it
exits cleanly, you can be sure the cluster nodes were properly
terminated.
