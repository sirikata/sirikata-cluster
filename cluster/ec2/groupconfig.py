from cluster.util.nodegroup import NodeGroupConfig

class EC2GroupConfig(NodeGroupConfig):
    '''Tracks info about a cluster, backed by a json file'''

    TypeName = 'ec2'
    Attributes = ['name', 'typename', 'size', 'state',
                  'keypair', 'instance_type', 'group', 'ami', 'puppet_master']

    def __init__(self, name, **kwargs):
        # If we've got any non-name params, ensure we have the expected set
        if kwargs:
            assert('keypair' in kwargs and \
                       'instance_type' in kwargs and \
                       'group' in kwargs and \
                       'ami' in kwargs and \
                       'puppet_master' in kwargs)
            super(EC2GroupConfig, self).__init__(name, typename=self.TypeName, **kwargs)
        else:
            super(EC2GroupConfig, self).__init__(name, **kwargs)
