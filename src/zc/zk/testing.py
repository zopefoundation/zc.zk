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

def setup_tree(tree, connection_string, root, zookeeper_node=False):
    zk = zc.zk.ZooKeeper(connection_string)
    if root != '/' and zk.client.exists(root):
        zk.delete_recursive(root)
    if root != '/':
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

        @side_effect(
            setupstack.context_manager(
                test, mock.patch('kazoo.client.KazooClient')))
        def client(addr, *a, **k):
            if addr != connection_string:
                return SlowClient(addr, *a, **k)
            else:
                return SlowClient(real_zk+test_root, *a, **k)

    else:
        faux_zookeeper = ZooKeeper(connection_string, Node())
        test_root = '/'
        real_zk = connection_string

        @side_effect(setupstack.context_manager(
            test, mock.patch('kazoo.client.KazooClient')))
        def client(*a, **k):
            return Client(faux_zookeeper, *a, **k)

    setup_tree(tree, real_zk, test_root, True)

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


class Watch:

    def __init__(self, data):
        self.data = data

    func = None
    def __call__(self, func):
        if self.func is None:
            self.value = self.data()
            func(self.value)
        self.func = func

    def update(self, value):
        self.value = value
        self.func(value)

class Client:

    def __init__(self, zookeeper, hosts="127.0.0.1:2162", timeout=10.0):
        self.zookeeper = zookeeper
        self.hosts = hosts
        self.timeout = timeout
        self.listeners = []
        self.state = None

    def add_listener(self, func):
        self.listeners.append(func)

    def start(self):
        def handle(state):
            self.state = state
            for func in self.listeners:
                func(state)
        self.handle = self.zookeeper.init(self.hosts, handle, self.timeout)
        if self.state is None:
            import kazoo.handlers.threading
            raise kazoo.handlers.threading.TimeoutError('Connection time-out',)

    def create(
        self, path, value="", acl=zc.zk.OPEN_ACL_UNSAFE, ephemeral=False
        ):
        return self.zookeeper.create(self.handle, path, value, acl, ephemeral)

    def ensure_path(self, path, acl=zc.zk.OPEN_ACL_UNSAFE):
        return self.zookeeper.ensure_path(self.handle, path, acl)

    def delete(self, path):
        return self.zookeeper.delete(self.handle, path)

    def ChildrenWatch(self, path):
        node = self.zookeeper._traverse(path)
        watch = Watch(lambda : list(node.children))
        node.child_watchers += ((self.handle, watch), )
        return watch

    def DataWatch(self, path):
        watch = Watch(lambda : self.zookeeper.get_data(path))
        self.zookeeper.watchers[path] += ((self.handle, watch), )
        return watch

    def stop(self):
        self.zookeeper.close(self.handle)

    def close(self):
        del self.zookeeper
        self.state = 'LOST'

    def lose_session(self, func=None):
        session = self.zookeeper.sessions[self.handle]
        session.disconnect()
        if func is not None:
            func()
        session.expire()
        session.connect()

    def exists(self, path):
        return self.zookeeper.exists(self.handle, path)

    def get(self, path):
        return self.zookeeper.get(self.handle, path)

    def get_children(self, path):
        return self.zookeeper.get_children(self.handle, path)

    def get_acls(self, path):
        return self.zookeeper.get_acls(self.handle, path)

    def set_acls(self, path, acls, aversion=-1):
        return self.zookeeper.set_acls(self.handle, path, acls, aversion)

    def set(self, path, value, version=-1):
        return self.zookeeper.set(self.handle, path, value, version)

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
        self.newstate(kazoo.protocol.states.KazooState.LOST)

    def newstate(self, state):
        old = self.state
        self.state = state
        if self.watch is not None:
            self.watch(state)
        if (state == kazoo.protocol.states.KazooState.CONNECTED and
            old == kazoo.protocol.states.KazooState.LOST
            ):
            self.zk._restore_session(self)

    def check(self):
        if self.state == KazooState.SUSPENDED:
            raise kazoo.exceptions.SessionExpiredError()
        elif self.state == KazooState.LOST:
            raise kazoo.exceptions.SessionExpiredError()
        elif self.state != KazooState.CONNECTED:
            raise AssertionError('Invalid state')

badpath = re.compile(r'(^|/)\.\.?(/|$)').search

class ZooKeeper:

    def __init__(self, connection_string, tree):
        self.connection_strings = set([connection_string])
        self.root = tree
        self.sessions = {}
        self.lock = threading.RLock()
        self.failed = {}
        self.sequence_number = 0
        self.watchers = collections.defaultdict(tuple)

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
        >>> zk.exists('..')
        Traceback (most recent call last):
        ...
        BadArgumentsError: bad argument
        >>> zk.exists('.')
        Traceback (most recent call last):
        ...
        BadArgumentsError: bad argument
        >>> zk.get('..')
        Traceback (most recent call last):
        ...
        BadArgumentsError: bad argument
        >>> zk.get('.')
        Traceback (most recent call last):
        ...
        BadArgumentsError: bad argument


        """
        if badpath(path):
            raise kazoo.exceptions.BadArgumentsError('bad argument')
        node = self.root
        for name in path.split('/')[1:]:
            if not name:
                continue
            try:
                node = node.children[name]
            except KeyError:
                raise kazoo.exceptions.NoNodeError('no node')

        return node

    def _clear_session(self, session, close=False):
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
            self.root.clear_watchers(handle, close)
            for path in self.watchers:
                self.watchers[path] = tuple(
                    (h, w) for (h, w) in self.watchers[path]
                    if h != handle or not close
                    )
            for path in list(session.nodes):
                try:
                    self._delete(session.handle, path, clear=True)
                except kazoo.exceptions.NoNodeError:
                    pass # deleted in another session, perhaps

    def _restore_session(self, session):
        handle = session.handle
        with self.lock:
            self.root.restore_watchers(handle)
            for path in self.watchers:
                value = self.get_data(path)
                for h, w in self.watchers[path]:
                    if h == handle and value != w.value:
                        w.update(value)

    def close(self, handle):
        with self.lock:
            self._clear_session(self._check_handle(handle, False), True)
            self.sessions.pop(handle).disconnect()

    def state(self, handle):
        with self.lock:
            return self._check_handle(handle, False).state

    def create(self, handle, path, data, acl, ephemeral=False):
        if isinstance(path, str):
            path = path.decode('utf8')
        while path.endswith(u'/'):
            path = path[:-1]
        base, name = path.rsplit(u'/', 1)

        with self.lock:
            self._check_handle(handle)
            node = self._traverse(base or u'/')
            if name in node.children:
                raise kazoo.exceptions.NodeExistsError()
            node.children[name] = newnode = Node(data)
            newnode.acl = acl
            newnode.ephemeral = ephemeral
            node.children_changed(self.sessions)
            for h, w in self.watchers.get(path, ()):
                w.update(data)
            if ephemeral:
                self.sessions[handle].add(path)
            return path

    def ensure_path(self, handle, path, acl):
        if isinstance(path, str):
            path = path.decode('utf8')
        while path.endswith('/'):
            path = path[:-1]
        if not path:
            return True
        if not path.startswith('/'):
            path = '/' + path
        base, name = path.rsplit('/', 1)
        self.ensure_path(handle, base, acl)

        with self.lock:
            self._check_handle(handle)
            node = self._traverse(base or '/')
            if name in node.children:
                return True
            node.children[name] = newnode = Node('')
            newnode.acl = acl
            newnode.ephemeral = False
            node.children_changed(self.sessions)
            for h, w in self.watchers.get(path, ()):
                w.update('')
            return path

    def _delete(self, handle, path, version=-1, clear=False):
        node = self._traverse(path)
        if version != -1 and node.version != version:
            raise kazoo.exceptions.BadVersionError('bad version')
        if node.children:
            raise kazoo.exceptions.NotEmptyError('not empty')
        base, name = path.rsplit('/', 1)
        bnode = self._traverse(base or '/')
        del bnode.children[name]
        for h, w in self.watchers.get(path, ()):
            w.update(None)

        node.deleted()
        bnode.children_changed(self.sessions)
        if path in self.sessions[handle].nodes:
            self.sessions[handle].remove(path)

    def delete(self, handle, path, version=-1):
        with self.lock:
            self._check_handle(handle)
            self._delete(handle, path, version)
        return 0

    def exists(self, handle, path):
        """Test whether a node exists:

        >>> zk = zc.zk.ZK('zookeeper.example.com:2181')
        >>> zk.exists('/test_exists')

        When a node exists, exists retirnes it's meta data, which is
        the same as the second result from get:

        >>> _ = zk.create('/test_exists')
        >>> zk.exists('/test_exists') == zk.get('/test_exists')[1]
        True

        >>> zk.close()
        """
        with self.lock:
            self._check_handle(handle)
            try:
                node = self._traverse(path)
                return node
            except kazoo.exceptions.NoNodeError:
                return None

    def get_children(self, handle, path):
        with self.lock:
            self._check_handle(handle)
            node = self._traverse(path)
            return list(node.children)

    def get(self, handle, path):
        with self.lock:
            self._check_handle(handle)
            node = self._traverse(path)
            return node.data, node

    def recv_timeout(self, handle):
        with self.lock:
            return self._check_handle(handle, False).session_timeout

    def set(self, handle, path, data, version=-1):
        with self.lock:
            self._check_handle(handle)
            node = self._traverse(path)
            if version != -1 and node.version != version:
                raise kazoo.exceptions.BadVersionError('bad version')
            node.data = data
            for h, w in self.watchers.get(path, ()):
                w.update(data)
            return True

    def set_watcher(self, handle, watch):
        with self.lock:
            self._check_handle(handle).watch = watch

    def get_acls(self, handle, path):
        with self.lock:
            self._check_handle(handle)
            node = self._traverse(path)
            return node.acl, node

    def set_acls(self, handle, path, acl, aversion):
        with self.lock:
            self._check_handle(handle)
            node = self._traverse(path)
            if aversion != -1 and aversion != node.aversion:
                raise kazoo.exceptions.BadVersionError("bad version")
            node.aversion += 1
            node.acl = acl

            return True

    def get_data(self, path):
        try:
            return self._traverse(path).data
        except kazoo.exceptions.NoNodeError:
            return None

class Node:
    child_watchers = ()
    version = aversion = cversion = 0
    acl = zc.zk.OPEN_ACL_UNSAFE
    ephemeral = False

    @property
    def numChildren(self):
        return len(self.children)

    @property
    def dataLength(self):
        return len(self.data)

    @property
    def ephemeralOwner(self):
        return self.ephemeral

    def __init__(self, data='', **children):
        self.data = data
        self.children = children
        self.ctime = self.mtime = time.time()

    def children_changed(self, sessions):
        value = list(self.children)
        for h, w in self.child_watchers:
            if sessions[h].state == kazoo.protocol.states.KazooState.CONNECTED:
                w.update(value)
        self.cversion += 1

    def changed(self):
        for w in self.watchers:
            w.func(self.data)
        self.version += 1
        self.mtime = time.time()

    def deleted(self):
        self.child_watchers = ()

    def clear_watchers(self, handle, close=False):
        self.child_watchers = tuple(
            (h, w) for (h, w) in self.child_watchers
            if h != handle or not close
            )
        for child in self.children.values():
            child.clear_watchers(handle, close)

    def restore_watchers(self, handle):
        value = list(self.children)
        for h, w in self.child_watchers:
            if h == handle and value != w.value:
                w.update(value)

        for child in self.children.values():
            child.restore_watchers(handle)
