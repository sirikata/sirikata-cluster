These are files for the puppet master node. You need to install these
into the appropriate location on your puppet master, e.g. at
/etc/puppet/manifests/, (or use the commands to allocate a puppet
master node in EC2).

To allow puppet nodes to actually use this server, puppet requires an
authentication step. You either need to set it up properly, or turn on
autosigning by doing

    echo "*" > /etc/puppet/autosign.conf
