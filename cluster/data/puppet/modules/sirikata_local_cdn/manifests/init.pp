class sirikata_local_cdn {
  # This just sets up a local CDN in a fixed directory that space
  # servers can place generated meshes into. This lets each server act
  # as its own CDN so a centralized CDN isn't required for upload,
  # which can be quite expensive

  # Storage space  file
  # This is on EC2 instance storage, which is temporary storage and
  # much faster, probably worth putting it here instead, but either
  # location is ok
  file { '/mnt/models':
    ensure => directory,
    owner => 'ubuntu',
    group => 'ubuntu',
  }
  file { '/home/ubuntu/models':
    ensure => symlink,
    target => '/mnt/models',
    require => File['/mnt/models']
  }

  # The server itself
  package { 'apache2':
    ensure => installed
  }
  service { 'apache2':
    ensure => running,
    enable => true,
    require => [ Package['apache2'], File['/etc/apache2/sites-available/cdn'], File['/etc/apache2/sites-enabled/cdn'] ],
    subscribe => [ File['/etc/apache2/sites-available/cdn'], File['/etc/apache2/sites-enabled/cdn'] ],
  }

  # With config for one vhost, getting rid of the ones that come with apache
  file {'/etc/apache2/sites-enabled/default' :
    ensure => absent
  }
  file {'/etc/apache2/sites-enabled/000-default' :
    ensure => absent
  }
  file {'/etc/apache2/sites-enabled/default-ssl' :
    ensure => absent
  }
  file {'/etc/apache2/sites-available/cdn':
    ensure  => file,
    require => [ Package['apache2'], File['/etc/apache2/sites-enabled/default'], File['/etc/apache2/sites-enabled/000-default'], File['/etc/apache2/sites-enabled/default-ssl'] ],
    content => template('sirikata_local_cdn/cdn-apache-vhost'),
  }
  file { '/etc/apache2/sites-enabled/cdn':
    ensure => symlink,
    target => '/etc/apache2/sites-available/cdn'
  }
}
