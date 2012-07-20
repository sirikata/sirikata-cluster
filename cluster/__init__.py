# Make sure this path is in the set of import paths. It may have been
# imported relative to some other file, adding this here makes sure
# files in here will be able to import cluster.foo.bar
import sys, os.path
sys.path.append( os.path.dirname(os.path.dirname(os.path.abspath(__file__))) )
