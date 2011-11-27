import collections
import json
import logging
import os
import sys
import threading
import zc.thread
import zookeeper

logger = logging.getLogger(__name__)

@zc.thread.Thread
def loggingthread():
    r, w = os.pipe()
    zookeeper.set_log_stream(os.fdopen(w, 'w'))
    log = logging.getLogger('ZooKeeper').log
    f = os.fdopen(r)
    levels = dict(ZOO_INFO = logging.INFO,
                  ZOO_WARN = logging.WARNING,
                  ZOO_ERROR = logging.ERROR,
                  ZOO_DEBUG = logging.DEBUG,
                  )
    while 1:
        line = f.readline().strip()
        try:
            if '@' in line:
                level, message = line.split('@', 1)
                level = levels.get(level.split(':')[-1])
            else:
                level = None

            if level is None:
                log(logging.INFO, line)
            else:
                log(level, message)
        except Exception, v:
            logging.getLogger('ZooKeeper').exception("Logging error: %s", v)


def parse_addr(addr):
    host, port = addr.split(':')
    return host, int(port)

def world_permission(perms=zookeeper.PERM_READ):
    return dict(perms=perms, scheme='world', id='anyone')

class CancelWatch(Exception):
    pass

class ZooKeeper:

    def __init__(self, zkaddr=2181):
        if isinstance(zkaddr, int):
            zkaddr = "127.0.0.1:%s" % zkaddr
        self.zkaddr = zkaddr
        self.watches = set()
        self.connected = threading.Event()
        zookeeper.init(zkaddr, self._watch_session)
        self.connected.wait()

    handle = None
    def _watch_session(self, handle, event_type, state, path):
        assert event_type == zookeeper.SESSION_EVENT
        assert not path
        if state == zookeeper.CONNECTED_STATE:
            if self.handle is None:
                self.handle = handle
                if self.watches:
                    # reestablish after session reestablished
                    watches = self.watches
                    self.watches = set()
                    for watch in watches:
                        self._watch(watch, False)
            else:
                assert handle == self.handle
            self.connected.set()
            logger.info('connected %s', handle)
        elif state == zookeeper.CONNECTING_STATE:
            self.connected.clear()
        elif state == zookeeper.EXPIRED_SESSION_STATE:
            self.connected.clear()
            zookeeper.close(self.handle)
            self.handle = None
            zookeeper.init(self.zkaddr, self._watch_session)
        else:
            logger.critical('unexpected session event %s %s', handle, state)

    def register_server(self, path, addr, **kw):
        kw['pid'] = os.getpid()
        self.connected.wait()
        zookeeper.create(self.handle, path + '/%s:%s' % addr, json.dumps(kw),
                         [world_permission()], zookeeper.EPHEMERAL)

    def _watch(self, watch, wait=True):
        if wait:
            self.connected.wait()
        self.watches.add(watch)

        def handler(h, t, state, p):
            if watch not in self.watches:
                return
            assert h == self.handle
            assert state == zookeeper.CONNECTED_STATE
            assert p == watch.path
            if t == zookeeper.DELETED_EVENT:
                watch._deleted()
                self.watches.remove(watch)
            else:
                assert t == watch.event_type
                zkfunc = getattr(zookeeper, watch.zkfunc)
                watch._notify(zkfunc(self.handle, watch.path, handler))

        handler(self.handle, watch.event_type, self.state, watch.path)

    def children(self, path):
        return Children(self, path)

    def properties(self, path):
        return Properties(self, path)

    def _set(self, path, data):
        self.connected.wait()
        return zookeeper.set(self.handle, path, data)

    def print_tree(self, path='/', indent=0):
        self.connected.wait()
        prefix = ' '*indent
        print prefix + path.split('/')[-1]+'/'
        indent += 2
        prefix += '  '
        data = zookeeper.get(self.handle, path)[0].strip()
        if data:
            if data.startswith('{') and data.endswith('}'):
                data = json.loads(data)
                import pprint
                print prefix+pprint.pformat(data).replace(
                    '\n', prefix+'\n')
            else:
                print prefix + repr(data)
        for p in zookeeper.get_children(self.handle, path):
            if not path.endswith('/'):
                p = '/'+p
            self.print_tree(path+p, indent)

    def close(self):
        zookeeper.close(self.handle)
        del self.handle

    @property
    def state(self):
        if self.handle is None:
            return zookeeper.CONNECTING_STATE
        return zookeeper.state(self.handle)


class NodeInfo:

    def __init__(self, session, path):
        self.session = session
        self.path = path
        self.callbacks = set()
        session._watch(self)

    def setData(self, data):
        self.data = data

    deleted = False
    def _deleted(self):
        self.deleted = True
        self.data = {}
        for callback in self.callbacks:
            try:
                callback()
            except TypeError:
                pass
            except:
                logger.exception('Error %r calling %r', self, callback)

    def __repr__(self):
        return "%s.%s(%s, %s)" % (
            self.__class__.__module__, self.__class__.__name__,
            self.session.handle, self.path)

    def _notify(self, data):
        self.setData(data)
        for callback in list(self.callbacks):
            try:
                callback(self)
            except Exception, v:
                self.callbacks.remove(callback)
                if isinstance(v, CancelWatch):
                    logger.debug("cancelled watch(%r, %r)", self, callback)
                else:
                    logger.exception("watch(%r, %r)", self, callback)

    def __call__(self, func):
        func(self)
        self.callbacks.add(func)
        return func

    def __iter__(self):
        return iter(self.data)

class Children(NodeInfo):

    event_type = zookeeper.CHILD_EVENT
    zkfunc = 'get_children'

class Properties(NodeInfo, collections.Mapping):

    event_type = zookeeper.CHANGED_EVENT
    zkfunc = 'get'

    def setData(self, data):
        sdata, self.meta_data = data
        s = sdata.strip()
        if not s:
            data = {}
        elif s.startswith('{') and s.endswith('}'):
            try:
                data = json.loads(s)
            except:
                logger.exception('bad json data in node at %r', self.path)
                data = dict(string_value = sdata)
        else:
            data = dict(string_value = sdata)

        self.data = data

    def __getitem__(self, key):
        return self.data[key]

    def __len__(self):
        return len(self.data)

    def __contains__(self, key):
        return key in self.data

    def copy(self):
        return self.data.copy()

    def _set(self, data):
        if not data:
            sdata = ''
        elif len(data) == 1 and 'string_value' in data:
            sdata = data['string_value']
        else:
            sdata = json.dumps(data)
        self.data = data
        zookeeper.set(self.session.handle, self.path, sdata)

    def set(self, **data):
        self._set(data)

    def update(self, **updates):
        data = self.data.copy()
        data.update(updates)
        self._set(data)

    def __hash__(self):
        # Gaaaa, collections.Mapping
        return hash(id(self))
