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

    def boot():
        raise Exception("Boot isn't properly defined")
