class redis {

  package { 'redis-server':
    ensure => installed
  }

  file { '/etc/redis/redis.conf':
    ensure => file,
    source  => "puppet:///modules/redis/etc/redis/redis.conf",
    require => Package['redis-server'],
  }

  service { 'redis-server':
    ensure => running,
    enable => true,
    require => [ Package['redis-server'], File['/etc/redis/redis.conf'] ],
    subscribe => File['/etc/redis/redis.conf'],
  }

}
