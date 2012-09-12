class sirikata($archive_url, $archive_name = 'sirikata.tar.bz2') {

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
  #  We make some services depend on this so we won't, e.g., fail to
  #  run something because pacemaker started but we didn't have the
  #  Sirikata binaries yet. You need to make sure you have an
  #  installed-formatted (i.e. bin/, lib/, share/ dirs) under puppet's
  #  files/home/ubuntu/sirikata.
  file { '/home/ubuntu/sirikata':
    ensure => directory,
    owner => 'ubuntu',
    group => 'ubuntu',
  }
  exec { 'Download Sirikata Binaries':
    command => "/usr/bin/curl -o ${archive_name} ${archive_url}${archive_name}",
    cwd => '/home/ubuntu',
    user => 'ubuntu',
    unless => "/usr/bin/test -f /home/ubuntu/${archive_name}",
  }
  exec { 'Sirikata Binaries':
    command => "tar -xf ../${archive_name}",
    cwd => '/home/ubuntu/sirikata',
    path => [ '/bin', '/usr/bin' ],
    user => 'ubuntu',
    refreshonly => true,
    subscribe => Exec['Download Sirikata Binaries'],
    require => [ Exec['Download Sirikata Binaries'], File['/home/ubuntu/sirikata'] ],
  }

  # READINESS INDICATORS These create files that let us know when
  # things are ready.
  file { '/home/ubuntu/ready' :
    ensure => directory,
    owner => 'ubuntu',
    group => 'ubuntu',
  }
  file { '/home/ubuntu/ready/sirikata' :
    ensure => file,
    require => [ File['/home/ubuntu/ready'], Exec['Sirikata Binaries'] ],
    content => '',
    owner => 'ubuntu',
    group => 'ubuntu',
  }
}
