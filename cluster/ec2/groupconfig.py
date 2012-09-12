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
        if hasattr(node, 'dns_name'):
            return node.dns_name
        return node['dns_name']

    def sirikata_path(self, node=None):
        return '/home/ubuntu/sirikata'

    def default_working_path(self, node=None):
        return '/home/ubuntu'

    def workspace_path(self, node=None):
        return '/home/ubuntu'

    def capabilities(self, node=None):
        if not self.state['capabilities']: return []
        if node['id'] not in self.state['capabilities']: return []
        cap_val = self.state['capabilities'][node['id']]
        if type(cap_val) == str: return [cap_val]
        return cap_val

    def get_node_name(self, idx_or_name_or_node):
        '''Gets a nodes name based on '''

        if type(idx_or_name_or_node) == int:
            return self.state['instances'][idx_or_name_or_node]

        if type(idx_or_name_or_node) == str or type(idx_or_name_or_node) == unicode:
            if ( any([x == idx_or_name_or_node for x in self.state['instances']]) ):
                return idx_or_name_or_node
            try: # may be string-encoded index
                idx = int(idx_or_name_or_node)
                return self.state['instances'][idx]
            except:
                pass
            raise Exception("Couldn't decode %s as index, name, or node object" % (idx_or_name_or_node))

        return idx_or_name_or_node['id']
