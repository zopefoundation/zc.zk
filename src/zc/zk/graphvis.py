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
"""This is a doodle/demo for generating a graphvis model from a tree.

It assumes the convention that nodes are "services" if they have a
``providers`` subnode (not a link) and if they or one of their subnodes
symbolically links to a provides node.
"""

import sys
import zc.zk

def _get_edges(tree, path, service, edges):

    if 'providers' in tree.children:
        service = path

    if service:
        for name, value in tree.properties.iteritems():
            if name.endswith(' ->') and value.endswith('/providers'):
                edges.append((service, value[:-10]))

    for name, child in tree.children.iteritems():
        _get_edges(child, path+'/'+name, service, edges)

def get_edges(tree):
    if isinstance(tree, basestring):
        if '\n' not in tree:
            if tree == '-':
                tree = sys.stdin.read()
            else:
                tree = open(tree).read()
        tree = zc.zk.parse_tree(tree)
    edges = []
    _get_edges(tree, '', '', edges)
    return edges

def dump_edges(edges, fname=None):
    if not isinstance(edges, list):
        edges = get_edges(edges)

    if fname and fname != '-':
        f = open(fname, 'w')
    else:
        f = sys.stdout

    f.write('digraph g {\n')
    for e in edges:
        f.write('  "%s" -> "%s";\n' % e)
    f.write('}\n')

    if fname and fname != '-':
        f.close()

if __name__ == '__main__':
    dump_edges(*sys.argv[1:])

