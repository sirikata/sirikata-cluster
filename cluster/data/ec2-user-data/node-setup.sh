#!/bin/bash

# Exit immediately on error and print commands as they  run
set -e -x

# Needed so that the aptitude/apt-get operations will not be interactive
export DEBIAN_FRONTEND=noninteractive

# Make sure we're up to date on packages
apt-get update && apt-get -y upgrade

aptitude -y install puppet

# Forcing puppet to resolve to the IP of the master has a couple of
# issues -- it's not reliable if the master changes IP and also can
# cause problems if the cert used by the puppet master isn't signed
# with the right names -- it'll complain about something like
#   Could not send report: Server hostname 'puppet' did not match
#   server certificate; expected foo.example.com
# Instead, insert the puppet master host name as part of the puppet
# config.
echo "[main]" > /etc/puppet/puppet.conf.new
echo "server={{{PUPPET_MASTER}}}" >> /etc/puppet/puppet.conf.new
cat /etc/puppet/puppet.conf  | egrep -v "\[main\]" >> /etc/puppet/puppet.conf.new
mv /etc/puppet/puppet.conf.new /etc/puppet/puppet.conf

# Enable the puppet client
sed -i /etc/default/puppet -e 's/START=no/START=yes/'

service puppet restart