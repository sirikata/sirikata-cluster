import os, json

class NodeGroupConfig(object):
    '''
    Base class for configuration. This class will load the config from
    JSON or set attributes for initial parameters passed into the
    constructor, provides shared functionality, and ensures a small
    set of parameters are always available.
    '''

    Attributes = ['name', 'typename', 'size', 'state']
    '''Attributes which should be stored at the top level of the
    config and should be set as attributes on the class during
    loading/initialization for convenience'''

    def __init__(self, name, **kwargs):
        '''Specify either a name only, which loads from a file, or *all* the parameters'''
        if not kwargs: # if one other value isn't defined, must have file
            values = json.load(open(self._filename(name), 'r'))
            self.name = name
            for attrname in self.Attributes:
                if attrname == 'name': continue
                setattr(self, attrname, values[attrname])
        else:
            self.name = name
            for attrname in self.Attributes:
                print attrname
                assert((attrname == 'name' or attrname == 'state') or attrname in kwargs)
                if (attrname == 'name' or attrname == 'state'): continue
                setattr(self, attrname, kwargs[attrname])
            # Everything else is temporary/mutable state that we just
            # want to keep track of for future operations
            self.state = {}

    def _filename(self, newname=None):
        return '.cluster-config-' + (newname or self.name) + '.json'

    def save(self):
        data = dict([(name, getattr(self, name)) for name in self.Attributes])
        json.dump(data, open(self._filename(), 'w'), indent=4)

    def delete(self):
        os.remove(self._filename())



class NodeGroup(object):
    '''
    Base class for groups of nodes considered a cluster. Defines the
    base functionality for clusters.
    '''

    ConfigClass = NodeGroupConfig

    def __init__(self, name, **kwargs):
        self.config = self.ConfigClass(name=name, **kwargs)


    # Properties

    def user(self):
        '''The user used to login, manage the node, and start services.'''
        raise Exception("NodeGroup.user isn't properly defined")

    def sirikata_path(self):
        '''The path to the sirikata directory.'''
        raise Exception("NodeGroup.sirikata_path isn't properly defined")

    def default_working_path(self):
        '''The default working path the user will be in when starting
        services. This can be useful for placing input data or
        extracting output data, although ideally you would use
        absolute paths instead of relying on defaults.
        '''
        raise Exception("NodeGroup.default_working_path isn't properly defined")


    # Operations

    def boot(self, **kwargs):
        '''If necessary, boot nodes and block until they have
        completed configuration.'''

        raise Exception("NodeGroup.boot isn't properly defined")

    def nodes(self, **kwargs):
        '''Get a list of node information.'''

        raise Exception("NodeGroup.boot isn't properly defined")

    def add_service(self, name, target, command, user, cwd, **kwargs):
        '''Add a service, running the given command, to this node group.'''

        raise Exception("NodeGroup.boot isn't properly defined")

    def remove_service(self, name, **kwargs):
        '''Remove a service from this node group.'''
        raise Exception("NodeGroup.boot isn't properly defined")

    def terminate(self, **kwargs):
        '''If necessary, terminate the nodes in this node group.'''
        raise Exception("NodeGroup.boot isn't properly defined")
