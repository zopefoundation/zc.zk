import doctest
import json
import logging
import mock
import os
import StringIO
import time
import zc.zk
import zc.thread
import zookeeper
import zope.testing.loggingsupport
import zope.testing.setupstack
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
        logger.setLevel(logging.ERROR)
        handle = zookeeper.init('zookeeper.example.com:2181')
        wait_until(lambda : 'error' in f.getvalue())
        zookeeper.close(handle)
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
        self.assertEqual(self.__set_data, '{"b": 2}')
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

def assert_(cond, mess=''):
    if not cond:
        print 'assertion failed: ', mess

def setup(test):
    test.globs['side_effect'] = side_effect
    test.globs['assert_'] = assert_
    for name in 'state', 'init', 'create', 'get', 'set', 'get_children':
        cm = mock.patch('zookeeper.'+name)
        test.globs[name] = cm.__enter__()
        zope.testing.setupstack.register(test, cm.__exit__)

def test_suite():
    return unittest.TestSuite((
        unittest.makeSuite(Tests),
        doctest.DocFileSuite(
            'README.txt',
            setUp=setup, tearDown=zope.testing.setupstack.tearDown
            ),
        unittest.makeSuite(LoggingTests),
        ))
