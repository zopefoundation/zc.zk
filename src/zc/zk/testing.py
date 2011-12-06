##############################################################################
#
# Copyright (c) Zope Foundation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.0 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
import json
import mock
import time
import zc.zk
import zookeeper

def assert_(cond, mess=''):
    if not cond:
        print 'assertion failed: ', mess

def setUp(test, tree=None, connection_string='zookeeper.example.com:2181'):
    if tree:
        zk = ZooKeeper(connection_string, Node())
    else:
        zk = ZooKeeper(
            connection_string,
            Node(
                fooservice = Node(
                    json.dumps(dict(
                        database = "/databases/foomain",
                        threads = 1,
                        favorite_color= "red",
                        )),
                    providers = Node()
                    ),
                zookeeper = Node('', quota=Node()),
                ),
            )
    teardowns = []
    for name in ZooKeeper.__dict__:
        if name[0] == '_':
            continue
        cm = mock.patch('zookeeper.'+name)
        m = cm.__enter__()
        m.side_effect = getattr(zk, name)
        teardowns.append(cm.__exit__)

    if tree:
        zk = zc.zk.ZooKeeper(connection_string)
        zk.import_tree(tree)
        zk.close()

    getattr(test, 'globs', test.__dict__)['zc.zk.testing'] = teardowns

def tearDown(test):
    globs = getattr(test, 'globs', test.__dict__)
    for cm in globs['zc.zk.testing']:
        cm()

class ZooKeeper:

    def __init__(self, connection_string, tree):
        self.connection_string = connection_string
        self.root = tree
        self.sessions = set()

    def init(self, addr, watch=None):
        assert_(addr==self.connection_string, addr)
        handle = 0
        while handle in self.sessions:
            handle += 1
        self.sessions.add(handle)
        if watch:
            watch(handle,
                  zookeeper.SESSION_EVENT, zookeeper.CONNECTED_STATE, '')

    def _check_handle(self, handle):
        if handle not in self.sessions:
            raise zookeeper.ZooKeeperException('handle out of range')

    def _traverse(self, path):
        node = self.root
        for name in path.split('/')[1:]:
            if not name:
                continue
            try:
                node = node.children[name]
            except KeyError:
                raise zookeeper.NoNodeException('no node')

        return node

    def close(self, handle):
        self._check_handle(handle)
        self.sessions.remove(handle)

    def state(self, handle):
        self._check_handle(handle)
        return zookeeper.CONNECTED_STATE

    def create(self, handle, path, data, acl, flags=0):
        self._check_handle(handle)
        base, name = path.rsplit('/', 1)
        node = self._traverse(base)
        if name in node.children:
            raise zookeeper.NodeExistsException()
        node.children[name] = newnode = Node(data)
        newnode.acls = acl
        newnode.flags = flags
        node.children_changed(handle, zookeeper.CONNECTED_STATE, base)
        return path

    def delete(self, handle, path):
        self._check_handle(handle)
        node = self._traverse(path)
        base, name = path.rsplit('/', 1)
        bnode = self._traverse(base)
        del bnode.children[name]
        node.deleted(handle, zookeeper.CONNECTED_STATE, path)
        bnode.children_changed(handle, zookeeper.CONNECTED_STATE, base)

    def exists(self, handle, path):
        self._check_handle(handle)
        try:
            self._traverse(path)
            return True
        except zookeeper.NoNodeException:
            return False

    def get_children(self, handle, path, watch=None):
        self._check_handle(handle)
        node = self._traverse(path)
        if watch:
            node.child_watchers += (watch, )
        return sorted(node.children)

    def get(self, handle, path, watch=None):
        self._check_handle(handle)
        node = self._traverse(path)
        if watch:
            node.watchers += (watch, )
        return node.data, dict(
            ephemeralOwner=(1 if node.flags & zookeeper.EPHEMERAL else 0),
            )

    def set(self, handle, path, data):
        self._check_handle(handle)
        node = self._traverse(path)
        node.data = data
        node.changed(handle, zookeeper.CONNECTED_STATE, path)

    def get_acl(self, handle, path):
        self._check_handle(handle)
        node = self._traverse(path)
        return dict(aversion=node.aversion), node.acl

    def set_acl(self, handle, path, aversion, acl):
        self._check_handle(handle)
        node = self._traverse(path)
        if aversion != node.aversion:
            raise zookeeper.BadVersionException("bad version")
        node.aversion += 1
        node.acl = acl

class Node:
    watchers = child_watchers = ()
    flags = 0
    aversion = 0
    acl = zc.zk.OPEN_ACL_UNSAFE

    def __init__(self, data='', **children):
        self.data = data
        self.children = children

    def children_changed(self, handle, state, path):
        watchers = self.child_watchers
        self.child_watchers = ()
        for w in watchers:
            w(handle, zookeeper.CHILD_EVENT, state, path)

    def changed(self, handle, state, path):
        watchers = self.watchers
        self.watchers = ()
        for w in watchers:
            w(handle, zookeeper.CHANGED_EVENT, state, path)

    def deleted(self, handle, state, path):
        watchers = self.watchers
        self.watchers = ()
        for w in watchers:
            w(handle, zookeeper.DELETED_EVENT, state, path)
        watchers = self.child_watchers
        self.watchers = ()
        for w in watchers:
            w(handle, zookeeper.DELETED_EVENT, state, path)
