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
import doctest
import json
import logging
import manuel.capture
import manuel.doctest
import manuel.testing
import mock
import os
import pprint
import re
import StringIO
import time
import zc.zk
import zc.thread
import zookeeper
import zope.testing.loggingsupport
import zope.testing.setupstack
import zope.testing.renormalizing
import unittest

def wait_until(func, timeout=9):
    if func():
        return
    deadline = time.time()+timeout
    while not func():
        time.sleep(.01)
        if time.time() > deadline:
            raise AssertionError('timeout')

class LoggingTests(unittest.TestCase):

    def test_logging(self):
        logger = logging.getLogger('ZooKeeper')
        f = StringIO.StringIO()
        h = logging.StreamHandler(f)
        logger.addHandler(h)
        logger.setLevel(logging.DEBUG)
        try:
            handle = zookeeper.init('zookeeper.example.com:2181')
            zookeeper.close(handle)
        except:
            pass
        wait_until(lambda : 'environment' in f.getvalue())
        logger.setLevel(logging.NOTSET)
        logger.removeHandler(h)

def side_effect(mock):
    return lambda func: setattr(mock, 'side_effect', func)

class Tests(unittest.TestCase):

    @mock.patch('zookeeper.init')
    def setUp(self, init):
        @zc.thread.Thread
        def getzk():
            zk = zc.zk.ZooKeeper()
            return zk

        wait_until(lambda : init.call_args)
        (zkaddr, self.__session_watcher), kw = init.call_args
        self.assertEqual((zkaddr, kw), ('127.0.0.1:2181', {}))
        self.__session_watcher(
            0, zookeeper.SESSION_EVENT, zookeeper.CONNECTED_STATE, '')
        getzk.join(1)
        self.__zk = getzk.value
        self.assertEqual(self.__zk.handle, 0)

        self.__teardowns = []
        cm = mock.patch('zookeeper.exists')
        @side_effect(cm.__enter__())
        def exists(handle, path):
            return True

    def tearDown(self):
        while self.__teardowns:
            self.__teardowns.pop()()

    def state_side_effect(self, handle):
        self.assertEqual(handle, self.__zk.handle)
        return zookeeper.CONNECTED_STATE

    @mock.patch('zookeeper.close')
    def test_close(self, close):
        self.__zk.close()
        close.assert_called_with(0)
        self.assertEqual(self.__zk.handle, None)

    @mock.patch('zookeeper.create')
    def test_register_server(self, create):
        @side_effect(create)
        def _(handle, path_, data, acl, flags):
            self.assertEqual((handle, path_), (0, '/foo/127.0.0.1:8080'))
            self.assertEqual(json.loads(data), dict(pid=os.getpid(), a=1))
            self.assertEqual(acl, [zc.zk.world_permission()])
            self.assertEqual(flags, zookeeper.EPHEMERAL)

        self.__zk.register_server('/foo', ('127.0.0.1', 8080), a=1)

    @mock.patch('zookeeper.close')
    @mock.patch('zookeeper.init')
    @mock.patch('zookeeper.state')
    @mock.patch('zookeeper.get_children')
    def test_children(self, get_children, state, init, close):
        state.side_effect = self.state_side_effect

        path = '/test'
        @side_effect(get_children)
        def _(handle, path_, handler):
            self.__handler = handler
            self.assertEqual((handle, path_), (0, path))
            return data

        # Get the data the first time
        data = []
        children = self.__zk.children(path)
        self.assertEqual(list(children), data)

        # When tree updates, children are updated
        data = ['a']
        self.__handler(0, zookeeper.CHILD_EVENT, zookeeper.CONNECTED_STATE,
                       path)
        self.assertEqual(list(children), data)

        # callbacks are called too:
        cb = children(mock.Mock())
        cb.assert_called_with(children)
        cb.reset_mock()
        self.assertEqual(len(children.callbacks), 1)
        data = ['a', 'b']
        self.__handler(0, zookeeper.CHILD_EVENT, zookeeper.CONNECTED_STATE,
                       path)
        self.assertEqual(list(children), data)
        cb.assert_called_with(children)

        # if a callback raises an exception, the exception is logged
        # and callback is discarded
        h = zope.testing.loggingsupport.Handler('zc.zk', level=logging.DEBUG)
        h.install()
        cb.side_effect = ValueError
        data = ['a']
        self.__handler(0, zookeeper.CHILD_EVENT, zookeeper.CONNECTED_STATE,
                       path)
        self.assertEqual(list(children), data)
        self.assertEqual(len(children.callbacks), 0)
        self.assertEqual(h.records[0].name, 'zc.zk')
        self.assertEqual(h.records[0].levelno, logging.ERROR)
        h.clear()

        # if a callback raises zc.zk.CancelWatch, the cancel is logged
        # and callback is discarded
        cb = children(mock.Mock())
        self.assertEqual(len(children.callbacks), 1)
        cb.side_effect = zc.zk.CancelWatch
        data = []
        self.__handler(0, zookeeper.CHILD_EVENT, zookeeper.CONNECTED_STATE,
                       path)
        self.assertEqual(list(children), data)
        self.assertEqual(len(children.callbacks), 0)
        self.assertEqual(h.records[0].name, 'zc.zk')
        self.assertEqual(h.records[0].levelno, logging.DEBUG)
        h.clear()

        h.uninstall()

        # If a session expires, it will be reestablished with watches intact.
        cb = children(mock.Mock())
        self.__session_watcher(
            0, zookeeper.SESSION_EVENT, zookeeper.EXPIRED_SESSION_STATE, "")
        close.assert_called_with(0)
        self.assertEqual(self.__zk.handle, None)
        data = ['test']
        self.__session_watcher(
            0, zookeeper.SESSION_EVENT, zookeeper.CONNECTED_STATE, "")
        self.assertEqual(list(children), data)
        cb.assert_called_with(children)


    @mock.patch('zookeeper.close')
    @mock.patch('zookeeper.init')
    @mock.patch('zookeeper.state')
    @mock.patch('zookeeper.get')
    def test_get_properties(self, get, state, init, close):
        state.side_effect = self.state_side_effect

        path = '/test'
        @side_effect(get)
        def _(handle, path_, handler):
            self.__handler = handler
            self.assertEqual((handle, path_), (0, path))
            return json.dumps(data), {}

        # Get the data the first time
        data = {}
        properties = self.__zk.properties(path)
        self.assertEqual(dict(properties), data)

        # When node updates, properties are updated
        data = dict(a=1)
        self.__handler(0, zookeeper.CHANGED_EVENT, zookeeper.CONNECTED_STATE,
                     path)
        self.assertEqual(dict(properties), data)

        # callbacks are called too:
        cb = properties(mock.Mock())
        cb.assert_called_with(properties)
        cb.reset_mock()
        self.assertEqual(len(properties.callbacks), 1)
        data = dict(a=1, b=2)
        self.__handler(0, zookeeper.CHANGED_EVENT, zookeeper.CONNECTED_STATE,
                     path)
        self.assertEqual(dict(properties), data)
        cb.assert_called_with(properties)

        # if a callback raises an exception, the exception is logged
        # and callback is discarded
        h = zope.testing.loggingsupport.Handler('zc.zk', level=logging.DEBUG)
        h.install()
        cb.side_effect = ValueError
        data = dict(a=1)
        self.__handler(0, zookeeper.CHANGED_EVENT, zookeeper.CONNECTED_STATE,
                     path)
        self.assertEqual(dict(properties), data)
        self.assertEqual(len(properties.callbacks), 0)
        self.assertEqual(h.records[0].name, 'zc.zk')
        self.assertEqual(h.records[0].levelno, logging.ERROR)
        h.clear()

        # if a callback raises zc.zk.CancelWatch, the cancel is logged
        # and callback is discarded
        cb = properties(mock.Mock())
        self.assertEqual(len(properties.callbacks), 1)
        cb.side_effect = zc.zk.CancelWatch
        data = {}
        self.__handler(0, zookeeper.CHANGED_EVENT, zookeeper.CONNECTED_STATE,
                     path)
        self.assertEqual(dict(properties), data)
        self.assertEqual(len(properties.callbacks), 0)
        self.assertEqual(h.records[0].name, 'zc.zk')
        self.assertEqual(h.records[0].levelno, logging.DEBUG)
        h.clear()

        h.uninstall()

        # If a session expires, it will be reestablished with watches intact.
        cb = properties(mock.Mock())
        self.__session_watcher(
            0, zookeeper.SESSION_EVENT, zookeeper.EXPIRED_SESSION_STATE, "")
        close.assert_called_with(0)
        self.assertEqual(self.__zk.handle, None)
        data = dict(test=1)
        self.__session_watcher(
            0, zookeeper.SESSION_EVENT, zookeeper.CONNECTED_STATE, "")
        self.assertEqual(dict(properties), data)
        cb.assert_called_with(properties)

    @mock.patch('zookeeper.state')
    @mock.patch('zookeeper.get')
    @mock.patch('zookeeper.set')
    def test_set_properties(self, set, get, state):
        state.side_effect = self.state_side_effect

        path = '/test'
        @side_effect(get)
        def _(handle, path_, handler):
            self.__handler = handler
            self.assertEqual((handle, path_), (0, path))
            return json.dumps(data), {}

        data = dict(a=1)
        properties = self.__zk.properties(path)
        self.assertEqual(dict(properties), data)

        @side_effect(set)
        def _(handle, path_, data):
            self.__set_data = json.loads(data)
            self.assertEqual((handle, path_), (0, path))

        properties.update(b=2)
        self.assertEqual(self.__set_data, dict(a=1, b=2))
        self.assertEqual(dict(properties), self.__set_data)

        properties.set(c=3)
        self.assertEqual(self.__set_data, dict(c=3))
        self.assertEqual(dict(properties), self.__set_data)

    @mock.patch('zookeeper.state')
    @mock.patch('zookeeper.get')
    @mock.patch('zookeeper.set')
    def test_special_values(self, set, get, state):
        state.side_effect = self.state_side_effect

        path = '/test'
        @side_effect(get)
        def _(handle, path_, handler):
            self.__handler = handler
            self.assertEqual((handle, path_), (0, path))
            return data, {}

        data = ''
        properties = self.__zk.properties(path)
        self.assertEqual(dict(properties), {})

        data = 'xxx'
        properties = self.__zk.properties(path)
        self.assertEqual(dict(properties), dict(string_value='xxx'))

        data = '{xxx}'
        properties = self.__zk.properties(path)
        self.assertEqual(dict(properties), dict(string_value='{xxx}'))

        data = '\n{xxx}\n'
        properties = self.__zk.properties(path)
        self.assertEqual(dict(properties), dict(string_value='\n{xxx}\n'))

        @side_effect(set)
        def _(handle, path_, data):
            self.__set_data = data
            self.assertEqual((handle, path_), (0, path))

        properties.set(b=2)
        self.assertEqual(self.__set_data, '{"b":2}')
        properties.set()
        self.assertEqual(self.__set_data, '')
        properties.set(string_value='xxx')
        self.assertEqual(self.__set_data, 'xxx')

    @mock.patch('zookeeper.state')
    @mock.patch('zookeeper.get')
    @mock.patch('zookeeper.get_children')
    def test_deleted_node_with_watchers(self, get_children, get, state):
        state.side_effect = self.state_side_effect
        path = '/test'
        @side_effect(get)
        def _(handle, path_, handler):
            self.__get_handler = handler
            return '{"a": 1}', {}
        @side_effect(get_children)
        def _(handle, path_, handler):
            self.__child_handler = handler
            return ['x']

        children = self.__zk.children(path)
        self.assertEqual(list(children), ['x'])
        cb = children(mock.Mock())
        cb.side_effect = lambda x: None
        ccb = children(mock.Mock())
        ccb.assert_called_with(children)

        properties = self.__zk.properties(path)
        self.assertEqual(dict(properties), dict(a=1))
        cb = properties(mock.Mock())
        cb.side_effect = lambda x: None
        pcb = properties(mock.Mock())
        pcb.assert_called_with(properties)

        self.__get_handler(
            0, zookeeper.DELETED_EVENT, zookeeper.CONNECTED_STATE, path)
        self.assertEqual(dict(properties), {})
        pcb.assert_called_with()

        self.__child_handler(
            0, zookeeper.DELETED_EVENT, zookeeper.CONNECTED_STATE, path)
        self.assertEqual(list(children), [])
        ccb.assert_called_with()

def resilient_import():
    """
We can use vatious spacing in properties and links:

    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.import_tree('''
    ... /test
    ...   a=1
    ...   b      =1
    ...   c=      1
    ...   ad->/x
    ...   af          ->/x
    ...   ae->         /x
    ... ''')

    >>> print zk.export_tree('/test'),
    /test
      a = 1
      b = 1
      c = 1
      ad -> /x
      ae -> /x
      af -> /x

When an expression is messed up, we get sane errors:

    >>> zk.import_tree('''
    ... /test
    ...   a= 1+
    ... ''') # doctest: +NORMALIZE_WHITESPACE
    Traceback (most recent call last):
    ...
    ValueError: Error unexpected EOF while parsing (<string>, line 1)
    in expression: '1+'

    >>> zk.import_tree('''
    ... /test
    ...   a ->
    ... ''') # doctest: +NORMALIZE_WHITESPACE
    Traceback (most recent call last):
    ...
    ValueError: (3, 'a ->', 'Bad link format')

    >>> zk.import_tree('''
    ... /test
    ...   a -> 1
    ... ''') # doctest: +NORMALIZE_WHITESPACE
    Traceback (most recent call last):
    ValueError: (3, 'a -> 1', 'Bad link format')
    """

def import_dry_run():
    """

    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.import_tree('''
    ... /test
    ...   a=1
    ...   b = 2
    ...   /c1
    ...     /c12
    ...   /c2
    ...   ae->         /x
    ...   ad->         /y
    ... ''')

    >>> zk.import_tree('''
    ... /test
    ...   a=2
    ...   /c1
    ...     /c12
    ...       a = 1
    ...       b -> /b
    ...       /c123
    ...   ae->         /z
    ... ''', dry_run=True)
    /test a change from 1 to 2
    /test remove link ad -> /y
    /test ae link change from /x to /z
    /test remove property b = 2
    extra path not trimmed: /test/c2
    /test/c1/c12 add property a = 1
    /test/c1/c12 add link b -> /b
    add /test/c1/c12/c123

    >>> print zk.export_tree('/test'),
    /test
      a = 1
      b = 2
      ad -> /y
      ae -> /x
      /c1
        /c12
      /c2

    """

def property_set_and_update_variations():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> data = zk.properties('/fooservice')
    >>> @data
    ... def _(data):
    ...     pprint.pprint(dict(data), width=70)
    {u'database': u'/databases/foomain',
     u'favorite_color': u'red',
     u'threads': 1}

    >>> data.set(dict(x=1))
    {u'x': 1}
    >>> data.set(dict(x=1), x=2, y=3)
    {u'x': 2, u'y': 3}
    >>> data.set(z=1)
    {u'z': 1}
    >>> data.update(a=1)
    {u'a': 1, u'z': 1}
    >>> data.update(dict(b=1), a=2)
    {u'a': 2, u'b': 1, u'z': 1}
    >>> data.update(dict(c=1))
    {u'a': 2, u'b': 1, u'c': 1, u'z': 1}
    >>> data.update(dict(d=1), d=2)
    {u'a': 2, u'b': 1, u'c': 1, u'd': 2, u'z': 1}
    """

def test_resolve():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.import_tree('''
    ... /top
    ...  /a
    ...    top -> /top
    ...    loop -> /top/a/b/loop
    ...    /b
    ...      top -> /top
    ...      loop -> /top/a/loop
    ...      /c
    ...        top -> /top
    ...        /d
    ...          name = 'd'
    ...          /e
    ...          top -> /top
    ...          loop -> /top/a/b/c/d/loop
    ...
    ... ''')


    >>> zk.resolve('/top/a/b/c/d')
    '/top/a/b/c/d'

    >>> zk.resolve('/top/a/top/a/b/top/a/b/c/top/a/b/c/d')
    u'/top/a/b/c/d'

    >>> sorted(zk.properties('/top/a/top/a/b/top/a/b/c/top/a/b/c/d').items())
    [(u'loop ->', u'/top/a/b/c/d/loop'), (u'name', u'd'), (u'top ->', u'/top')]

    >>> zk.register_server('/top/a/top/a/b/top/a/b/c/top/a/b/c/d', 'addr')
    >>> sorted(zk.children('/top/a/top/a/b/top/a/b/c/top/a/b/c/d'))
    [u'addr', 'e']

    >>> zk.resolve('/top/a/top/a/b/top/x')
    Traceback (most recent call last):
      File "/usr/local/python/2.6/lib/python2.6/doctest.py", line 1253, in __run
        compileflags, 1) in test.globs
      File "<doctest zc.zk.tests.test_resolve[4]>", line 1, in <module>
        zk.resolve('/top/a/top/a/b/top/x')
      File "/Users/jim/p/zc/zk/trunk/src/zc/zk/__init__.py", line 382, in resolve
        raise zookeeper.NoNodeException(path)
    NoNodeException: /top/a/top/a/b/top/x

    >>> zk.resolve('/top/a/b/c/d/loop')
    Traceback (most recent call last):
    ...
    LinkLoop: ('/top/a/b/c/d/loop', u'/top/a/b/c/d/loop')

    >>> zk.resolve('/top/a/loop/b/c/d')
    Traceback (most recent call last):
    ...
    LinkLoop: ('/top/a/loop', u'/top/a/b/loop', u'/top/a/loop')
    """

def assert_(cond, mess=''):
    if not cond:
        print 'assertion failed: ', mess

def setup(test):
    test.globs['side_effect'] = side_effect
    test.globs['assert_'] = assert_
    test.globs['ZooKeeper'] = zk = ZooKeeper(
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
    for name in ('state', 'init', 'create', 'get', 'set', 'get_children',
                 'exists', 'get_acl', 'set_acl', 'delete'):
        cm = mock.patch('zookeeper.'+name)
        test.globs[name] = m = cm.__enter__()
        m.side_effect = getattr(zk, name)
        zope.testing.setupstack.register(test, cm.__exit__)

class ZooKeeper:

    def __init__(self, tree):
        self.root = tree

    def init(self, addr, watch=None):
        self.handle = 0
        assert_(addr=='zookeeper.example.com:2181', addr)
        if watch:
            watch(0, zookeeper.SESSION_EVENT, zookeeper.CONNECTED_STATE, '')

    def state(self, handle):
        self.check_handle(handle)
        return zookeeper.CONNECTED_STATE

    def check_handle(self, handle):
        if handle != self.handle:
            raise zookeeper.ZooKeeperException('handle out of range')

    def traverse(self, path):
        node = self.root
        for name in path.split('/')[1:]:
            if not name:
                continue
            try:
                node = node.children[name]
            except KeyError:
                raise zookeeper.NoNodeException('no node')

        return node

    def create(self, handle, path, data, acl, flags=0):
        self.check_handle(handle)
        base, name = path.rsplit('/', 1)
        node = self.traverse(base)
        if name in node.children:
            raise zookeeper.NodeExistsException()
        node.children[name] = newnode = Node(data)
        newnode.acls = acl
        newnode.flags = flags
        node.children_changed(self.handle, zookeeper.CONNECTED_STATE, base)
        return path

    def delete(self, handle, path):
        self.check_handle(handle)
        self.traverse(path) # seeif it's there
        base, name = path.rsplit('/', 1)
        node = self.traverse(base)
        del node.children[name]
        node.children_changed(self.handle, zookeeper.CONNECTED_STATE, base)

    def exists(self, handle, path):
        self.check_handle(handle)
        try:
            self.traverse(path)
            return True
        except zookeeper.NoNodeException:
            return False

    def get_children(self, handle, path, watch=None):
        self.check_handle(handle)
        node = self.traverse(path)
        if watch:
            node.child_watchers += (watch, )
        return sorted(node.children)

    def get(self, handle, path, watch=None):
        self.check_handle(handle)
        node = self.traverse(path)
        if watch:
            node.watchers += (watch, )
        return node.data, dict(
            ephemeralOwner=(1 if node.flags & zookeeper.EPHEMERAL else 0),
            )

    def set(self, handle, path, data):
        self.check_handle(handle)
        node = self.traverse(path)
        node.data = data
        node.changed(self.handle, zookeeper.CONNECTED_STATE, path)

    def get_acl(self, handle, path):
        self.check_handle(handle)
        node = self.traverse(path)
        return dict(aversion=node.aversion), node.acl

    def set_acl(self, handle, path, aversion, acl):
        self.check_handle(handle)
        node = self.traverse(path)
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

def test_suite():
    return unittest.TestSuite((
        unittest.makeSuite(Tests),
        doctest.DocTestSuite(
            setUp=setup, tearDown=zope.testing.setupstack.tearDown,
            ),
        manuel.testing.TestSuite(
            manuel.doctest.Manuel(
                checker = zope.testing.renormalizing.RENormalizing([
                    (re.compile('pid = \d+'), 'pid = 9999')
                    ])) + manuel.capture.Manuel(),
            'README.txt',
            setUp=setup, tearDown=zope.testing.setupstack.tearDown,
            ),
        unittest.makeSuite(LoggingTests),
        ))
