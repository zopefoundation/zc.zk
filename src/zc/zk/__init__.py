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
import collections
import json
import logging
import os
import re
import socket
import sys
import threading
import time
import weakref
import zc.zk.event
import zc.thread
import zookeeper

logger = logging.getLogger(__name__)

_logging_pipe = os.pipe()
zookeeper.set_log_stream(os.fdopen(_logging_pipe[1], 'w'))

@zc.thread.Thread
def loggingthread():
    r, w = _logging_pipe
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

                if 'Exceeded deadline by' in line and level == logging.WARNING:
                    level = logging.DEBUG

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

def encode(props):
    if len(props) == 1 and 'string_value' in props:
        return props['string_value']

    if props:
        return json.dumps(props, separators=(',',':'))
    else:
        return ''

def decode(sdata, path='?'):
    s = sdata.strip()
    if not s:
        data = {}
    elif s.startswith('{') and s.endswith('}'):
        try:
            data = json.loads(s)
        except:
            logger.exception('bad json data in node at %r', path)
            data = dict(string_value = sdata)
    else:
        data = dict(string_value = sdata)
    return data

def join(*args):
    return '/'.join(args)

def world_permission(perms=zookeeper.PERM_READ):
    return dict(perms=perms, scheme='world', id='anyone')

OPEN_ACL_UNSAFE = [world_permission(zookeeper.PERM_ALL)]
READ_ACL_UNSAFE = [world_permission()]

class CancelWatch(Exception):
    pass

class LinkLoop(Exception):
    pass

class FailedConnect(Exception):
    pass

class BadPropertyLink(Exception):
    pass

class Resolving:

    def resolve(self, path, seen=()):
        if path.endswith('/.'):
            return self.resolve(path[:-2])
        if path.endswith('/..'):
            base = self.resolve(path[:-3])
            if '/' in base:
                return base.rsplit('/', 1)[0]
            else:
                raise zookeeper.NoNodeException(path)

        try:
            if self.exists(path):
                return path
        except zookeeper.BadArgumentsException:
            if not path[:1] == '/':
                raise zookeeper.NoNodeException(path)

        if path in seen:
            seen += (path,)
            raise LinkLoop(seen)

        try:
            base, name = path.rsplit('/', 1)
            base = self.resolve(base, seen)
            newpath = base + '/' + name
            if self.exists(newpath):
                return newpath
            props = self.get_properties(base)
            newpath = props.get(name+' ->')
            if not newpath:
                raise zookeeper.NoNodeException()

            if not newpath[0] == '/':
                newpath = base + '/' + newpath

            seen += (path,)
            return self.resolve(newpath, seen)
        except zookeeper.NoNodeException:
            raise zookeeper.NoNodeException(path)


class ZooKeeper(Resolving):

    def __init__(self, connection_string="127.0.0.1:2181", session_timeout=None,
                 wait=False):
        self.watches = WatchManager()
        self.ephemeral = {}
        self.handle = None

        connected = self.connected = threading.Event()
        def watch_session(handle, event_type, state, path):
            assert event_type == zookeeper.SESSION_EVENT
            assert not path
            if state == zookeeper.CONNECTED_STATE:
                if self.handle is None:
                    self.handle = handle
                    for watch in self.watches.clear():
                        self._watch(watch)
                    for path, data in self.ephemeral.items():
                        zookeeper.create(self.handle, path, data['data'],
                                         data['acl'], data['flags'])
                else:
                    assert handle == self.handle
                connected.set()
                logger.info('connected %s', handle)
            elif state == zookeeper.CONNECTING_STATE:
                connected.clear()
            elif state == zookeeper.EXPIRED_SESSION_STATE:
                connected.clear()
                if self.handle is not None:
                    zookeeper.close(self.handle)
                self.handle = None
                init()
            else:
                logger.critical('unexpected session event %s %s', handle, state)

        if session_timeout:
            init = (lambda : zookeeper.init(connection_string, watch_session,
                                            session_timeout)
                    )
        else:
            init = lambda : zookeeper.init(connection_string, watch_session)

        handle = init()
        connected.wait(1)
        if not connected.is_set():
            if wait:
                while not connected.is_set():
                    logger.critical("Can't connect to ZooKeeper at %r",
                                    connection_string)
                    connected.wait(1)
            else:
                zookeeper.close(handle)
                raise FailedConnect(connection_string)


    def _findallipv4addrs(self, tail):
        try:
            import netifaces
        except ImportError:
            return [socket.getfqdn()+tail]

        addrs = set()
        loopaddrs = set()
        for iface in netifaces.interfaces():
            for info in netifaces.ifaddresses(iface).get(2, ()):
                addr = info.get('addr')
                if addr:
                    if addr.startswith('127.'):
                        loopaddrs.add(addr+tail)
                    else:
                        addrs.add(addr+tail)

        return addrs or loopaddrs

    def register_server(self, path, addr, acl=READ_ACL_UNSAFE, **kw):
        kw['pid'] = os.getpid()

        if not isinstance(addr, str):
            addr = '%s:%s' % tuple(addr)

        if addr[:1] == ':':
            addrs = self._findallipv4addrs(addr)
        else:
            addrs = (addr,)

        path = self.resolve(path)
        zc.zk.event.notify(RegisteringServer(addr, path, kw))
        if path != '/':
            path += '/'

        for addr in addrs:
            self.create(path + addr, encode(kw), acl, zookeeper.EPHEMERAL)

    test_sleep = 0
    def _async(self, completion, meth, *args):
        post = getattr(self, '_post_'+meth)
        if completion is None:
            result = getattr(zookeeper, meth)(self.handle, *args)
            post(*args)
            if self.test_sleep:
                time.sleep(self.test_sleep)
            return result

        def asynccb(handle, status, *cargs):
            assert handle == self.handle
            if status == 0:
                post(*args)
            completion(handle, status, *cargs)

        return getattr(zookeeper, 'a'+meth)(self.handle, *(args+(asynccb,)))

    def create(self, path, data, acl, flags=0, completion=None):
        return self._async(completion, 'create', path, data, acl, flags)
    acreate = create

    def _post_create(self, path, data, acl, flags):
        if flags & zookeeper.EPHEMERAL:
            self.ephemeral[path] = dict(data=data, acl=acl, flags=flags)

    def delete(self, path, version=-1, completion=None):
        return self._async(completion, 'delete', path, version)
    adelete = delete

    def _post_delete(self, path, version):
        self.ephemeral.pop(path, None)

    def set(self, path, data, version=-1, completion=None):
        return self._async(completion, 'set', path, data, version)
    aset = set2 = set

    def _post_set(self, path, data, version):
        if path in self.ephemeral:
            self.ephemeral[path]['data'] = data

    def set_acl(self, path, version, acl, completion=None):
        return self._async(completion, 'set_acl', path, version, acl)
    aset_acl = set_acl

    def _post_set_acl(self, path, version, acl):
        if path in self.ephemeral:
            self.ephemeral[path]['acl'] = acl

    def _watch(self, watch):
        event_type = watch.event_type
        watch.real_path = real_path = self.resolve(watch.path)
        key = event_type, real_path
        if self.watches.add(key, watch):
            try:
                self._watchkey(key)
            except zookeeper.ConnectionLossException:
                # We lost a race here. We got disconnected between
                # when we resolved the watch path and the time we set
                # the watch. This is very unlikely.
                watches = set(self.watches.pop(key))
                for w in watches:
                    w._deleted()
                if watch in watches:
                    watches.remove(watch)
                if watches:
                    # OMG, how unlucky can we be?
                    # someone added a watch between the time we added
                    # the key and failed to add the watch in zookeeper.
                    logger.critical('lost watches %r', watches)
                raise
        else:
            # We already had a watch for the key.  We need to pass this one
            # it's data.
            zkfunc = getattr(zookeeper, self.__zkfuncs[event_type])
            watch._notify(zkfunc(self.handle, real_path))

    __zkfuncs = {
        zookeeper.CHANGED_EVENT: 'get',
        zookeeper.CHILD_EVENT: 'get_children',
        }
    def _watchkey(self, key):
        event_type, real_path = key
        zkfunc = getattr(zookeeper, self.__zkfuncs[event_type])

        def handler(h, t, state, p, reraise=False):

            if state != zookeeper.CONNECTED_STATE:
                # This can happen if we get disconnected or a session expires.
                # When we reconnect, we should restablish the watchers.
                logger.warning(
                    "Node watcher event %r with non-connected state, %r",
                    t, state)
                return

            try:
                assert h == self.handle
                assert state == zookeeper.CONNECTED_STATE
                assert p == real_path
                if key not in self.watches:
                    return

                if t == zookeeper.DELETED_EVENT:
                    self._rewatch(key)
                else:
                    assert t == event_type
                    try:
                        v = zkfunc(self.handle, real_path, handler)
                    except zookeeper.NoNodeException:
                        self._rewatch(key)
                    else:
                        for watch in self.watches.watches(key):
                            watch._notify(v)
            except:
                logger.exception("%s(%s) handler failed",
                                 self.__zkfuncs[event_type], real_path)
                if reraise:
                    raise

        handler(self.handle, event_type, self.state, real_path, True)

    def _rewatch(self, key):
        event_type = key[0]
        for watch in self.watches.pop(key):
            try:
                real_path = self.resolve(watch.path)
            except (zookeeper.NoNodeException, LinkLoop):
                logger.exception("%s path went away", watch)
                watch._deleted()
            else:
                self._watch(watch)

    def children(self, path):
        return Children(self, path)

    def create_recursive(self, path, data, acl):
        if self.exists(path):
            return
        base, name = path.rsplit('/', 1)
        if base:
            self.create_recursive(base, data, acl)
        if not self.exists(path):
            self.create(path, data, acl)

    def get_properties(self, path):
        return decode(self.get(path)[0])

    def properties(self, path):
        return Properties(self, path)

    def import_tree(self, text, path='/', trim=False, acl=OPEN_ACL_UNSAFE,
                    dry_run=False):
        while path.endswith('/'):
            path = path[:-1] # Mainly to deal w root: /
        self._import_tree(path, parse_tree(text), acl, trim, dry_run, True)

    def _import_tree(self, path, node, acl, trim, dry_run, top=False):
        if not top:
            new_children = set(node.children)
            for name in sorted(self.get_children(path)):
                if name in new_children:
                    continue
                cpath = join(path, name)
                if trim:
                    self.delete_recursive(cpath, dry_run)
                else:
                    print 'extra path not trimmed:', cpath

        for name, child in sorted(node.children.iteritems()):
            cpath = path + '/' + name
            data = encode(child.properties)
            if self.exists(cpath):
                if dry_run:
                    new = child.properties
                    old = self.get_properties(cpath)
                    old = decode(self.get(cpath)[0])
                    for n, v in sorted(old.items()):
                        if n not in new:
                            if n.endswith(' ->'):
                                print '%s remove link %s %s' % (cpath, n, v)
                            else:
                                print '%s remove property %s = %s' % (
                                    cpath, n, v)
                        elif new[n] != v:
                            if n.endswith(' ->'):
                                print '%s %s link change from %s to %s' % (
                                    cpath, n[:-3], v, new[n])
                            else:
                                print '%s %s change from %s to %s' % (
                                    cpath, n, v, new[n])
                    for n, v in sorted(new.items()):
                        if n not in old:
                            if n.endswith(' ->'):
                                print '%s add link %s %s' % (cpath, n, v)
                            else:
                                print '%s add property %s = %s' % (
                                    cpath, n, v)
                else:
                    self.set(cpath, data)
                    meta, oldacl = self.get_acl(cpath)
                    if acl != oldacl:
                        self.set_acl(cpath, meta['aversion'], acl)
            else:
                if dry_run:
                    print 'add', cpath
                    continue
                else:
                    self.create(cpath, data, acl)
            self._import_tree(cpath, child, acl, trim, dry_run)

    def delete_recursive(self, path, dry_run=False, force=False):
        self._delete_recursive(path, dry_run, force)

    def _delete_recursive(self, path, dry_run, force):
        ephemeral_child = None
        for name in sorted(self.get_children(path)):
            ephemeral_child = (
                self._delete_recursive(join(path, name), dry_run, force) or
                ephemeral_child
                )

        if ephemeral_child:
            print "%s not deleted due to ephemeral descendent." % path
            return ephemeral_child

        ephemeral = self.is_ephemeral(path) and not force
        if dry_run:
            if ephemeral:
                print "wouldn't delete %s because it's ephemeral." % path
            else:
                print "would delete %s." % path
        else:
            if ephemeral:
                print "Not deleting %s because it's ephemeral." % path
            else:
                logger.info('deleting %s', path)
                self.delete(path)
        return ephemeral

    def is_ephemeral(self, path):
        return bool(self.get(path)[1]['ephemeralOwner'])

    def export_tree(self, path='/', ephemeral=False, name=None):
        output = []
        out = output.append

        def export_tree(path, indent, name=None):
            children = self.get_children(path)
            if path == '/':
                path = ''
                if 'zookeeper' in children:
                    children.remove('zookeeper')
                if name is not None:
                    out(indent + '/' + name)
                    indent += '  '
            else:
                data, meta = self.get(path)
                if meta['ephemeralOwner'] and not ephemeral:
                    return
                if name is None:
                    name = path.rsplit('/', 1)[1]
                properties = decode(data)
                type_ = properties.pop('type', None)
                if type_:
                    name += ' : '+type_
                out(indent + '/' + name)
                indent += '  '
                links = []
                for i in sorted(properties.iteritems()):
                    if i[0].endswith(' ->'):
                        links.append(i)
                    else:
                        out(indent+"%s = %r" % i)
                for i in links:
                    out(indent+"%s %s" % i)

            for name in sorted(children):
                export_tree(path+'/'+name, indent)

        export_tree(path, '', name)
        return '\n'.join(output)+'\n'

    def print_tree(self, path='/'):
        print self.export_tree(path, True),

    def _set(self, path, data):
        return self.set(path, data)

    def ln(self, target, source):
        base, name = source.rsplit('/', 1)
        if target[-1] == '/':
            target += name
        properties = self.get_properties(base)
        properties[name+' ->'] = target
        self._set(base, encode(properties))

    def close(self):
        zookeeper.close(self.handle)
        self.handle = None

    @property
    def state(self):
        if self.handle is None:
            return zookeeper.CONNECTING_STATE
        return zookeeper.state(self.handle)

    def walk(self, path='/'):
        yield path
        for name in sorted(self.get_children(path)):
            if path != '/':
                name = '/'+name
            for p in self.walk(path+name):
                yield p


def _make_method(name):
    return (lambda self, *a, **kw:
            getattr(zookeeper, name)(self.handle, *a, **kw))

for name in (
    'add_auth', 'aexists', 'aget', 'aget_acl',
    'aget_children', 'async', 'client_id',
    'exists', 'get', 'get_acl',
    'get_children', 'is_unrecoverable', 'recv_timeout',
    ):
    setattr(ZooKeeper, name, _make_method(name))

del _make_method

class WatchManager:
    # Manage {key -> w{watches}} in a thread-safe manner.
    # (And also provide a hard set to allow nodeinfos w callbacks
    #  to keep themselves around.)

    def __init__(self):
        self.data = {}
        self.lock = threading.Lock()

        def _remove(ref, selfref=weakref.ref(self)):
            self = selfref()
            if self is None:
                return
            key = ref.key
            with self.lock:
                refs = self.data.get(key, ())
                if ref in refs:
                    refs.remove(ref)
                    if not refs:
                        del self.data[key]

        self._remove = _remove

    def __len__(self):
        with self.lock:
            return sum(
                len([r for r in refs if r() is not None])
                for refs in self.data.itervalues()
                )

    def __contains__(self, key):
        with self.lock:
            return key in self.data

    def add(self, key, value):
        ref = weakref.KeyedRef(value, self._remove, key)
        newkey = False
        with self.lock:
            try:
                refs = self.data[key]
            except KeyError:
                self.data[key] = refs = set()
                newkey = True
            refs.add(ref)
        return newkey

    def pop(self, key):
        with self.lock:
            watches = [ref() for ref in self.data.pop(key, ())]

        for watch in watches:
            if watch is not None:
                yield watch

    def watches(self, key):
        with self.lock:
            watches = [ref() for ref in self.data.get(key, ())]

        for watch in watches:
            if watch is not None:
                yield watch

    def clear(self):
        # Clear data and return an iterator on the old values
        with self.lock:
            old = self.data
            self.data = {}

        for refs in old.itervalues():
            for ref in refs:
                v = ref()
                if v is not None:
                    yield v

ZK = ZooKeeper

class NodeInfo:

    def __init__(self, session, path):
        self.session = session
        self.path = path
        self.callbacks = []
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
        return "%s%s.%s(%s, %s)" % (
            self.deleted and 'DELETED: ' or '',
            self.__class__.__module__, self.__class__.__name__,
            self.session.handle, self.path)

    def _notify(self, data):
        if data is not None:
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
        self.callbacks.append(func)
        return self

    def __iter__(self):
        return iter(self.data)

class Children(NodeInfo):

    event_type = zookeeper.CHILD_EVENT

    def __len__(self):
        return len(self.data)

class Properties(NodeInfo, collections.Mapping):

    event_type = zookeeper.CHANGED_EVENT

    def __init__(self, *args):
        self._linked_properties = {}
        NodeInfo.__init__(self, *args)

    def _setData(self, data, handle_errors=False):
        # Save a mapping as our data.
        # Set up watchers for any property links.
        _linked_properties = {}
        for name in data:
            if name.endswith(' =>') and name[:-3] not in data:
                link = data[name].strip().split()
                try:
                    if not (1 <= len(link) <= 2):
                        raise ValueError('Bad link data')
                    path = link.pop(0)
                    if path[0] != '/':
                        path = self.path + '/' + path
                    path = self.session.resolve(path)
                    properties = self._setup_link(path, _linked_properties)
                    properties[link and link[0] or name[:-3]]
                except Exception, v:
                    if handle_errors:
                        logger.exception(
                            'Bad property link %r %r', name, data[name])
                    else:
                        raise ValueError("Bad property link",
                                         name, data[name], v)

        # Only after processing all links, do we update instance attrs:
        self.data = data
        self._linked_properties = _linked_properties

    def _setup_link(self, path, _linked_properties=None):
        if _linked_properties is None:
            _linked_properties = self._linked_properties

        props = _linked_properties.get(path, self)
        if props is not self:
            return props

        props = self.session.properties(path)

        _linked_properties[path] = props

        def notify(properties=None):
            if properties is None:
                # A node we were watching was deleted.  We shuld try to
                # re-resolve it. This doesn't happen often, let's just reset
                # everything.
                self._setData(self.data)
            elif self._linked_properties.get(path) is properties:
                self._notify(None)
            else:
                # We must not care about it anymore.
                raise CancelWatch()

        props.callbacks.append(notify)
        return props

    def setData(self, data):
        # Called by upstream watchers.
        sdata, self.meta_data = data
        self._setData(decode(sdata, self.path), True)

    def __getitem__(self, key, seen=()):
        try:
            return self.data[key]
        except KeyError:
            link = self.data.get(key + ' =>', self)
            if link is self:
                raise
            try:
                data = link.split()
                if len(data) > 2:
                    raise ValueError('Invalid property link')
                path = data.pop(0)
                if not path[0] == '/':
                    path = self.path + '/' + path

                path = self.session.resolve(path)
                if path in seen:
                    raise LinkLoop(seen+(path,))
                seen += (path,)
                properties = self._linked_properties.get(path)
                if properties is None:
                    properties = self._setup_link(path)
                name = data and data[0] or key
                return properties.__getitem__(name, seen)
            except Exception, v:
                raise BadPropertyLink(
                    v, 'in %r: %r' %
                    (key + ' =>', self.data[key + ' =>'])
                    )

    def __len__(self):
        return len(self.data)

    def __contains__(self, key):
        return key in self.data or (key + ' =>') in self.data

    def copy(self):
        return self.data.copy()

    def _set(self, data):
        self._setData(data)
        self.session._set(self.path, encode(data))

    def set(self, data=None, **properties):
        data = data and dict(data) or {}
        data.update(properties)
        self._set(data)

    def update(self, data=None, **properties):
        d = self.data.copy()
        if data:
            d.update(data)
        d.update(properties)
        self._set(d)

    def __hash__(self):
        # Gaaaa, collections.Mapping
        return hash(id(self))

_text_is_node = re.compile(
    r'/(?P<name>\S+)'
    '(\s*:\s*(?P<type>\S.*))?'
    '$').match
_text_is_property = re.compile(
    r'(?P<name>\S+)'
    '\s*=\s*'
    '(?P<expr>\S.*)'
    '$'
    ).match
_text_is_link = re.compile(
    r'(?P<name>\S+)'
    '\s*->\s*'
    '(?P<target>\S+)'
    '$'
    ).match
_text_is_plink = re.compile(
    r'(?P<name>\S+)'
    '\s*=>\s*'
    '(?P<target>\S+(\s+\S+)?)'
    '(\s+(?P<pname>/\S+))?'
    '$'
    ).match

class ParseNode:

    def __init__(self, name='', properties=None, **children):
        self.name = name
        self.properties = properties or {}
        self.children = children
        for name, child in children.iteritems():
            child.name = name

def parse_tree(text, node_class=ParseNode):
    root = node_class()
    indents = [(-1, root)] # sorted [(indent, node)]
    lineno = 0
    for line in text.split('\n'):
        lineno += 1
        line = line.rstrip()
        if not line:
            continue
        stripped = line.strip()
        if stripped[0] == '#':
            continue
        indent = len(line) - len(stripped)

        data = None

        m = _text_is_plink(stripped)
        if m:
            data = (m.group('name') + ' =>'), m.group('target')

        if data is None:
            m = _text_is_property(stripped)
            if m:
                expr = m.group('expr')
                try:
                    data = eval(expr, {})
                except Exception, v:
                    raise ValueError(
                        "Error %s in expression: %r in line %s" %
                        (v, expr, lineno))
                data = m.group('name'), data

        if data is None:
            m = _text_is_link(stripped)
            if m:
                data = (m.group('name') + ' ->'), m.group('target')

        if data is None:
            m = _text_is_node(stripped)
            if m:
                data = node_class(m.group('name'))
                if m.group('type'):
                    data.properties['type'] = m.group('type')

        if data is None:
            if '->' in stripped:
                raise ValueError(lineno, stripped, "Bad link format")
            else:
                raise ValueError(lineno, stripped, "Unrecognized data")

        if indent > indents[-1][0]:
            if not isinstance(indents[-1][1], node_class):
                raise ValueError(
                    lineno, line,
                    "Can't indent under properties")
            indents.append((indent, data))
        else:
            while indent < indents[-1][0]:
                indents.pop()

            if indent > indents[-1][0]:
                raise ValueError(lineno, data, "Invalid indentation")

        if isinstance(data, node_class):
            children = indents[-2][1].children
            if data.name in children:
                raise ValueError(lineno, data, 'duplicate node')
            children[data.name] = data
            indents[-1] = indent, data
        else:
            if indents[-2][1] is root:
                raise ValueError("Can't above imported nodes.")
            properties = indents[-2][1].properties
            name, value = data
            if name in properties:
                raise ValueError(lineno, data, 'duplicate property')
            properties[name] = value

    return root

class RegisteringServer:
    """Event emitted while a server is being registered.

    Attributes:

    name
      The server name (node name)
    name
      The service path (node parent path)
    properties
      A dictionary of properties to be saved on the ephemeral node.

      Typeically, subscribers will add properties.
    """

    def __init__(self, name, path, properties):
        self.name = name
        self.path = path
        self.properties = properties

    def __repr__(self):
        return "RegisteringServer(%r, %r, %r)" % (
            self.name, self.path, self.properties)
