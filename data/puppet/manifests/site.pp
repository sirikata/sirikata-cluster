# Node definitions. We specify the default as just a regular sirikata
# node. Combinations are provided to be inherited from. These should
# probably only be Sirikata + one other service.
node default {
  include sirikata
}

node sirikata_redis inherits default {
  include redis
}

# We get node-specific configuration from a generated nodes.pp
# file. Only non-default nodes are added to it.
import "nodes"
