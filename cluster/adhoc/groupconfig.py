from cluster.util.nodegroup import NodeGroupConfig
import json, random

class AdHocGroupConfig(NodeGroupConfig):
    TypeName = 'adhoc'
    Attributes = ['name', 'typename', 'size', 'state',
                  'nodes', # List of nodes or node properties
                  'user', # Default user for ssh if none specified in per-node properties
                  'sirikata_path', # Default path we should install/run Sirikata from if none specified in per-node properties
                  'default_work_path', # Default path we should execute services in and allow them to store files in
                  'default_scratch_path', # Default path for scratch data (e.g. pid files)
                  ]

    def __init__(self, name, **kwargs):
        # If we've got any non-name params, ensure we have the expected set
        if kwargs:
            assert('nodes' in kwargs and \
                       'user' in kwargs and \
                       'sirikata_path' in kwargs and \
                       'default_scratch_path' in kwargs)

            # Filter the nodes definitions to ensure a regular structure
            nodes = []
            for node in kwargs['nodes']:
                # Try to figure out automatically if the string is just a hostname or a full spec
                new_node = {}
                if isinstance(node, str):
                    if node.find('{') == -1 and node.find(' ') == -1:
                        new_node['dns_name'] = node
                    else:
                        # Treat as a json spec
                        new_node = json.loads(node)
                else:
                    new_node = node

                # Fill in any missing data we can derive
                assert('dns_name' in new_node)
                if 'id' not in new_node:
                    new_node['id'] = new_node['dns_name'].split('.')[0]

                nodes.append(new_node)

            # Sanity check node uniqueness
            node_ids = set()
            for node in nodes:
                if node['id'] in node_ids: raise Exception('Found duplicate node identifiers: ' + node['id'])
                node_ids.add(node['id'])

            # And generate new kwargs
            nkwargs = dict(kwargs)
            nkwargs['nodes'] = nodes
            nkwargs['size'] = len(nodes)
            super(AdHocGroupConfig, self).__init__(name, typename=self.TypeName, **nkwargs)
        else:
            super(AdHocGroupConfig, self).__init__(name, **kwargs)


    def workspace(self):
        '''Returns a workspace directory that won't be cleaned up
        automatically (i.e. not /tmp), is local to the machine
        (i.e. no NFS shares), and won't clutter up a user's directory
        if used for temporary files.'''
        return self.default_scratch_path


    def get_node(cc, node_name):
        '''Returns a node's instance info based on any of a number of
        'names'. A pure number will be used directly as an index. The name
        can also match the node's id, private or public IP or dns name, or
        it's pacemaker ID (which is based on the internal IP).

        The special value 'any' will get a random (uniformly) node.
        '''

        if node_name == 'any':
            node_name = random.randint(0, len(cc.nodes))

        if isinstance(node_name, dict):
            assert('id' in node_name and 'dns_name' in node_name)
            return node_name

        try:
            idx = int(node_name)
            return cc.nodes[idx]
        except:
            pass
        for inst in cc.nodes:
            if inst['id'] == node_name or inst['dns_name'] == node_name:
                return inst
        raise Exception("Couldn't find node '" + node_name + "'")


    def node_ssh_address(self, node):
        '''Helper that generates user@foo.com for ssh'ing into a
        machine, grabbing a default username if one is not already
        associated with the node.'''
        user = self.user
        if 'user' in node:
            user = node['user']
        return user + '@' + node['dns_name']
