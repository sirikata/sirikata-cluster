import nodes
import cluster.util
from groupconfig import AdHocGroupConfig

class NodeGroup(cluster.util.NodeGroup):
    # Raw command handlers, exported to the sirikata-cluster.py tool.
    handlers = [
        ('adhoc create', nodes.create),
        ('adhoc members info', nodes.members_info),
        ('adhoc node ssh', nodes.node_ssh),
        ('adhoc ssh', nodes.ssh),
        ('adhoc sync sirikata', nodes.sync_sirikata),
        ('adhoc add service', nodes.add_service),
        ('adhoc remove service', nodes.remove_service),
        ('adhoc destroy', nodes.destroy),
        ]

    ConfigClass = AdHocGroupConfig

    def __init__(self, name):
        super(NodeGroup, self).__init__(name=name)



    def user(self):
        return self.config.user

    def sirikata_path(self):
        return self.config.sirikata_path

    def default_working_path(self):
        return self.config.default_work_path

    def workspace(self):
        '''Returns a workspace directory that won't be cleaned up
        automatically (i.e. not /tmp), is local to the machine
        (i.e. no NFS shares), and won't clutter up a user's directory
        if used for temporary files.'''
        return self.config.workspace()



    def boot(self, **kwargs):
        # Nothing to do, we assume the lifecycle for ad-hoc clusters are managed separately
        return True

    def nodes(self, **kwargs):
        return nodes.members_info_data(self.config)

    def sync_sirikata(self, path, **kwargs):
        return (nodes.sync_sirikata(self.config, path) == 0)

    def add_service(self, name, target, command, user=None, cwd=None, **kwargs):
        nkwargs = dict(kwargs)
        if user is not None: nkwargs['user'] = user
        if cwd is not None: nkwargs['cwd'] = cwd
        return (nodes.add_service(self.config, name, target, *command, **nkwargs) == 0)

    def remove_service(self, name, **kwargs):
        return (nodes.remove_service(self.config, name) == 0)

    def terminate(self, **kwargs):
        # Nothing to do, we assume the lifecycle for ad-hoc clusters are managed separately
        return True
