import nodes
import puppet
import sirikata
import cluster.util
from groupconfig import EC2GroupConfig

class NodeGroup(cluster.util.NodeGroup):
    # Raw command handlers, exported to the sirikata-cluster.py tool.
    handlers = [
        ('ec2 security create', nodes.create_security_group),
        ('ec2 create', nodes.create),
        ('ec2 nodes boot', nodes.boot),
        ('ec2 nodes request spot instances', nodes.request_spot_instances),
        ('ec2 nodes import', nodes.import_nodes),
        ('ec2 nodes wait ready', nodes.wait_nodes_ready),
        ('ec2 members info', nodes.members_info),
        ('ec2 node ssh', nodes.node_ssh),
        ('ec2 ssh', nodes.ssh),
        ('ec2 add service', nodes.add_service),
        ('ec2 service status', nodes.service_status),
        ('ec2 list services', nodes.list_services),
        ('ec2 remove service', nodes.remove_service),
        ('ec2 remove all services', nodes.remove_all_services),
        ('ec2 node set type', nodes.set_node_type),
        ('ec2 nodes terminate', nodes.terminate),
        ('ec2 destroy', nodes.destroy),
        ('ec2 sync sirikata', sirikata.sync_sirikata),
        ('ec2 sync files', nodes.sync_files),

        ('puppet master config', puppet.master_config),
        ('puppet slaves restart', puppet.slaves_restart),
        ('puppet update', puppet.update),

        # Version that only packages into a tar.bz2 but doesn't
        # distribute. Needs to be included as a command somehwere, but
        # doesn't belong to any one NodeGroup class, so here is as
        # good as anywhere else
        ('sirikata package', cluster.util.sirikata.package)
        ]

    ConfigClass = EC2GroupConfig

    def __init__(self, name):
        super(NodeGroup, self).__init__(name=name)


    def boot(self, **kwargs):
        return (nodes.boot(self.config, **kwargs) == 0)

    def nodes(self, **kwargs):
        return nodes.members_info_data(self.config)

    def sync_sirikata(self, path, **kwargs):
        return (sirikata.sync_sirikata(self.config, path) == 0)

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
        return (nodes.terminate(self.config, **kwargs) == 0)
