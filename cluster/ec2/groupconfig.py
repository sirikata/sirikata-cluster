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


    def user(self, node=None):
        return 'ubuntu'

    def hostname(self, node=None):
        return node['dns_name']

    def sirikata_path(self, node=None):
        return '/home/ubuntu/sirikata'

    def default_working_path(self, node=None):
        return '/home/ubuntu'

    def workspace_path(self, node=None):
        return '/home/ubuntu'



    def get_node_name(self, idx_or_name_or_node):
        '''Gets a nodes name based on '''

        if type(idx_or_name_or_node) == int:
            return self.state['instances'][idx_or_name_or_node]

        if type(idx_or_name_or_node) == str:
            assert( any([x == idx_or_name_or_node for x in self.state['instances']]) )
            return idx_or_name_or_node

        return idx_or_name_or_node['id']
