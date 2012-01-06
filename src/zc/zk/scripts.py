##############################################################################
#
# Copyright Zope Foundation and Contributors.
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
import logging
import optparse
import sys
import zc.zk

def export(args=None):
    if args is None:
        args = sys.argv[1:]

    parser = optparse.OptionParser("""
    Usage: %prog [options] connection [path]
    """)
    parser.add_option('-e', '--ephemeral', action='store_true')
    parser.add_option('-o', '--output')

    options, args = parser.parse_args(args)
    connection = args.pop(0)
    if args:
        [path] = args
    else:
        path = '/'

    logging.basicConfig(level=logging.WARNING)

    zk = zc.zk.ZooKeeper(connection)
    data = zk.export_tree(path, ephemeral=options.ephemeral)

    if options.output:
        with open(options.output, 'w') as f:
            f.write(data)
    else:
        print data,
