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

    ./sirikata-cluster.py cluster boot nodes mycluster

When you're done with the nodes, terminate them:

    ./sirikata-cluster.py cluster terminate nodes mycluster

You could revive the cluster by booting again, the cluster spec isn't
destroyed when you terminat the nodes.

Finally, you can actually destroy the cluster.

    ./sirikata-cluster.py cluster destroy mycluster

This step checks to make sure you haven't left the cluster running: it
will notify you if it looks like something is still active. If it
exits cleanly, you can be sure the cluster nodes were properly
terminated.
