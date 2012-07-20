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

There are also some Puppet modules included as git submodules, so do

    git submodule update --init --recursive

to make sure you have a complete checkout.

Configuration
-------------

Currently only configuration by environment variables is supported,
much like AWS scripts. A few values are required for EC2 API access:

* AWS_ACCESS_KEY_ID
* AWS_SECRET_ACCESS_KEY


Puppet Master Configuration
---------------------------

You'll need to do some Puppet master node setup. The easiest way is to
work against a local puppet master using the default layout, in which
case you can just:

    ./sirikata-cluster.py puppet master config --yes

You'll need to enter your sudo password to edit/add files under
/etc/puppet.


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

    mkdir -p /etc/puppet/modules/sirikata/files/etc/corosync
    cp /etc/corosync/authkey /etc/puppet/modules/sirikata/files/etc/corosync/


Sirikata Packaging
------------------

Sirikata needs to be packaged to run on the cluster. You should run a
make install step (ideally in Release mode and *without* any
non-server dependencies, i.e. having run make headless-depends and not
make depends). Then, tar the contents *without any prefixed
folder*. In other words, you should have bin/, lib/, and share/ as the
top level, e.g.,

    > cd installed-sirikata
    > ls
      bin/ include/ lib/ share/
    # Note that we list directories explicitly so we can skip include/
    > tar -cjvf sirikata.tar.bz2 ./bin ./lib ./share

Then place this in your puppet files directory under
home/ubuntu/sirikata.tar.bz2. On a default puppet install that will be
at /etc/puppet/modules/sirikata/files/home/ubuntu/sirikata.tar.bz2, e.g.,

    > sudo mkdir -p /etc/puppet/modules/sirikata/files/home/ubuntu
    > sudo cp sirikata.tar.bz2 /etc/puppet/modules/sirikata/files/home/ubuntu/

That's it. If you need to update this file for a running cluster, copy
a new one into place and force all the puppets on your cluster to
restart so they pick up the change:

    ./sirikata-cluster.py puppet slaves restart

Assuming you don't have any special requirements such as additional
files or unusual layout, you can use a helper command to do all this
for you:

    ./sirikata-cluster.py sirikata package /path/to/installed/sirikata


Clusters
--------

This script isolates different clusters by using unique,
human-readable names for each cluster, e.g. 'myworld'. All commands
will take the cluster name as part of the command.


First, you'll need a security group to allocate nodes under which has
the appropriate settings. You can do this manually, but a simple (but
relatively less secured) default configuration will work for a
Sirikata cluster:

    ./sirikata-cluster.py ec2 security create "sirikata-cluster" "Cluster deployment of Sirikata including Corosync/Pacemaker and Puppet"

This command is useful since there are a few extra ports these scripts
require for puppet, corosync, and pacemaker. It also opens up SSH and
a range of ports commonly used by Sirikata.

Next, you can create a cluster specification:

    ./sirikata-cluster.py ec2 create mycluster 2 ahoy.stanford.edu my_key_pair --instance-type=t1.micro --group=default --ami=ami-82fa58eb

The specification includes the name of the cluster (mycluster), number
of nodes, puppet master host, a key pair used for ssh access, the
instance type, EC2 security group and the base AMI to install on. This
step just creates a cluster specification locally -- you haven't
actually created any nodes yet.

For that, just ask for the nodes to be booted:

    ./sirikata-cluster.py ec2 nodes boot mycluster

While they're active, you can get an ssh prompt into one of the nodes:

    ./sirikata-cluster.py ec2 node ssh mycluster 1 [--pem=my_ec2_ssh_key.pem]

where the number is the node index (starting at 0) and the pem file is
the key pair file corresponding to the key pair name you specified in
the creation stage for ssh access. This is required, but marked as
optional above because you can also specify it via the environment
variable SIRIKATA_CLUSTER_PEMFILE, which is nicer since it's used by a
number of commands (sometimes indirectly where it may not be obvious
it is needed).


Unfortunately, because the version of corosync available, the nodes
can't just figure out which other nodes are available by
themselves. We need to provide each node with a list. There are a
couple of steps involved -- getting the list of addresses, updating
the puppet master config, and forcing all the nodes to re-run their
puppet configurations. Once the puppet configurations are updated,
they take care of updating corosync and restarting it. Finally, there
is one more modification which needs to be run on one of the nodes to
make the cluster usable (stonith-enabled=false). We've wrapped this
whole process into a single command (you can look at the code to see
the individual steps):

    ./sirikata-cluster.py ec2 fix corosync mycluster [--pem=my_ec2_ssh_key.pem]

(Note that this assumes a local puppet master in the default location).
At this point, you should have the nodes ready for executing pacemaker
resources (i.e. services).

When you're done with the nodes, terminate them:

    ./sirikata-cluster.py ec2 nodes terminate mycluster

You could revive the cluster by booting again, the cluster spec isn't
destroyed when you terminat the nodes.

Finally, you can actually destroy the cluster.

    ./sirikata-cluster.py ec2 destroy mycluster

This step checks to make sure you haven't left the cluster running: it
will notify you if it looks like something is still active. If it
exits cleanly, you can be sure the cluster nodes were properly
terminated.
