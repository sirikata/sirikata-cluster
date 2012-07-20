# Make sure this path is in the set of import paths. It may have been
# imported relative to some other file, adding this here makes sure
# files in here will be able to import cluster.foo.bar
import sys, os.path
sys.path.append( os.path.dirname(os.path.dirname(os.path.abspath(__file__))) )

import ec2

# List of cluster types (e.g. ec2, local (just localhost), grid
# (simple ssh to a cluster), aggregate (meta-cluster built from
# others), etc). Each is a subclass of cluster.util.NodeGroup which
# can load a config and perform a basic set of shared functionality
ClusterTypes = [ ec2.NodeGroup ]
