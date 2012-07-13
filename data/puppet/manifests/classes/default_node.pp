class default_node {

  # COROSYNC

  package { 'corosync':
    ensure => installed
  }

  # We need the network of the IP address to bind to, e.g. if we get
  # IP addresses like 192.168.1.100, we need 192.168.1.0
  $ip_address_network = $network_eth0

  file {'/etc/corosync/corosync.conf':
    ensure  => file,
    require => Package['corosync'],
    content => template('corosync.conf'),
  }

  file { '/etc/corosync/authkey':
    ensure => file,
    source  => "puppet:///files/etc/corosync/authkey",
    mode => '0400',
    owner => 'root',
    group => 'root',
  }

  exec { 'enable corosync':
    command => 'sed -i s/START=no/START=yes/ /etc/default/corosync',
    path => [ '/bin', '/usr/bin' ],
    unless => 'grep START=yes /etc/default/corosync',
    require => Package['corosync'],
  }

  service { 'corosync':
    ensure => running,
    enable => true,
    require => [ Exec['enable corosync'], File['/etc/corosync/authkey'] ],
    subscribe => File['/etc/corosync/corosync.conf', '/etc/corosync/authkey'],
  }

  # PACEMAKER

  package { 'pacemaker':
    ensure => installed,
    require => Package['corosync'],
  }

  service { 'pacemaker':
    ensure => running,
    enable => true,
    require => Package['pacemaker'],
  }

  # STONITH settings that are there by default cause problems, disable
  # for now
  exec { 'disable stonith':
    command => "/usr/sbin/crm configure property stonith-enabled=false",
    unless => "/usr/sbin/crm_verify -L",
    require => Service['pacemaker'],
  }
}
