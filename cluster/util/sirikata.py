#!/usr/bin/env python

import cluster.util.arguments as arguments
import os, subprocess

def package(*args, **kwargs):
    """sirikata package /path/to/installed/sirikata

    Package a version of Sirikata installed in the given path.
    """

    installed_path = arguments.parse_or_die(package, [str], *args)

    # Sanity check
    if not os.path.exists(installed_path):
        print "Location of installed Sirikata binaries doesn't exist..."
        return 1

    bin_path = os.path.join(installed_path, 'bin')
    lib_path = os.path.join(installed_path, 'lib')
    share_path = os.path.join(installed_path, 'share')
    if not os.path.exists(bin_path) or not os.path.exists(lib_path) or not os.path.exists(share_path):
        print "Installed Sirikata doesn't have expected layout with bin/, lib/, and share/..."
        return 1

    # Generate archive
    print "Creating archive, this can take awhile..."
    gen_file = os.path.join(installed_path, 'sirikata.tar.bz2')
    return subprocess.call(['tar', '-cjf', 'sirikata.tar.bz2', './bin', './lib', './share'], cwd=installed_path)
