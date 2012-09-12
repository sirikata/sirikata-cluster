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

You'll need to do some Puppet master node setup. First you'll want to
setup some configuration information. Currently this is just a URL
prefix for the archive of Sirikata binaries to be installed. Instead
of serving the data through Puppet (which is slow and limits you to
serving from the master) you can specify any URL the cURL will
handle. Copy cluster/data/puppet/manifests/config.example.pp to
config.pp and edit it appropriately. You should make sure you have
data uploaded there (see the section on generating Sirikata archives)
before booting up nodes.

Once you have the configuration in place, the easiest way to setup the
puppet master is to work against a local puppet master using the
default layout, in which case you can just:

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

Then put the package in place to match the URL you specified in the
Puppet configuration step so the puppet slaves can download it.

That's it. Updating a package requires deleting the old package from
the nodes (e.g. using a cluster ssh command), then restarting the
puppets so they pick up the changes:

    ./sirikata-cluster.py puppet slaves restart

Assuming you don't have any special requirements such as additional
files or unusual layout, you can use a helper command to do all this
for you:

    ./sirikata-cluster.py ec2 sirikata package /path/to/installed/sirikata

If you have two different types of clusters, you can split it into
steps:

    # Generate package
    ./sirikata-cluster.py sirikata package /path/to/installed/sirikata
    # Distribute to ec2 cluster
    ./sirikata-cluster.py ec2 sync sirikata /path/to/installed/sirikata/sirikata.tar.bz2 --notify-puppets=my-ec2-cluster
    # Distribute to ad-hoc cluster
    ./sirikata-cluster.py adhoc sync sirikata my-adhoc-cluster /path/to/installed/sirikata/sirikata.tar.bz2

Clusters
--------

This script isolates different clusters by using unique,
human-readable names for each cluster, e.g. 'myworld'. All commands
will take the cluster name as part of the command.


### EC2 Clusters

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

Or, if you are using spot instances:

    ./sirikata-cluster.py ec2 nodes request spot instances mycluster 0.01
    # Wait for request to be fulfilled
    ./sirikata-cluster.py ec2 nodes import mycluster
    # Or, to manually add instances:
    # ./sirikata-cluster.py ec2 nodes import mycluster i-4567899 i-9876544

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


### Ad-Hoc Clusters

Ad-hoc clusters are built out of a set of nodes that you specify with
properties on each, with default fall-back properties for convenience
if all your nodes are configured identically.

Creating an ad-hoc cluster can be complicated if you have variation
between nodes and just because it requires more settings to be
specified than EC2, where we can enforce a particular layout. To
create a cluster:

    ./sirikata-cluster.py adhoc create my-adhoc-cluster ewencp /home/ewencp/sirikata /home/ewencp /disk/scratch host1.example.com host2.example.com '{ "dns_name" : "host3.example.com", "username" : "bob", "sirikata_path" : "/path/to/sirikata", "default_working_path" : "/home/user", "workspace_path" : "/path/to/non/tmp/work/dir", "capabilities" : "redis" }'

The arguments are the cluster name, the default user, a directory to
sync the Sirikata binaries to, a default work directory where it's
safe to save data and temporary files to, and a path that can be used
as scratch space but which *won't* be automatically cleaned up like
/tmp. The rest of the arguments
are node specifications. The first couple use the default settings and
only need the hostname. In the future we'll be able to refer to them
just by 'host1' and 'host2'. The third node needs special setting so
we pass in a JSON string describing the node, including "capabilities"
which describe special services this node can provide.

Most commands work just like the EC2 versions. Where a node is
required, you can specify it by index, ID, or full hostname. Available
commands include listing member info, SSH to a single node, and
running an SSH command across all nodes. As described above, you'll
need to sync Sirikata before running any Sirikata services.

Finally, similar to the EC2 cluster, you can destroy the entire thing:

    ./sirikata-cluster.py adhoc destroy my-adhoc-cluster


Running Services
----------------

All types of clusters support the same interface for adding and
removing services:

    ./sirikata-cluster.py clustertype add service cluster_name_or_config service_id target_node|any [--user=default_user] [--cwd=/path/to/execute] [--] command to run --pid-file=PIDFILE

You are responsible for making sure that the command you request is a
daemon, i.e. that it will fork, disconnect from the parent, close
stdin/out, etc. If you can't guarantee that, you can use
--force-daemonize=true, but this is not reliable -- it may not catch
errors during application startup. To avoid specifying PID file paths
multiple times, the script will select the path (so it can find it
during service removal) and replace any appearance of PIDFILE in the
command arguments with that path. The example shows how the right
value could be passed to a regular Sirikata binary.

Some cluster types will accept additional keyword arguments, e.g., the
EC2 version accepts --pem=/path/to/keyfile.pem to set the SSH key to
use.

Removing a service is also simple:

    ./sirikata-cluster.py clustertype remove service cluster_name_or_config service_id


Managing Clusters Programmatically
----------------------------------

The core functionality of clusters is exposed via the NodeGroup class
(cluster/util/nodegroup.py) and it's implementations for each cluster
type. You'll probably want to create the clusters manually, but you
can then boot them, get lists of nodes, sync Sirikata binaries onto
the cluster nodes, add and remove services, and shutdown the
nodes. Once you've created the cluster configuration, using most of
these are as simple as creating a NodeGroup object specifying the name
of the cluster and calling a method, e.g.,

    import cluster, os.path
    cluster.util.config.env()
    ng = cluster.ec2.NodeGroup('mycluster')
    ng.add_service('space', 'any', [os.path.join(ng.sirikata_path(), 'bin', 'space')])

Note that in this case we use the config utility to parse environment
variables so they'll be used automatically, in this case to
automatically use a pem file when managing the EC2 nodes.
