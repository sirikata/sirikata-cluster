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
        ('adhoc sync files', nodes.sync_files),
        ('adhoc add service', nodes.add_service),
        ('adhoc service status', nodes.service_status),
        ('adhoc remove service', nodes.remove_service),
        ('adhoc destroy', nodes.destroy),
        ]

    ConfigClass = AdHocGroupConfig

    def __init__(self, name):
        super(NodeGroup, self).__init__(name=name)


    def boot(self, **kwargs):
        # Nothing to do, we assume the lifecycle for ad-hoc clusters are managed separately
        return True

    def nodes(self, **kwargs):
        return nodes.members_info_data(self.config)

    def sync_sirikata(self, path, **kwargs):
        return (nodes.sync_sirikata(self.config, path) == 0)

    def sync_files(self, target, src, dest, **kwargs):
        return (nodes.sync_files(self.config, target, src, dest, **kwargs) == 0)

    def add_service(self, name, target, command, user=None, cwd=None, **kwargs):
        nkwargs = dict(kwargs)
        if user is not None: nkwargs['user'] = user
        if cwd is not None: nkwargs['cwd'] = cwd
        return (nodes.add_service(self.config, name, target, *command, **nkwargs) == 0)

    def service_status(self, name, **kwargs):
        return (nodes.service_status(self.config, name) == 0)

    def remove_service(self, name, **kwargs):
        return (nodes.remove_service(self.config, name) == 0)

    def terminate(self, **kwargs):
        # Nothing to do, we assume the lifecycle for ad-hoc clusters are managed separately
        return True
