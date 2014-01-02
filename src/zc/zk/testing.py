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
from zope.testing import setupstack
from kazoo.protocol.states import KazooState
import collections
import json
import kazoo.client
import kazoo.protocol.states
import mock
import os
import random
import re
import sys
import threading
import time
import traceback
import zc.zk
import zc.thread

__all__ = ['assert_', 'setUp', 'tearDown', 'testing_with_real_zookeeper']

def side_effect(mock):
    return lambda func: setattr(mock, 'side_effect', func)

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
    import warnings
    warnings.warn("wait_until is deprecated. Use zope.testing.wait.wait",
                  DeprecationWarning, 2)

    if func():
        return
    deadline = time.time()+timeout
    while not func():
        time.sleep(.01)
        if time.time() > deadline:
            raise AssertionError('timeout')

def setup_tree(tree, connection_string, root='/test-root',
               zookeeper_node=False):
    zk = zc.zk.ZooKeeper(connection_string)
    if zk.client.exists(root):
        zk.delete_recursive(root)
    zk.client.create(root)
    zk.import_tree(tree or """
    /fooservice
      /providers
      database = '/databases/foomain'
      threads = 1
      favorite_color = 'red'
    """, root)

    if zookeeper_node:
        zk.import_tree("""
        /zookeeper
          /quota
        """, root)

    zk.close()

def testing_with_real_zookeeper():
    """Test whether we're testing with a real ZooKeeper server.

    The real connection string is returned.
    """
    return os.environ.get('TEST_ZOOKEEPER_CONNECTION')

class SlowClient(kazoo.client.KazooClient):

    __test_sleep = float(os.environ.get('TEST_ZOOKEEPER_SLEEP', 0.01))

    def create(self, *a, **k):
        try:
            return super(SlowClient, self).create(*a, **k)
        finally:
            time.sleep(self.__test_sleep)

    def delete(self, *a, **k):
        try:
            return super(SlowClient, self).delete(*a, **k)
        finally:
            time.sleep(self.__test_sleep)

    def set(self, *a, **k):
        try:
            return super(SlowClient, self).set(*a, **k)
        finally:
            time.sleep(self.__test_sleep)

def setUp(test, tree=None, connection_string='zookeeper.example.com:2181'):
    """Set up zookeeper emulation.

    Standard (mock) testing
    -----------------------

    The first argument is a test case object (either doctest or unittest).

    You can optionally pass:

    tree
       An initial ZooKeeper tree expressed as an import string.
       If not passed, an initial tree will be created with examples
       used in the zc.zk doctests.

    connection_string
       The connection string to use for the emulation server. This
       defaults to 'zookeeper.example.com:2181'.

    Testing with a real ZooKeeper Server
    ------------------------------------

    You can test against a real ZooKeeper server, instead of a mock by
    setting the environment variable TEST_ZOOKEEPER_CONNECTION to the
    connection string of a test server.

    The tests will create a top-level node with a random name that
    starts with 'zc.zk.testing.test-root', and use that as the virtual
    root for your tests.  Although this is the virtual root, of the
    zookeeper tree in your tests, the presense of the node may be
    shown in your tests. In particularm ``zookeeper.create`` returns
    the path created and the string returned is real, not virtual.
    This node is cleaned up by the ``tearDown``.

    A doctest can determine if it's running with a stub ZooKeeper by
    checking whether the value of the ZooKeeper gloval variable is None.
    A regular unit test can check the ZooKeeper test attribute.
    """

    globs = setupstack.globs(test)
    faux_zookeeper = None
    real_zk = testing_with_real_zookeeper()
    if real_zk:
        test_root = '/zc.zk.testing.test-root%s' % random.randint(0, sys.maxint)
        globs['/zc.zk.testing.test-root'] = test_root
        setup_tree(tree, real_zk, test_root, True)

        @side_effect(
            setupstack.context_manager(
                test, mock.patch('kazoo.client.KazooClient')))
        def client(addr, *a, **k):
            if addr != connection_string:
                return SlowClient(addr, *a, **kw)
            else:
                return SlowClient(real_zk+test_root, *a, **k)

    else:
        if tree:
            faux_zookeeper = ZooKeeper(connection_string, Node())
        else:
            faux_zookeeper = ZooKeeper(
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

        @side_effect(setupstack.context_manager(
            test, mock.patch('kazoo.client.KazooClient')))
        def client(*a, **k):
            return Client(faux_zookeeper, *a, **k)

        if tree:
            zk = zc.zk.ZooKeeper(connection_string)
            zk.import_tree(tree)
            zk.close()

    globs['wait_until'] = wait_until # BBB
    globs['ZooKeeper'] = faux_zookeeper
    globs.setdefault('assert_', assert_)

def tearDown(test):
    """The matching tearDown for setUp.

    The single argument is the test case passed to setUp.
    """
    setupstack.tearDown(test)
    real_zk = testing_with_real_zookeeper()
    if real_zk:
        zk = zc.zk.ZooKeeper(real_zk)
        root = setupstack.globs(test)['/zc.zk.testing.test-root']
        if zk.exists(root):
            zk.delete_recursive(root)
        zk.close()


class Session:

    def __init__(self, zk, handle, watch=None, session_timeout=None):
        self.zk = zk
        self.handle = handle
        self.nodes = set() # ephemeral nodes
        self.add = self.nodes.add
        self.remove = self.nodes.remove
        self.watch = watch
        self.state = kazoo.protocol.states.KazooState.LOST
        self.session_timeout = session_timeout

    def connect(self):
        self.newstate(kazoo.protocol.states.KazooState.CONNECTED)

    def disconnect(self):
        self.newstate(kazoo.protocol.states.KazooState.SUSPENDED)

    def expire(self):
        self.zk._clear_session(self)
        self.newstate(kazoo.protocol.states.KazooState.EXPIRED)

    def newstate(self, state):
        self.state = state
        if self.watch is not None:
            self.watch(state)
        self.zk._session_event(self.handle, state)

    def check(self):
        if self.state == KazooState.SUSPENDED:
            raise kazoo.exceptions.SessionExpiredError()
        elif self.state == KazooState.Lost:
            raise kazoo.exceptions.SessionExpiredError()
        elif self.state != KazooState.CONNECTED:
            raise AssertionError('Invalid state')

badpath = re.compile(r'(^([^/]|$))|(/\.\.?(/|$))|(./$)').search

class Client:

    def __init__(self, zookeeper, hosts, timeout):
        self.zookeeper = zookeeper
        self.hosts = hosts
        self.timeout = timeout
        self.listeners = []
        self.state = kazoo.protocol.states.KazooState.LOST

    def add_listener(self, func):
        self.listeners.append(func)

    def start(self):
        def handle(state):
            self.state = state
            for func in self.listeners:
                func(state)
        self.handle = self.zookeeper.init(self.hosts, handle, self.timeout)

class ZooKeeper:

    def __init__(self, connection_string, tree):
        self.connection_strings = set([connection_string])
        self.root = tree
        self.sessions = {}
        self.lock = threading.RLock()
        self.failed = {}
        self.sequence_number = 0
        self.exists_watchers = collections.defaultdict(tuple)

    def init(self, addr, watch=None, session_timeout=4000):
        with self.lock:
            handle = 0
            while handle in self.sessions:
                handle += 1
            self.sessions[handle] = Session(
                self, handle, watch, session_timeout)
            if addr in self.connection_strings:
                self.sessions[handle].connect()
            else:
                self.failed.setdefault(addr, set()).add(handle)
            return handle

    def _allow_connection(self, connection_string):
        self.connection_strings.add(connection_string)
        for handle in self.failed.pop(connection_string, ()):
            if handle in self.sessions:
                self.sessions[handle].connect()

    def _check_handle(self, handle, checkstate=True):
        try:
            session = self.sessions[handle]
        except KeyError:
            raise kazoo.exceptions.ZooKeeperError('handle out of range')
        if checkstate:
            session.check()
        return session

    def _traverse(self, path):
        """This is used by a bunch of the methods.

        We'll test som edge cases here.

        We error on bad paths:

        >>> zk = zc.zk.ZK('zookeeper.example.com:2181')

        >>> zk.exists('')
        Traceback (most recent call last):
        ...
        BadArgumentsException: bad argument
        >>> zk.exists('xxx')
        Traceback (most recent call last):
        ...
        BadArgumentsException: bad argument
        >>> zk.exists('..')
        Traceback (most recent call last):
        ...
        BadArgumentsException: bad argument
        >>> zk.exists('.')
        Traceback (most recent call last):
        ...
        BadArgumentsException: bad argument

        >>> zk.get('')
        Traceback (most recent call last):
        ...
        BadArgumentsException: bad argument
        >>> zk.get('xxx')
        Traceback (most recent call last):
        ...
        BadArgumentsException: bad argument
        >>> zk.get('..')
        Traceback (most recent call last):
        ...
        BadArgumentsException: bad argument
        >>> zk.get('.')
        Traceback (most recent call last):
        ...
        BadArgumentsException: bad argument


        """
        if badpath(path):
            raise kazoo.exceptions.BadArgumentError('bad argument')
        node = self.root
        for name in path.split('/')[1:]:
            if not name:
                continue
            try:
                node = node.children[name]
            except KeyError:
                raise kazoo.exceptions.NoNodeError('no node')

        return node

    def _session_event(self, handle, state):
        with self.lock:
            for path, watchers in self.exists_watchers.items():
                for h, w in watchers:
                    if h == handle:
                        w(h, zookeeper.SESSION_EVENT, state, '')
            self.root.session_event(handle, state)


    def _clear_session(self, session):
        """
        Test: don't sweat ephemeral nodes that were already deleted

        >>> zk = zc.zk.ZK('zookeeper.example.com:2181')
        >>> zk.register('/fooservice/providers', 'a:b')

        >>> zk2 = zc.zk.ZK('zookeeper.example.com:2181')
        >>> zk2.delete_recursive('/fooservice', force=True)
        >>> zk2.close()

        >>> zk.close()
        """
        handle = session.handle
        with self.lock:
            self.root.clear_watchers(handle)
            for path in self.exists_watchers:
                self.exists_watchers[path] = tuple(
                    (h, w) for (h, w) in self.exists_watchers[path]
                    if h != handle
                    )
            for path in list(session.nodes):
                try:
                    self._delete(session.handle, path, clear=True)
                except zookeeper.NoNodeException:
                    pass # deleted in another session, perhaps

    def close(self, handle):
        with self.lock:
            self._clear_session(self._check_handle(handle, False))
            self.sessions.pop(handle).disconnect()

    def state(self, handle):
        with self.lock:
            return self._check_handle(handle, False).state

    def create(self, handle, path, data, acl, flags=0):
        with self.lock:
            self._check_handle(handle)
            base, name = path.rsplit('/', 1)
            if flags & zookeeper.SEQUENCE:
                self.sequence_number += 1
                name += "%.10d" % self.sequence_number
                path = base + '/' + name
            if base.endswith('/'):
                raise zookeeper.BadArgumentsException('bad arguments')
            node = self._traverse(base or '/')
            for p in node.acl:
                if not (p['perms'] & zookeeper.PERM_CREATE):
                    raise zookeeper.NoAuthException('not authenticated')
            if name in node.children:
                raise zookeeper.NodeExistsException()
            node.children[name] = newnode = Node(data)
            newnode.acl = acl
            newnode.flags = flags
            node.children_changed(handle, zookeeper.CONNECTED_STATE, base)

            for h, w in self.exists_watchers.pop(path, ()):
                w(h, zookeeper.CREATED_EVENT, zookeeper.CONNECTED_STATE, path)

            if flags & zookeeper.EPHEMERAL:
                self.sessions[handle].add(path)
            return path

    def _delete(self, handle, path, version=-1, clear=False):
        node = self._traverse(path)
        if version != -1 and node.version != version:
            raise zookeeper.BadVersionException('bad version')
        if node.children:
            raise zookeeper.NotEmptyException('not empty')
        base, name = path.rsplit('/', 1)
        bnode = self._traverse(base or '/')
        if not clear:
            for p in bnode.acl:
                if not (p['perms'] & zookeeper.PERM_DELETE):
                    raise zookeeper.NoAuthException('not authenticated', path)
        del bnode.children[name]
        node.deleted(handle, zookeeper.CONNECTED_STATE, path)
        bnode.children_changed(handle, zookeeper.CONNECTED_STATE, base)
        if path in self.sessions[handle].nodes:
            self.sessions[handle].remove(path)

    def delete(self, handle, path, version=-1):
        with self.lock:
            self._check_handle(handle)
            self._delete(handle, path, version)
        return 0

    def exists(self, handle, path, watch=None):
        """Test whether a node exists:

        >>> zk = zc.zk.ZK('zookeeper.example.com:2181')
        >>> zk.exists('/test_exists')

        We can set watches:

        >>> def watch(*args):
        ...     print args

        >>> zk.exists('/test_exists', watch)
        >>> _ = zk.create('/test_exists', '', zc.zk.OPEN_ACL_UNSAFE)
        (0, 1, 3, '/test_exists')

        When a node exists, exists retirnes it's meta data, which is
        the same as the second result from get:

        >>> zk.exists('/test_exists') == zk.get('/test_exists')[1]
        True

        We can set watches on nodes that exist, too:

        >>> zk.exists('/test_exists', watch) == zk.get('/test_exists')[1]
        True

        >>> _ = zk.delete('/test_exists')
        (0, 2, 3, '/test_exists')

        Watches are one-time:

        >>> _ = zk.create('/test_exists', '', zc.zk.OPEN_ACL_UNSAFE)
        >>> _ = zk.delete('/test_exists')

        >>> zk.close()
        """
        with self.lock:
            self._check_handle(handle)
            try:
                node = self._traverse(path)
                if watch:
                    node.exists_watchers += ((handle, watch), )
                return node.meta()
            except zookeeper.NoNodeException:
                if watch:
                    self.exists_watchers[path] += ((handle, watch), )
                return None

    def get_children(self, handle, path, watch=None):
        with self.lock:
            self._check_handle(handle)
            node = self._traverse(path)
            for p in node.acl:
                if not (p['perms'] & zookeeper.PERM_READ):
                    raise zookeeper.NoAuthException('not authenticated')
            if watch:
                node.child_watchers += ((handle, watch), )
            return list(node.children)

    def get(self, handle, path, watch=None):
        with self.lock:
            self._check_handle(handle)
            node = self._traverse(path)
            for p in node.acl:
                if not (p['perms'] & zookeeper.PERM_READ):
                    raise zookeeper.NoAuthException('not authenticated')
            if watch:
                node.watchers += ((handle, watch), )
            return node.data, node.meta()

    def set(self, handle, path, data, version=-1, async=False):
        with self.lock:
            self._check_handle(handle)
            node = self._traverse(path)
            for p in node.acl:
                if not (p['perms'] & zookeeper.PERM_WRITE):
                    raise zookeeper.NoAuthException('not authenticated')
            if version != -1 and node.version != version:
                raise zookeeper.BadVersionException('bad version')
            node.data = data
            node.changed(handle, zookeeper.CONNECTED_STATE, path)
            if async:
                return node.meta()
            else:
                return 0

    def set_watcher(self, handle, watch):
        with self.lock:
            self._check_handle(handle).watch = watch

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
            for p in node.acl:
                if not (p['perms'] & zookeeper.PERM_ADMIN):
                    raise zookeeper.NoAuthException('not authenticated', path)
            if aversion != node.aversion:
                raise zookeeper.BadVersionException("bad version")
            node.aversion += 1
            node.acl = acl

            return 0

class Node:
    watchers = child_watchers = exists_watchers = ()
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
        watchers = self.exists_watchers
        self.exists_watchers = ()
        for h, w in watchers:
            w(h, zookeeper.DELETED_EVENT, state, path)
        watchers = self.child_watchers
        self.watchers = ()
        for h, w in watchers:
            w(h, zookeeper.DELETED_EVENT, state, path)

    def session_event(self, handle, state):
        for (h, w) in self.watchers:
            if h == handle:
                w(h, zookeeper.SESSION_EVENT, state, '')
        for (h, w) in self.child_watchers:
            if h == handle:
                w(h, zookeeper.SESSION_EVENT, state, '')
        for (h, w) in self.exists_watchers:
            if h == handle:
                w(h, zookeeper.SESSION_EVENT, state, '')
        for child in self.children.values():
            child.session_event(handle, state)

    def clear_watchers(self, handle):
        self.watchers = tuple(
            (h, w) for (h, w) in self.watchers
            if h != handle
            )
        self.child_watchers = tuple(
            (h, w) for (h, w) in self.child_watchers
            if h != handle
            )
        self.exists_watchers = tuple(
            (h, w) for (h, w) in self.exists_watchers
            if h != handle
            )
        for name, child in self.children.items():
            child.clear_watchers(handle)
