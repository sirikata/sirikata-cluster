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
