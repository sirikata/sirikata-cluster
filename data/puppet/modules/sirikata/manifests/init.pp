class sirikata {

  include ntp

  # SIRIKATA DATA FILES AND REQUIREMENTS

  # For extracting contents of archive with binaries
  package { 'bzip2':
    ensure => installed
  }
  # For weight-sqr
  package { 'libgsl0ldbl':
    ensure => installed
  }
  # For oh-cassandra
  # FIXME does this depend on the version we built the binaries on?
  # Looks like there are 1.0.0 versions and libssl-dev at 1.0.1...
  package { 'libssl0.9.8':
    ensure => installed
  }

  #  Unfortunately, puppet is *extremely* slow about copying files
  #  through it's normal file replication mechanism when there are
  #  lots of files. So instead of replicating the files directly, we
  #  ask for a compressed archive and then extract it.
  #
  #  FIXME Even this is inefficient, it'd be even better to put it on
  #  S3, bittorrent, or something where we won't have transfer all of
  #  it from the source server.
  #
  #  We make some services depend on this so we won't, e.g., fail to
  #  run something because pacemaker started but we didn't have the
  #  Sirikata binaries yet. You need to make sure you have an
  #  installed-formatted (i.e. bin/, lib/, share/ dirs) under puppet's
  #  files/home/ubuntu/sirikata.
  file { '/home/ubuntu/sirikata.tar.bz2':
    ensure => file,
    owner => 'ubuntu',
    group => 'ubuntu',
    source  => "puppet:///modules/sirikata/home/ubuntu/sirikata.tar.bz2",
  }
  file { '/home/ubuntu/sirikata':
    ensure => directory,
    owner => 'ubuntu',
    group => 'ubuntu',
  }
  exec { 'Sirikata Binaries':
    command => 'tar -xvf ../sirikata.tar.bz2',
    cwd => '/home/ubuntu/sirikata',
    path => [ '/bin', '/usr/bin' ],
    user => 'ubuntu',
    unless => 'test -f /home/ubuntu/sirikata/bin/space', # Reasonable sanity check
    require => File['/home/ubuntu/sirikata.tar.bz2', '/home/ubuntu/sirikata'],
  }

  # COROSYNC

  package { 'corosync':
    ensure => installed,
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
    source  => "puppet:///modules/sirikata/etc/corosync/authkey",
    mode => '0400',
    owner => 'root',
    group => 'root',
  }

  file { '/usr/lib/ocf/resource.d/sirikata':
    ensure => file,
    source  => "puppet:///modules/sirikata/usr/lib/ocf/resource.d/sirikata",
    owner => 'root',
    group => 'root',
    recurse => true,
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
    require => [ Exec['enable corosync'], File['/etc/corosync/authkey'], File['/usr/lib/ocf/resource.d/sirikata'] ],
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
    hasrestart => true,
    hasstatus => true,
    require => [ Package['pacemaker'], Service['corosync'] ],
    subscribe => Service['corosync'], # Restart after corosync restarts
  }

  # STONITH settings that are there by default cause problems, disable
  # for now
  exec { 'disable stonith':
    command => "/usr/sbin/crm configure property stonith-enabled=false",
    unless => "/usr/sbin/crm_verify -L",
    require => Service['pacemaker'],
  }


  # READINESS INDICATORS These create files that let us know when
  # things are ready.
  file { '/home/ubuntu/ready' :
    ensure  => directory,
    owner => 'ubuntu',
    group => 'ubuntu',
  }
  file { '/home/ubuntu/ready/pacemaker' :
    ensure  => file,
    require => [ File['/home/ubuntu/ready'], Exec['disable stonith'] ],
    content => '',
    owner => 'ubuntu',
    group => 'ubuntu',
  }
  file { '/home/ubuntu/ready/sirikata' :
    ensure  => file,
    require => [ File['/home/ubuntu/ready'], Exec['Sirikata Binaries'] ],
    content => '',
    owner => 'ubuntu',
    group => 'ubuntu',
  }
}
