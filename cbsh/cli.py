#####################################################################################
#
#  Copyright (c) Crossbar.io Technologies GmbH
#
#  Unless a separate license agreement exists between you and Crossbar.io GmbH (e.g.
#  you have purchased a commercial license), the license terms below apply.
#
#  Should you enter into a separate license agreement after having received a copy of
#  this software, then the terms of such license agreement replace the terms below at
#  the time at which such license agreement becomes effective.
#
#  In case a separate license agreement ends, and such agreement ends without being
#  replaced by another separate license agreement, the license terms below apply
#  from the time at which said agreement ends.
#
#  LICENSE TERMS
#
#  This program is free software: you can redistribute it and/or modify it under the
#  terms of the GNU General Public License, version 3, as published by the
#  Free Software Foundation. This program is distributed in the hope that it will be
#  useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
#  See the GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License along
#  with this program. If not, see <https://www.gnu.org/licenses/gpl-3.0.en.html>.
#
#####################################################################################

import sys
import platform
import importlib
import hashlib

import six
import click

# this is for pyinstaller! otherwise it fails to find this dep.
# see: http://cffi.readthedocs.io/en/latest/cdef.html
import _cffi_backend  # noqa

# import and select network framework in txaio _before_ any further cbsh imports
import txaio
txaio.use_asyncio()

from cbsh import app, command, quickstart  # noqa: E402
from cbsh import __version__, __build__  # noqa: E402

USAGE = """
Examples:
To start the interactive shell, use the "shell" command:

    cbf shell

You can run the shell under different user profile
using the "--profile" option:

    cbf --profile mister-test1 shell
"""

# the global, singleton app object
_app = app.Application()


def hl(text):
    if not isinstance(text, six.text_type):
        text = '{}'.format(text)
    return click.style(text, fg='yellow', bold=True)


class Config(object):
    """
    Command configuration object where we collect all the parameters,
    options etc for later processing.
    """

    def __init__(self, app, profile, realm, role):
        self.app = app
        self.profile = profile
        self.realm = realm
        self.role = role
        self.resource_type = None
        self.resource = None

    def __str__(self):
        return u'Config(resource_type={}, resource={})'.format(
            self.resource_type, self.resource)


@click.group(
    help="Crossbar.io Fabric Command Line", invoke_without_command=True)
@click.option(
    '--profile',
    envvar='CBF_PROFILE',
    default=u'default',
    help="Set the profile to be used",
)
@click.option(
    '--realm',
    envvar='CBF_REALM',
    default=None,
    help="Set the realm to join",
)
@click.option(
    '--role',
    envvar='CBF_ROLE',
    default=None,
    help="Set the role requested to authenticate as",
)
@click.pass_context
def cli(ctx, profile, realm, role):
    ctx.obj = Config(_app, profile, realm, role)

    # Allowing a command group to specifiy a default subcommand can be done using
    # https://github.com/click-contrib/click-default-group
    #
    # However, this breaks the click-repl integration for prompt-toolkit:
    #
    # https://github.com/pallets/click/issues/430#issuecomment-282015177
    #
    # Hence, we are using a different (probably less clean) trick - this works.
    #
    if ctx.invoked_subcommand is None:
        ctx.invoke(cmd_shell)


@cli.command(name='version', help='print version information')
@click.pass_obj
def cmd_version(cfg):
    def get_version(name_or_module):
        if isinstance(name_or_module, str):
            name_or_module = importlib.import_module(name_or_module)
        try:
            return name_or_module.__version__
        except AttributeError:
            return ''

    # Python (language)
    py_ver = '.'.join([str(x) for x in list(sys.version_info[:3])])

    # Python (implementation)
    if hasattr(sys, 'pypy_version_info'):
        pypy_version_info = getattr(sys, 'pypy_version_info')
        py_impl_str = '.'.join(str(x) for x in pypy_version_info[:3])
        py_ver_detail = "{}-{}".format(platform.python_implementation(),
                                       py_impl_str)
    else:
        py_ver_detail = platform.python_implementation()

    # Autobahn
    ab_ver = get_version('autobahn')

    # Pyinstaller (frozen EXE)
    py_is_frozen = getattr(sys, 'frozen', False)
    if py_is_frozen:
        m = hashlib.sha256()
        with open(sys.executable, 'rb') as fd:
            m.update(fd.read())
        fingerprint = m.hexdigest()
    else:
        fingerprint = None

    # Docker Compose
    try:
        import compose
    except ImportError:
        compose_ver = 'not installed'
    else:
        compose_ver = compose.__version__

    # Sphinx
    try:
        import sphinx
    except ImportError:
        sphinx_ver = 'not installed'
    else:
        sphinx_ver = sphinx.__version__

    platform_str = platform.platform(terse=True, aliased=True)

    click.echo()
    click.echo(
        hl("  Crossbar.io Shell") +
        ' - Interactive shell and toolbelt for Crossbar.io')
    click.echo()
    click.echo((
        "  Copyright (c) Crossbar.io Technologies GmbH. Licensed under the GPL 3.0 license"
    ))
    click.echo((
        "  unless a separate license agreement exists between you and Crossbar.io GmbH."
    ))
    click.echo()
    click.echo('  {:<24}: {}'.format('Version',
                                     hl('{} (build {})'.format(
                                         __version__, __build__))))
    click.echo('  {:<24}: {}'.format('Platform', hl(platform_str)))
    click.echo('  {:<24}: {}'.format('Python (language)', hl(py_ver)))
    click.echo('  {:<24}: {}'.format('Python (implementation)',
                                     hl(py_ver_detail)))
    click.echo('  {:<24}: {}'.format('Autobahn', hl(ab_ver)))
    click.echo('  {:<24}: {}'.format('Docker Compose', hl(compose_ver)))
    click.echo('  {:<24}: {}'.format('Sphinx', hl(sphinx_ver)))
    click.echo('  {:<24}: {}'.format('Frozen executable',
                                     hl('yes' if py_is_frozen else 'no')))
    if py_is_frozen:
        click.echo('  {:<24}: {}'.format('Executable SHA256', hl(fingerprint)))
    click.echo()


@cli.command(
    name='quickstart', help='generate a complete starter container stack')
@click.pass_obj
def cmd_quickstart(cfg):
    quickstart.run(cfg)


@cli.command(
    name='auth',
    help='authenticate user profile / key-pair with Crossbar.io Fabric')
@click.option(
    '--code',
    default=None,
    help="Supply authentication code (received by email)",
)
@click.option(
    '--new-code',
    is_flag=True,
    default=False,
    help=  # noqa: E251
    "Request sending of a new authentication code (even though an old one is still pending)",
)
@click.pass_context
def cmd_auth(ctx, code, new_code):
    cfg = ctx.obj
    cfg.code = code
    cfg.new_code = new_code
    ctx.obj.app.run_context(ctx)


@cli.command(name='shell', help='run an interactive Crossbar.io Shell')
@click.pass_context
def cmd_shell(ctx):
    ctx.obj.app.run_context(ctx)


@cli.command(name='clear', help='clear screen')
async def cmd_clear():
    click.clear()


@cli.command(name='help', help='general help')
@click.pass_context
def cmd_help(ctx):
    click.echo(ctx.parent.get_help())
    click.echo(USAGE)


@cli.group(name='set', help='change shell settings')
@click.pass_obj
def cmd_set(cfg):
    pass


#
# set output-verbosity
#
@cmd_set.group(name='output-verbosity', help='command output verbosity')
@click.pass_obj
def cmd_set_output_verbosity(cfg):
    pass


@cmd_set_output_verbosity.command(
    name='silent',
    help='swallow everything including result, but error messages')
@click.pass_obj
def cmd_set_output_verbosity_silent(cfg):
    cfg.app.set_output_verbosity('silent')


@cmd_set_output_verbosity.command(
    name='result-only', help='only output the plain command result')
@click.pass_obj
def cmd_set_output_verbosity_result_only(cfg):
    cfg.app.set_output_verbosity('result-only')


@cmd_set_output_verbosity.command(
    name='normal', help='output result and short run-time message')
@click.pass_obj
def cmd_set_output_verbosity_normal(cfg):
    cfg.app.set_output_verbosity('normal')


@cmd_set_output_verbosity.command(
    name='extended', help='output result and extended execution information.')
@click.pass_obj
def cmd_set_output_verbosity_extended(cfg):
    cfg.app.set_output_verbosity('extended')


#
# set output-format
#
@cmd_set.group(name='output-format', help='command output format')
@click.pass_obj
def cmd_set_output_format(cfg):
    pass


def _make_set_output_format(output_format):
    @cmd_set_output_format.command(
        name=output_format,
        help='set {} output format'.format(output_format.upper()))
    @click.pass_obj
    def f(cfg):
        cfg.app.set_output_format(output_format)

    return f


for output_format in app.Application.OUTPUT_FORMAT:
    _make_set_output_format(output_format)


#
# set output-style
#
@cmd_set.group(name='output-style', help='command output style')
@click.pass_obj
def cmd_set_output_style(cfg):
    pass


def _make_set_output_style(output_style):
    @cmd_set_output_style.command(
        name=output_style,
        help='set {} output style'.format(output_style.upper()))
    @click.pass_obj
    def f(cfg):
        cfg.app.set_output_style(output_style)

    return f


for output_style in app.Application.OUTPUT_STYLE:
    _make_set_output_style(output_style)


@cli.group(name='create', help='create resources')
@click.pass_obj
def cmd_create(cfg):
    pass


@cmd_create.command(
    name='management-realm', help='create a new management realm')
@click.argument('realm')
@click.pass_obj
async def cmd_create_management_realm(cfg, realm):
    cmd = command.CmdCreateManagementRealm(realm=realm)
    await cfg.app.run_command(cmd)


@cli.group(name='pair', help='pair nodes and devices')
@click.pass_obj
def cmd_pair(cfg):
    pass


@cmd_pair.command(name='node', help='pair a node')
@click.argument('pubkey')
@click.argument('realm')
@click.argument('node_id')
@click.pass_obj
async def cmd_pair_node(cfg, pubkey, realm, node_id):
    cmd = command.CmdPairNode(pubkey=pubkey, realm=realm, node_id=node_id)
    await cfg.app.run_command(cmd)


@cli.group(name='start', help='start workers, components, ..')
@click.pass_obj
def cmd_start(cfg):
    pass


# @cmd_start.command(name='worker', help='start a worker')
# @click.argument('node')
# @click.argument('worker')
# @click.argument('worker-type')
# @click.option('--options', help='worker options', default=None)
# @click.pass_obj
# async def cmd_start_worker(cfg, node, worker, worker_type, options=None):
#    cmd = command.CmdStartWorker(node, worker, worker_type, worker_options=options)
#    await cfg.app.run_command(cmd)
# from cbsh.command import CmdStartContainerWorker, CmdStartContainerComponent


@cmd_start.command(name='container-worker', help='start a container worker')
@click.option(
    '--process-title', help='worker process title (at OS level)', default=None)
@click.argument('node')
@click.argument('worker')
@click.pass_obj
async def cmd_start_container_worker(cfg, node, worker, process_title=None):
    cmd = command.CmdStartContainerWorker(
        node, worker, process_title=process_title)
    await cfg.app.run_command(cmd)


@cmd_start.command(
    name='container-component', help='start a container component')
@click.option(
    '--classname', help='fully qualified Python class name', required=True)
@click.option('--realm', help='realm to join this component on', required=True)
@click.option(
    '--transport-type',
    help='connecting transport type',
    required=True,
    type=click.Choice(['websocket', 'rawsocket']))
@click.option(
    '--transport-ws-url',
    help='WebSocket transport connecting URL (eg wss://example.com:9000/ws',
    type=str)
@click.option(
    '--transport-endpoint-type',
    help='connecting transport endpoint type',
    required=True,
    type=click.Choice(['tcp', 'unix']))
@click.option(
    '--transport-tcp-host', help='connecting TCP transport host', type=str)
@click.option(
    '--transport-tcp-port', help='connecting TCP transport port', type=int)
@click.argument('node')
@click.argument('worker')
@click.argument('component')
@click.pass_obj
async def cmd_start_container_component(
        cfg,
        node,
        worker,
        component,
        classname=None,
        realm=None,
        transport_type=None,
        transport_ws_url=None,
        transport_endpoint_type=None,
        transport_tcp_host=None,
        transport_tcp_port=None,
):
    cmd = command.CmdStartContainerComponent(
        node,
        worker,
        component,
        classname=classname,
        realm=realm,
        transport_type=transport_type,
        transport_ws_url=transport_ws_url,
        transport_endpoint_type=transport_endpoint_type,
        transport_tcp_host=transport_tcp_host,
        transport_tcp_port=transport_tcp_port)
    await cfg.app.run_command(cmd)


@cli.group(name='list', help='list resources')
@click.pass_obj
def cmd_list(cfg):
    pass


@cmd_list.command(name='management-realms', help='list management realms')
@click.pass_obj
async def cmd_list_management_realms(cfg):
    cmd = command.CmdListManagementRealms()
    await cfg.app.run_command(cmd)


@cmd_list.command(name='nodes', help='list nodes')
@click.pass_obj
async def cmd_list_nodes(cfg):
    cmd = command.CmdListNodes()
    await cfg.app.run_command(cmd)


@cmd_list.command(name='workers', help='list workers')
@click.argument('node')
@click.pass_obj
async def cmd_list_workers(cfg, node):
    cmd = command.CmdListWorkers(node)
    await cfg.app.run_command(cmd)


@cli.group(name='show', help='show resources')
@click.pass_obj
def cmd_show(cfg):
    pass


@cmd_show.command(name='fabric', help='show fabric')
@click.pass_obj
async def cmd_show_fabric(cfg):
    cmd = command.CmdShowFabric()
    await cfg.app.run_command(cmd)


@cmd_show.command(name='node', help='show node')
@click.argument('node')
@click.pass_obj
async def cmd_show_node(cfg, node):
    cmd = command.CmdShowNode(node)
    await cfg.app.run_command(cmd)


@cmd_show.command(name='worker', help='show worker')
@click.argument('node')
@click.argument('worker')
@click.pass_obj
async def cmd_show_worker(cfg, node, worker):
    cmd = command.CmdShowWorker(node, worker)
    await cfg.app.run_command(cmd)


@cmd_show.command(name='transport', help='show transport (for router workers)')
@click.argument('node')
@click.argument('worker')
@click.argument('transport')
@click.pass_obj
async def cmd_show_transport(cfg, node, worker, transport):
    cmd = command.CmdShowTransport(node, worker, transport)
    await cfg.app.run_command(cmd)


@cmd_show.command(name='realm', help='show realm (for router workers)')
@click.argument('node')
@click.argument('worker')
@click.argument('realm')
@click.pass_obj
async def cmd_show_realm(cfg, node, worker, realm):
    cmd = command.CmdShowRealm(node, worker, realm)
    await cfg.app.run_command(cmd)


@cmd_show.command(
    name='component', help='show component (for container and router workers)')
@click.argument('node')
@click.argument('worker')
@click.argument('component')
@click.pass_obj
async def cmd_show_component(cfg, node, worker, component):
    cmd = command.CmdShowComponent(node, worker, component)
    await cfg.app.run_command(cmd)


@cli.command(name='current', help='currently selected resource')
@click.pass_obj
async def cmd_current(cfg):
    _app.print_selected()


@cli.group(name='select', help='change current resource')
@click.pass_obj
def cmd_select(cfg):
    pass


@cmd_select.command(name='node', help='change current node')
@click.argument('resource')
@click.pass_obj
async def cmd_select_node(cfg, resource):
    _app.current_resource_type = u'node'
    _app.current_resource = resource
    _app.print_selected()


@cmd_select.command(name='worker', help='change current worker')
@click.argument('resource')
@click.pass_obj
async def cmd_select_worker(cfg, resource):
    _app.current_resource_type = u'worker'
    _app.current_resource = resource
    _app.print_selected()


@cmd_select.command(name='transport', help='change current transport')
@click.argument('resource')
@click.pass_obj
async def cmd_select_transport(cfg, resource):
    _app.current_resource_type = u'transport'
    _app.current_resource = resource
    _app.print_selected()


def main():
    """
    Main entry point into CLI.
    """

    # forward to sphinx-build
    if len(sys.argv) > 1 and sys.argv[1] == 'sphinx':
        try:
            from sphinx.cmd.build import main as _forward_main
        except ImportError:
            raise click.Abort(
                'could not import sphinx-build - command forwarding failed!')
        else:
            argv = []
            if len(sys.argv) > 2:
                argv.extend(sys.argv[2:])
            sys.exit(_forward_main(argv=argv))
    else:
        cli()  # pylint: disable=E1120


if __name__ == '__main__':
    main()
