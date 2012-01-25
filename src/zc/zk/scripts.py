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
import zookeeper

def export(args=None):
    """Usage: %prog [options] connection [path]
    """
    if args is None:
        args = sys.argv[1:]

    parser = optparse.OptionParser(export.__doc__)
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


def import_(args=None):
    """Usage: %prog [options] connection [import-file [path]]

    Import a tree definition from a file.

    If no import-file is provided or if the import file is -, then
    data are read from standard input.
    """

    if args is None:
        args = sys.argv[1:]

    parser = optparse.OptionParser(import_.__doc__)
    parser.add_option('-d', '--dry-run', action='store_true')
    parser.add_option('-t', '--trim', action='store_true')
    parser.add_option(
        '-p', '--permission', type='int',
        default=zookeeper.PERM_ALL,
        help='ZooKeeper permission bits as integer,'
        ' defaulting to zookeeper.PERM_ALL',
        )

    options, args = parser.parse_args(args)
    if not (1 <= len(args) <= 3):
        parser.parse_args(['-h'])

    connection = args.pop(0)
    if args:
        import_file = args.pop(0)
    else:
        import_file = '-'

    if args:
        [path] = args
    else:
        path = '/'

    logging.basicConfig(level=logging.WARNING)

    zk = zc.zk.ZooKeeper(connection)
    if import_file == '-':
        import_file = sys.stdin
    else:
        import_file = open(import_file)

    zk.import_tree(
        import_file.read(), path,
        trim=options.trim,
        dry_run=options.dry_run,
        acl=[zc.zk.world_permission(options.permission)],
        )

