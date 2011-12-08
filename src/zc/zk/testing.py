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
"""Testing support

This module provides a mock of zookeeper needed to test use of zc.zk.
It's especially useful for testing packages that build on zc.zk.

It provides setUp and tearDown functions that can be used with
doctests or with regular ```unittest`` tests.
"""
import json
import mock
import sys
import threading
import time
import traceback
import zc.zk
import zc.thread
import zookeeper

__all__ = ['assert_', 'setUp', 'tearDown']

def assert_(cond, mess='', error=True):
    """A simple assertion function.

    If ``error``, raise an AssertionError if the assertion fails,
    otherwise, print a message.
    """
    if not cond:
        if error:
            raise AssertionError(mess)
        else:
            print 'assertion failed: ', mess

def wait_until(func=None, timeout=9):
    """Wait until a function returns true.

    Raise an AssertionError on timeout.
    """
    if func():
        return
    deadline = time.time()+timeout
    while not func():
        time.sleep(.01)
        if time.time() > deadline:
            raise AssertionError('timeout')

def setUp(test, tree=None, connection_string='zookeeper.example.com:2181'):
    """Set up zookeeper emulation.

    The first argument is a test case object (either doctest or unittest).

    You can optionally pass:

    tree
       An initial ZooKeeper tree expressed as an import string.
       If not passed, an initial tree will be created with examples
       used in the zc.zk doctests.

    connection_string
       The connection string to use for the emulation server. This
       defaults to 'zookeeper.example.com:2181'.
    """
    faux_zookeeper = ZooKeeper(
        connection_string, Node(zookeeper = Node('', quota=Node())))

    teardowns = []
    for name in ZooKeeper.__dict__:
        if name[0] == '_':
            continue
        cm = mock.patch('zookeeper.'+name)
        m = cm.__enter__()
        m.side_effect = getattr(faux_zookeeper, name)
        teardowns.append(cm.__exit__)

    zk = zc.zk.ZooKeeper(connection_string)
    if not tree:
        tree = """
        /fooservice
          database = '/databases/foomain'
          threads = 1
          favorite_color = 'red'
          /providers
        """
    zk.import_tree(tree)
    zk.close()

    globs = getattr(test, 'globs', test.__dict__)
    globs['wait_until'] = wait_until
    globs['zc.zk.testing'] = teardowns
    globs['ZooKeeper'] = faux_zookeeper
    globs.setdefault('assert_', assert_)

def tearDown(test):
    """The matching tearDown for setUp.

    The single argument is the test case passed to setUp.
    """
    globs = getattr(test, 'globs', test.__dict__)
    for cm in globs['zc.zk.testing']:
        cm()

class Session:

    def __init__(self, zk, handle, watch=None):
        self.zk = zk
        self.handle = handle
        self.nodes = set()
        self.add = self.nodes.add
        self.remove = self.nodes.remove
        self.watch = watch
        self.state = zookeeper.CONNECTING_STATE

    def connect(self):
        self.newstate(zookeeper.CONNECTED_STATE)

    def disconnect(self):
        self.newstate(zookeeper.CONNECTING_STATE)

    def expire(self):
        self.zk._clear_session(self)
        self.newstate(zookeeper.EXPIRED_SESSION_STATE)

    def newstate(self, state):
        self.state = state
        if self.watch is not None:
            self.watch(self.handle, zookeeper.SESSION_EVENT, state, '')

    def check(self):
        if self.state == zookeeper.CONNECTING_STATE:
            raise zookeeper.ConnectionLossException()
        elif self.state == zookeeper.EXPIRED_SESSION_STATE:
            raise zookeeper.SessionExpiredException()
        elif self.state != zookeeper.CONNECTED_STATE:
            raise AssertionError('Invalid state')

exception_codes = {
    zookeeper.ApiErrorException: zookeeper.APIERROR,
    zookeeper.AuthFailedException: zookeeper.AUTHFAILED,
    zookeeper.BadArgumentsException: zookeeper.BADARGUMENTS,
    zookeeper.BadVersionException: zookeeper.BADVERSION,
    zookeeper.ClosingException: zookeeper.CLOSING,
    zookeeper.ConnectionLossException: zookeeper.CONNECTIONLOSS,
    zookeeper.DataInconsistencyException: zookeeper.DATAINCONSISTENCY,
    zookeeper.InvalidACLException: zookeeper.INVALIDACL,
    zookeeper.InvalidCallbackException: zookeeper.INVALIDCALLBACK,
    zookeeper.InvalidStateException: zookeeper.INVALIDSTATE,
    zookeeper.MarshallingErrorException: zookeeper.MARSHALLINGERROR,
    zookeeper.NoAuthException: zookeeper.NOAUTH,
    zookeeper.NoChildrenForEphemeralsException:
    zookeeper.NOCHILDRENFOREPHEMERALS,
    zookeeper.NoNodeException: zookeeper.NONODE,
    zookeeper.NodeExistsException: zookeeper.NODEEXISTS,
    zookeeper.NotEmptyException: zookeeper.NOTEMPTY,
    zookeeper.NothingException: zookeeper.NOTHING,
    zookeeper.OperationTimeoutException: zookeeper.OPERATIONTIMEOUT,
    zookeeper.RuntimeInconsistencyException: zookeeper.RUNTIMEINCONSISTENCY,
    zookeeper.SessionExpiredException: zookeeper.SESSIONEXPIRED,
    zookeeper.SessionMovedException: zookeeper.SESSIONMOVED,
    zookeeper.SystemErrorException: zookeeper.SYSTEMERROR,
    zookeeper.UnimplementedException: zookeeper.UNIMPLEMENTED,
}

class ZooKeeper:

    def __init__(self, connection_string, tree):
        self.connection_string = connection_string
        self.root = tree
        self.sessions = {}
        self.lock = threading.RLock()
        self.connect_immediately = True

    def init(self, addr, watch=None):
        with self.lock:
            assert_(addr==self.connection_string, addr)
            handle = 0
            while handle in self.sessions:
                handle += 1
            self.sessions[handle] = Session(self, handle, watch)
            if self.connect_immediately:
                self.sessions[handle].connect()

    def _check_handle(self, handle, checkstate=True):
        try:
            session = self.sessions[handle]
        except KeyError:
            raise zookeeper.ZooKeeperException('handle out of range')
        if checkstate:
            session.check()
        return session

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

    def _clear_session(self, session):
        with self.lock:
            for path in list(session.nodes):
                self._delete(session.handle, path)
            self.root.clear_watchers(session.handle)

    def _doasync(self, completion, handle, nreturn, func, *args):
        if completion is None:
            return func(*args)

        if isinstance(nreturn, int):
            nerror = nreturn
        else:
            nreturn, nerror = nreturn

        @zc.thread.Thread
        def doasync():
            try:
                # print 'doasync', func, args
                with self.lock:
                    status = 0
                    try:
                        r = func(*args)
                    except Exception, v:
                        status = exception_codes.get(v.__class__, -1)
                        r = (None, ) * nerror
                    if not isinstance(r, tuple):
                        if nreturn == 1:
                            r = (r, )
                        else:
                            r = ()
                    completion(*((handle, status) + r))
            except:
                traceback.print_exc(file=sys.stdout)

        return 0

    def close(self, handle):
        with self.lock:
            self._clear_session(self._check_handle(handle, False))
            del self.sessions[handle]

    def state(self, handle):
        with self.lock:
            return self._check_handle(handle, False).state

    def create(self, handle, path, data, acl, flags=0):
        with self.lock:
            self._check_handle(handle)
            base, name = path.rsplit('/', 1)
            node = self._traverse(base)
            if name in node.children:
                raise zookeeper.NodeExistsException()
            node.children[name] = newnode = Node(data)
            newnode.acl = acl
            newnode.flags = flags
            node.children_changed(handle, zookeeper.CONNECTED_STATE, base)
            if flags & zookeeper.EPHEMERAL:
                self.sessions[handle].add(path)
            return path

    def acreate(self, handle, path, data, acl, flags=0, completion=None):
        return self._doasync(completion, handle, 1,
                            self.create, handle, path, data, acl, flags)

    def _delete(self, handle, path, version=-1):
        node = self._traverse(path)
        if version != -1 and node.version != version:
            raise zookeeper.BadVersionException('bad version')
        if node.children:
            raise zookeeper.NotEmptyException('not empty')
        base, name = path.rsplit('/', 1)
        bnode = self._traverse(base)
        del bnode.children[name]
        node.deleted(handle, zookeeper.CONNECTED_STATE, path)
        bnode.children_changed(handle, zookeeper.CONNECTED_STATE, base)
        if path in self.sessions[handle].nodes:
            self.sessions[handle].remove(path)

    def delete(self, handle, path, version=-1):
        with self.lock:
            self._check_handle(handle)
            self._delete(handle, path, version)

    def adelete(self, handle, path, version=-1, completion=None):
        return self._doasync(completion, handle, 0,
                             self.delete, handle, path, version)

    def exists(self, handle, path, watch=None):
        if watch is not None:
            raise TypeError('exists watch not supported')
        with self.lock:
            self._check_handle(handle)
            try:
                self._traverse(path)
                return True
            except zookeeper.NoNodeException:
                return False

    def aexists(self, handle, path, watch=None, completion=None):
        return self._doasync(completion, handle, 1,
                             self.exists, handle, path, watch)

    def get_children(self, handle, path, watch=None):
        with self.lock:
            self._check_handle(handle)
            node = self._traverse(path)
            if watch:
                node.child_watchers += ((handle, watch), )
            return sorted(node.children)

    def aget_children(self, handle, path, watch=None, completion=None):
        return self._doasync(completion, handle, 1,
                             self.get_children, handle, path, watch)

    def get(self, handle, path, watch=None):
        with self.lock:
            self._check_handle(handle)
            node = self._traverse(path)
            if watch:
                node.watchers += ((handle, watch), )
            return node.data, node.meta()

    def aget(self, handle, path, watch=None, completion=None):
        return self._doasync(completion, handle, 2,
                             self.get, handle, path, watch)

    def set(self, handle, path, data, version=-1, async=False):
        with self.lock:
            self._check_handle(handle)
            node = self._traverse(path)
            if version != -1 and node.version != version:
                raise zookeeper.BadVersionException('bad version')
            node.data = data
            node.changed(handle, zookeeper.CONNECTED_STATE, path)
            if async:
                return node.meta()
            else:
                return 0

    def aset(self, handle, path, data, version=-1, completion=None):
        return self._doasync(completion, handle, 1,
                             self.set, handle, path, data, version, True)

    def get_acl(self, handle, path):
        with self.lock:
            self._check_handle(handle)
            node = self._traverse(path)
            return node.meta(), node.acl

    def aget_acl(self, handle, path, completion=None):
        return self._doasync(completion, handle,
                             self.get_acl, handle, path)

    def set_acl(self, handle, path, aversion, acl):
        with self.lock:
            self._check_handle(handle)
            node = self._traverse(path)
            if aversion != node.aversion:
                raise zookeeper.BadVersionException("bad version")
            node.aversion += 1
            node.acl = acl

            return 0

    def aset_acl(self, handle, path, aversion, acl, completion=None):
        return self._doasync(completion, handle, (1, 0),
                             self.set_acl, handle, path, aversion, acl)

class Node:
    watchers = child_watchers = ()
    flags = 0
    version = aversion = cversion = 0
    acl = zc.zk.OPEN_ACL_UNSAFE

    def meta(self):
        return dict(
            version = self.version,
            aversion = self.aversion,
            cversion = self.cversion,
            ctime = self.ctime,
            mtime = self.mtime,
            numChildren = len(self.children),
            dataLength = len(self.data),
            ephemeralOwner=(1 if self.flags & zookeeper.EPHEMERAL else 0),
            )

    def __init__(self, data='', **children):
        self.data = data
        self.children = children
        self.ctime = self.mtime = time.time()

    def children_changed(self, handle, state, path):
        watchers = self.child_watchers
        self.child_watchers = ()
        for h, w in watchers:
            w(h, zookeeper.CHILD_EVENT, state, path)
        self.cversion += 1

    def changed(self, handle, state, path):
        watchers = self.watchers
        self.watchers = ()
        for h, w in watchers:
            w(h, zookeeper.CHANGED_EVENT, state, path)
        self.version += 1
        self.mtime = time.time()

    def deleted(self, handle, state, path):
        watchers = self.watchers
        self.watchers = ()
        for h, w in watchers:
            w(h, zookeeper.DELETED_EVENT, state, path)
        watchers = self.child_watchers
        self.watchers = ()
        for h, w in watchers:
            w(h, zookeeper.DELETED_EVENT, state, path)

    def clear_watchers(self, handle):
        self.watchers = tuple(
            (h, w) for (h, w) in self.watchers
            if h != handle
            )
        self.child_watchers = tuple(
            (h, w) for (h, w) in self.child_watchers
            if h != handle
            )
        for child in self.children.itervalues():
            child.clear_watchers(handle)
