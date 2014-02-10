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
import kazoo.client
import kazoo.exceptions

from kazoo.security import OPEN_ACL_UNSAFE, READ_ACL_UNSAFE

logger = logging.getLogger(__name__)

def parse_addr(addr):
    host, port = addr.split(':')
    return host, int(port)

def encode(props):
    if len(props) == 1 and 'string_value' in props:
        return props['string_value']

    return json.dumps(props, separators=(',',':'))

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

class CancelWatch(Exception):
    pass

class LinkLoop(Exception):
    pass

class FailedConnect(Exception):
    pass

class BadPropertyLink(Exception):
    pass

dot = re.compile(r"/\.(/|$)")
dotdot = re.compile(r"/[^/]+/\.\.(/|$)")
class Resolving:

    def resolve(self, path, seen=()):

        # normalize dots
        while 1:
            npath = dotdot.sub(r"\1", dot.sub(r"\1", path))
            if npath == path:
                break
            path = npath

        if self.exists(path):
            return path

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
                raise kazoo.exceptions.NoNodeError(newpath)

            if not newpath[0] == '/':
                newpath = base + '/' + newpath

            seen += (path,)
            return self.resolve(newpath, seen)
        except kazoo.exceptions.NoNodeError:
            raise kazoo.exceptions.NoNodeError(path)

aliases = 'exists', 'create', 'delete', 'get_children', 'get'

class ZooKeeper(Resolving):

    def __init__(
        self,
        connection_string="127.0.0.1:2181",
        session_timeout=None,
        wait = False
        ):

        if session_timeout is None:
            session_timeout = 10.0

        self.session_timeout = session_timeout

        if isinstance(connection_string, basestring):
            client = kazoo.client.KazooClient(
                connection_string, session_timeout)
            started = False
        else:
            client = connection_string
            started = True
            self.close = lambda : None

        self.client = client
        for alias in aliases:
            setattr(self, alias, getattr(client, alias))

        self.ephemeral = {}
        self.state = None

        def watch_session(state):
            if state == kazoo.protocol.states.KazooState.CONNECTED:
                if self.state == kazoo.protocol.states.KazooState.LOST:
                    logger.warning("session lost")
                    for path, data in self.ephemeral.items():
                        logger.info("restoring ephemeral %s", path)
                        self.create(
                            path, data['data'], data['acl'], ephemeral=True)
                logger.info('connected')
            self.state = state

        client.add_listener(watch_session)

        if started:
            watch_session(client.state)
        else:
            while 1:
                try:
                    client.start()
                except Exception:
                    logger.critical("Can't connect to ZooKeeper at %r",
                                    connection_string)
                    if wait:
                        time.sleep(1)
                    else:
                        raise FailedConnect(connection_string)
                else:
                    break

    def get_properties(self, path):
        return decode(self.get(path)[0], path)

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

    def register(self, path, addr, acl=READ_ACL_UNSAFE, **kw):
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
            data = encode(kw)
            apath = path + addr
            self.create(apath, data, acl, ephemeral=True)
            self.ephemeral[apath] = dict(data=data, acl=acl)

    register_server = register # backward compatibility

    def set(self, path, data, *a, **k):
        r = self.client.set(path, data, *a, **k)
        if path in self.ephemeral:
            self.ephemeral[path]['data'] = data
        return r

    def children(self, path):
        return Children(self, path)

    def properties(self, path, watch=True):
        return Properties(self, path, watch)

    def import_tree(self, text, path='/', trim=None, acl=OPEN_ACL_UNSAFE,
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
                    self.delete_recursive(cpath, dry_run,
                                          ignore_if_ephemeral=True)
                elif trim is None:
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
                    oldacl, meta = self.client.get_acls(cpath)
                    if acl != oldacl:
                        self.client.set_acls(cpath, meta.aversion, acl)
            else:
                if dry_run:
                    print 'add', cpath
                    continue
                else:
                    self.create(cpath, data, acl)
            self._import_tree(cpath, child, acl, trim, dry_run)

    def delete_recursive(self, path, dry_run=False, force=False,
                         ignore_if_ephemeral=False):
        self._delete_recursive(path, dry_run, force, ignore_if_ephemeral)

    def _delete_recursive(self, path, dry_run, force,
                          ignore_if_ephemeral=False):
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
        if ephemeral and ignore_if_ephemeral:
            return
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
        return bool(self.get(path)[1].ephemeralOwner)

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
                if meta.ephemeralOwner and not ephemeral:
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

    def ln(self, target, source):
        base, name = source.rsplit('/', 1)
        if target[-1] == '/':
            target += name
        properties = decode(self.get(base)[0])
        properties[name+' ->'] = target
        self.set(base, encode(properties))

    def close(self):
        self.client.stop()
        self.client.close()
        self.close = lambda : None

    def walk(self, path='/', ephemeral=True, children=False):
        try:
            if not ephemeral and self.get(path)[1].ephemeralOwner:
                return

            _children = sorted(self.get_children(path))
            if children:
                yield path, _children
            else:
                yield path
        except kazoo.exceptions.NoNodeError:
            return

        for name in _children:
            if path != '/':
                name = '/'+name
            for p in self.walk(path+name):
                yield p

    def create_recursive(self, path, data, acl):
        self.client.ensure_path(path, acl)
        self.client.set(path, data)

    # for test assertions, in a backward-compatible way
    def recv_timeout(self):
        return self.session_timeout

ZK = ZooKeeper

class KazooWatch:

    def __init__(self, client, children, path, watch):
        self.watch_ref = weakref.ref(watch)
        if children:
            client.ChildrenWatch(path)(self.handle)

            # Add a data watch so we know when a node is deleted.
            @client.DataWatch(path)
            def handle(data, *_):
                if data is None:
                    self.handle(data)
        else:
            client.DataWatch(path)(self.handle)

    def handle(self, data, *rest):
        watch = self.watch_ref()
        if watch is None:
            return False
        watch.handle(data, *rest)
        if data is None:
            return False

class Watch:
    # Base class for child and data watchers

    def __init__(self, zk, path, watch=True):
        self.zk = zk
        self.path = path
        self.watch = watch
        self.callbacks = []
        self.register(True)

    def register(self, reraise):
        try:
            real_path = self.zk.resolve(self.path)
        except Exception:
            if reraise:
                raise
            else:
                self._deleted()
        else:
            self.real_path = real_path
            if self.watch:
                KazooWatch(self.zk.client, self.children, real_path, self)
            else:
                if self.children:
                    self.setData(self.zk.get_children(real_path))
                else:
                    self.setData(self.zk.get(real_path)[0])

    def handle(self, data, *rest):
        if data is None:
            # The watched node was deleted.
            # Try to re-resolve the watch path.
            self.register(False)
        else:
            self._notify(data)

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
        return "%s%s.%s(%s)" % (
            self.deleted and 'DELETED: ' or '',
            self.__class__.__module__, self.__class__.__name__,
            self.path)

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
        if not self.watch:
            raise TypeError("Can't set callbacks without watching.")
        func(self)
        self.callbacks.append(func)
        return self

    def __iter__(self):
        return iter(self.data)

class Children(Watch):

    children = True

    def setData(self, data):
        Watch.setData(self, [v.encode('utf8') for v in data])

    def __len__(self):
        return len(self.data)

class Properties(Watch, collections.Mapping):

    children = False

    def __init__(self, zk, path, watch=True, _linked_properties=None):
        if _linked_properties is None:
             # {prop_link_path -> Properties}
            _linked_properties = {}
        self._linked_properties = _linked_properties
        Watch.__init__(self, zk, path, watch)

    def _setData(self, data, handle_errors=False):
        # Save a mapping as our data.
        # Set up watchers for any property links.
        old = getattr(self, 'data', None)
        self.data = data
        try:
            for name in data:
                if name.endswith(' =>') and name[:-3] not in data:
                    link = data[name].strip().split()
                    try:
                        if not (1 <= len(link) <= 2):
                            raise ValueError('Bad link data')
                        path = link.pop(0)
                        if path[0] != '/':
                            path = self.path + '/' + path

                        # TODO: why resolve here? Why not store the original
                        # path in the linked properties.
                        path = self.zk.resolve(path)
                        properties = self._setup_link(path)
                        properties[link and link[0] or name[:-3]]
                    except Exception, v:
                        if handle_errors:
                            logger.exception(
                                'Bad property link %r %r', name, data[name])
                        else:
                            raise ValueError("Bad property link",
                                             name, data[name], v)
        except:
            self.data = old # rollback
            raise

    def _setup_link(self, path):
        _linked_properties = self._linked_properties
        props = _linked_properties.get(path)
        if props is not None:
            return props

        _linked_properties[self.real_path] = self
        props = Properties(self.zk, path, self.watch, _linked_properties)

        _linked_properties[path] = props

        if self.watch:
            @props.callbacks.append
            def notify(properties=None):
                if properties is None:
                    # A node we were watching was deleted.  We should
                    # try to re-resolve it. This doesn't happen often,
                    # let's just reset everything.
                    self._setData(self.data, True)
                elif self._linked_properties.get(path) is properties:
                    # Notify our subscribers that there was a change
                    # that might effect them. (But don't update our data.)
                    self._notify(None)
                else:
                    # We must not care about it anymore.
                    raise CancelWatch()

        return props

    def setData(self, data):
        self._setData(decode(data, self.path), True)

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

                path = self.zk.resolve(path)
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

    def __iter__(self):
        for key in self.data:
            if key.endswith(' =>'):
                key = key[:-3]
            yield key

    def __len__(self):
        return len(self.data)

    def __contains__(self, key):
        return key in self.data or (key + ' =>') in self.data

    def copy(self):
        return self.data.copy()

    def _set(self, data):
        self._linked_properties = {}
        self._setData(data)
        self.zk.set(self.path, encode(data))

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

    def __setitem__(self, key, value):
        self.update({key: value})

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
                raise ValueError(
                    "Can't import properties above imported nodes.")
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
