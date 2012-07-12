class default_node {
  package { 'pacemaker':
    ensure => installed
  }
  package { 'corosync':
    ensure => installed
  }
}
