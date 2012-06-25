##############################################################################
#
# Copyright (c) 2011 Zope Foundation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################

import json
import logging
import sys

logger = logging.getLogger(__name__)

_servers = []

def notify(event):
    _servers.append(dict(address=event.name, path=event.path,
                         **event.properties))

def servers(connection, path=None):
    if path is None:
        connection.write(json.dumps(_servers) + '\n')
    else:
        connection.write(
            ' '.join([s['address'] for s in _servers if s['path'] == path])
             + '\n')

def _connect(addr):
    import re
    import socket

    if re.search(':\d+$', addr):
        host, port = addr.rsplit(':')
        addr = host, int(port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    else:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    sock.connect(addr)
    return sock

def check(args=None):
    if args is None:
        args = sys.argv[1:]

    [addr, path] = args

    try:
        sock = _connect(addr)

        sock.sendall('servers %s\n' % path)
        f = sock.makefile()
        addr = f.readline()

        f.close()
        sock.close()

        _connect(addr).close()
    except Exception:
        logger.debug("Failed check", exc_info=True)
        sys.exit(1)

def get_addr(args=None):
    if args is None:
        args = sys.argv[1:]


    [addr, path] = args

    sock = _connect(addr)
    f = sock.makefile()
    sock.sendall('servers %s\n' % path)
    print f.readline(),
