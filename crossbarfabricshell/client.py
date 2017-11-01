###############################################################################
#
# The MIT License (MIT)
#
# Copyright (c) Crossbar.io Technologies GmbH
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", fWITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
###############################################################################

import argparse
import asyncio
import binascii
import os
import sys

import txaio
txaio.use_asyncio()

from txaio import make_logger

import asyncio
from autobahn.wamp.exception import ApplicationError
from autobahn.asyncio.wamp import ApplicationSession, ApplicationRunner
from autobahn.wamp import cryptosign

__all__ = (
    'BaseCryptosignClientSession',
    'ShellClient',
    'ManagementClientSession',
    'run',
)


class BaseCryptosignClientSession(ApplicationSession):

    def onConnect(self):
        self.log.debug("BaseCryptosignClientSession connected to router")

        self._key = self.config.extra[u'key']

        # authentication extra information for wamp-cryptosign
        #
        extra = {
            # forward the client pubkey: this allows us to omit authid as
            # the router can identify us with the pubkey already
            u'pubkey': self._key.public_key(),

            # not yet implemented. a public key the router should provide
            # a trustchain for it's public key. the trustroot can eg be
            # hard-coded in the client, or come from a command line option.
            u'trustroot': None,

            # not yet implemented. for authenticating the router, this
            # challenge will need to be signed by the router and send back
            # in AUTHENTICATE for client to verify. A string with a hex
            # encoded 32 bytes random value.
            u'challenge': None,

            # this is only implemented on Twisted, and does NOT
            # work currently on asyncio !
            # u'channel_binding': u'tls-unique',
        }

        # used for user login/registration activation code
        for k in [u'activation_code', u'request_new_activation_code']:
            if k in self.config.extra and self.config.extra[k]:
                extra[k] = self.config.extra[k]

        # now request to join ..
        self.join(self.config.realm,
                  authmethods=[u'cryptosign'],
                  authid=self.config.extra.get(u'authid', None),
                  authrole=self.config.extra.get(u'authrole', None),
                  authextra=extra)

    def onChallenge(self, challenge):
        # sign and send back the challenge with our private key.
        return self._key.sign_challenge(self, challenge)

    def onDisconnect(self):
        asyncio.get_event_loop().stop()


class BaseAnonymousClientSession(ApplicationSession):

    def onConnect(self):
        self.log.debug("BaseAnonymousClientSession connected to router")

        # now request to join ..
        self.join(self.config.realm,
                  authmethods=[u'anonymous'],
                  authextra=self.config.extra.get(u'authextra', None))

    def onDisconnect(self):
        asyncio.get_event_loop().stop()


class _ShellClient(object):

    log = make_logger()

    async def onJoin(self, details):
        self.log.debug("ShellClient session joined: {details}", details=details)

        self._ticks = 0

        def on_tick(tick):
            self._ticks += 1

        await self.subscribe(on_tick, u'crossbarfabriccenter.tick')

        done = self.config.extra.get(u'done', None)
        if done and not done.done():
            done.set_result(details)

        self.log.debug("session ready!")

    def onLeave(self, details):
        self.log.debug("session closed: {details}", details=details)

        # reason=<wamp.error.authentication_failed>
        if details.reason != u'wamp.close.normal':
            done = self.config.extra.get(u'done', None)
            if done and not done.done():
                done.set_exception(ApplicationError(details.reason, details.message))

        self.disconnect()


class ShellClient(_ShellClient, BaseCryptosignClientSession):
    pass

class ShellAnonymousClient(_ShellClient, BaseAnonymousClientSession):
    pass


class _ManagementClientSession(object):

    log = make_logger()

    async def onJoin(self, details):
        self.log.debug("ManagementClientSession joined: {details}", details=details)

        main = self.config.extra.get(u'main', None)
        if main:
            self.log.debug('Running main() ...')
            return_code = 0
            try:
                return_code = await main(self)
            except Exception as e:
                # something bad happened: investigate your side or pls file an issue;)
                return_code = -1
                self.log.error('Error during management session main(): {error}', error=e)
            finally:
                # in any case, shutdown orderly
                if return_code:
                    self.config.extra[u'return_code'] = return_code
                # in any case, shutdown orderly
                if not self._goodbye_sent:
                    self.leave()
        else:
            self.log.warn('no main() configured!')
            self.leave()

    def onLeave(self, details):
        self.log.debug("CFC session closed: {details}", details=details)
        self.disconnect()


class ManagementClientSession(_ManagementClientSession, BaseCryptosignClientSession):
    pass

class ManagementAnonymousClientSession(_ManagementClientSession, BaseAnonymousClientSession):
    pass


def run(main=None):
    # parse command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', dest='debug', action='store_true', default=False,
                        help='Enable logging at level "debug".')
    parser.add_argument('--url', dest='url', type=str, default=u'wss://fabric.crossbario.com',
                        help='The Crossbar.io Fabric Center (CFC) WebSocket URL '
                             '(default: wss://fabric.crossbario.com')
    parser.add_argument('--realm', dest='realm', type=str,
                        help='The management realm to join on CFC')
    parser.add_argument('--keyfile', dest='keyfile', type=str, default=u'~/.cbf/default.priv',
                        help='The private client key file to use for authentication.')
    parser.add_argument('--authmethod', dest='authmethod', type=str, default=u'cryptosign',
                        help='Authentication method: cryptosign or anonymous')
    args = parser.parse_args()

    if args.debug:
        txaio.start_logging(level='debug')
    else:
        txaio.start_logging(level='info')

    extra = None
    if args.authmethod == u'cryptosign':

        # for authenticating the management client, we need a Ed25519 public/private key pair
        # here, we are reusing the user key - so this needs to exist before
        privkey_file = os.path.expanduser(args.keyfile)
        privkey_hex = None
        user_id = None

        if not os.path.exists(privkey_file):
            raise Exception('private key file {} does not exist'.format(privkey_file))
        else:
            with open(privkey_file, 'r') as f:
                data = f.read()
                for line in data.splitlines():
                    if line.startswith('private-key-ed25519'):
                        privkey_hex = line.split(':')[1].strip()
                    if line.startswith('user-id'):
                        user_id = line.split(':')[1].strip()

        if privkey_hex is None:
            raise Exception('no private key found in keyfile!')

        if user_id is None:
            raise Exception('no user ID found in keyfile!')

        key = cryptosign.SigningKey.from_key_bytes(binascii.a2b_hex(privkey_hex))

        extra = {
            u'key': key,
            u'authid': user_id,
            u'main': main,
            u'return_code': None
        }

    elif args.authmethod == u'anonymous':

        extra = {
            u'main': main,
            u'return_code': None
        }

    else:
        raise Exception('logic error')

    print(extra)
    runner = ApplicationRunner(url=args.url, realm=args.realm, extra=extra)

    if args.authmethod == u'cryptosign':
        runner.run(ManagementClientSession)
    elif args.authmethod == u'anonymous':
        runner.run(ManagementAnonymousClientSession)
    else:
        raise Exception('logic error')

    return_code = extra[u'return_code']
    if isinstance(return_code, int) and return_code != 0:
        sys.exit(return_code)


if __name__ == '__main__':
    run()
