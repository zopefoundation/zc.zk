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
from pprint import pprint
from zope.testing import setupstack
from zope.testing.wait import wait
import doctest
import json
import logging
import manuel.capture
import manuel.doctest
import manuel.testing
import mock
import os
import re
import socket
import StringIO
import sys
import threading
import time
import zc.zk
import zc.zk.testing
import zc.thread
import zope.testing.loggingsupport
import zope.testing.renormalizing
import unittest

def side_effect(mock):
    return lambda func: setattr(mock, 'side_effect', func)

class zklogger(object):

    def __init__(self):
        logger = logging.getLogger('zc.zk')
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(h)
        self.h = h
        logger.setLevel(logging.DEBUG)

    def uninstall(self):
        logger = logging.getLogger('zc.zk')
        logger.removeHandler(self.h)
        logger.setLevel(logging.NOTSET)

def test_children():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> _ = zk.create('/test')
    >>> children = zk.children('/test')
    >>> list(children)
    []

    >>> len(children)
    0
    >>> bool(children)
    False

    >>> def create(path):
    ...     zk.create(path, '', zc.zk.OPEN_ACL_UNSAFE)
    >>> create('/test/a')
    >>> sorted(children)
    ['a']

    >>> len(children)
    1
    >>> bool(children)
    True

We can register callbacks:

    >>> @children
    ... def cb(c):
    ...     print 'good', sorted(c)
    good ['a']

When we register a callback, it gets called immediately with a children object.

    >>> create('/test/b')
    good ['a', 'b']
    >>> sorted(children)
    ['a', 'b']

If a callback raises an error immediately, it isn't saved:

    >>> @children
    ... def bad(c):
    ...     raise ValueError
    Traceback (most recent call last):
    ...
    ValueError

    >>> create('/test/c')
    good ['a', 'b', 'c']

    >>> len(children)
    3
    >>> bool(children)
    True

If a callback raises an error later, it is logged and the callback is
cancelled:

    >>> logger = zklogger()

    >>> badnow = False
    >>> @children
    ... def bad(c):
    ...     assert c is children
    ...     print 'bad later', sorted(c)
    ...     if badnow:
    ...         raise ValueError
    bad later ['a', 'b', 'c']

    >>> _ = zk.delete('/test/c')
    good ['a', 'b']
    bad later ['a', 'b']

    >>> badnow = True
    >>> _ = zk.delete('/test/b') # doctest: +ELLIPSIS
    good ['a']
    bad later ['a']
    ERROR watch(zc.zk.Children(/test), <function bad at ...>)
    Traceback (most recent call last):
    ...
    ValueError

    >>> _ = zk.delete('/test/a')
    good []

A callback can also cancel itself by raising CancelWatch:

    >>> cancelnow = False
    >>> @children
    ... def cancel(c):
    ...     assert c is children
    ...     print 'cancel later', sorted(c)
    ...     if cancelnow:
    ...         raise zc.zk.CancelWatch
    cancel later []

    >>> create('/test/a')
    good ['a']
    cancel later ['a']

    >>> cancelnow = True
    >>> create('/test/b') # doctest: +ELLIPSIS
    good ['a', 'b']
    cancel later ['a', 'b']
    DEBUG cancelled watch(zc.zk.Children(/test), <function cancel at ...>)

    >>> logger.uninstall()

    >>> zk.close()

    """

def test_handler_cleanup():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> _ = zk.create('/test')

Children:

    >>> children = zk.children('/test')
    >>> @children
    ... def kids(c):
    ...     print c
    zc.zk.Children(/test)
    >>> del children
    >>> _ = zk.create('/test/a')
    zc.zk.Children(/test)
    >>> del kids
    >>> _ = zk.create('/test/aa')

    >>> @zk.children('/test')
    ... def kids(c):
    ...     print c
    zc.zk.Children(/test)

    >>> _ = zk.create('/test/aaa')
    zc.zk.Children(/test)
    >>> del kids
    >>> _ = zk.create('/test/aaaa')

Properties:

    >>> properties = zk.properties('/test')
    >>> @properties
    ... def props(c):
    ...     print c
    zc.zk.Properties(/test)

    >>> p2 = zk.properties('/test')
    >>> del properties
    >>> p2['a'] = 1
    zc.zk.Properties(/test)
    >>> del props
    >>> p2['a'] += 1

    >>> @zk.properties('/test')
    ... def props(c):
    ...     print c
    zc.zk.Properties(/test)

    >>> p2['a'] += 1
    zc.zk.Properties(/test)
    >>> del props

    >>> p2['a'] += 1

    >>> zk.close()
    """

def test_deleted_node_with_watchers():
    """

Set up some handlers.

    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> _ = zk.create('/test', '{"a": 1}', zc.zk.OPEN_ACL_UNSAFE)

    >>> children = zk.children('/test')
    >>> @children
    ... def _(arg):
    ...     print 1, list(arg)
    1 []

    >>> @children
    ... def _(arg=None):
    ...     print 2, arg
    2 zc.zk.Children(/test)

    >>> _ = zk.create('/test/a', '', zc.zk.OPEN_ACL_UNSAFE)
    1 ['a']
    2 zc.zk.Children(/test)

    >>> _ = zk.delete('/test/a')
    1 []
    2 zc.zk.Children(/test)

    >>> properties = zk.properties('/test')
    >>> @properties
    ... def _(arg):
    ...     print 3, dict(arg)
    3 {u'a': 1}

    >>> @properties
    ... def _(arg=None):
    ...     print 4, arg
    4 zc.zk.Properties(/test)

    >>> _ = zk.set('/test', '{"b": 2}')
    3 {u'b': 2}
    4 zc.zk.Properties(/test)

Hack data into the child watcher to verify it's cleared:

    >>> children.data = 'data'

Now delete the node.  The handlers that accept no arguments will be called:

    >>> _ = zk.delete('/test')
    4 None
    2 None

Note that the handlers that accept 0 arguments were called.

And the data are cleared:

    >>> list(children), list(properties)
    ([], [])

    >>> zk.close()
    """


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
    in expression: '1+' in line 3

    >>> zk.import_tree('''
    ... /test
    ...   a ->
    ... ''') # doctest: +NORMALIZE_WHITESPACE
    Traceback (most recent call last):
    ...
    ValueError: (3, 'a ->', 'Bad link format')

    >>> zk.close()
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

    >>> zk.close()
    """

def property_set_and_update_variations():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> data = zk.properties('/fooservice')
    >>> @data
    ... def _(data):
    ...     pprint(dict(data), width=70)
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

    >>> zk.close()
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

    >>> zk.register('/top/a/top/a/b/top/a/b/c/top/a/b/c/d', 'addr')
    >>> sorted(map(str, zk.children('/top/a/top/a/b/top/a/b/c/top/a/b/c/d')))
    ['addr', 'e']

    >>> zk.resolve('/top/a/top/a/b/top/x')
    Traceback (most recent call last):
    ...
    NoNodeError: /top/a/top/a/b/top/x

    >>> zk.resolve('/top/a/b/c/d/loop')
    Traceback (most recent call last):
    ...
    LinkLoop: ('/top/a/b/c/d/loop', u'/top/a/b/c/d/loop')

    >>> zk.resolve('/top/a/loop/b/c/d')
    Traceback (most recent call last):
    ...
    LinkLoop: ('/top/a/loop', u'/top/a/b/loop', u'/top/a/loop')

    >>> zk.resolve('/top/a/b/c/d/./../..')
    '/top/a/b'

    >>> zk.close()
    """

def test_ln_target_w_trailing_slash():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.ln('/databases/main', '/fooservice/')
    >>> pprint(zk.get_properties('/fooservice'))
    {u' ->': u'/databases/main',
     u'database': u'/databases/foomain',
     u'favorite_color': u'red',
     u'threads': 1}

    >>> zk.close()
    """

def test_export_top_w_name():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> print zk.export_tree('/', name='top'),
    /top
      /fooservice
        database = u'/databases/foomain'
        favorite_color = u'red'
        threads = 1
        /providers

    >>> zk.close()
    """

def test_server_registeration_event():
    """
    >>> import sys, zc.zk.event, zope.event
    >>> zc.zk.event.notify is zope.event.notify
    True
    >>> sys.modules['zope.event'] = None
    >>> _ = reload(zc.zk.event)
    >>> zc.zk.event.notify is zope.event.notify
    False
    >>> zc.zk.event.notify is zc.zk.event._noop
    True
    >>> def notify(e):
    ...     print e
    ...     e.properties['test'] = 1
    >>> zc.zk.event.notify = notify

    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.register('/fooservice/providers', '1.2.3.4:5678')
    RegisteringServer('1.2.3.4:5678', '/fooservice/providers', {'pid': 1793})

    >>> zk.print_tree('/fooservice/providers')
    /providers
      /1.2.3.4:5678
        pid = 9999
        test = 1

    >>> zk.close()

    >>> sys.modules['zope.event'] = zope.event
    >>> _ = reload(zc.zk.event)
    >>> zc.zk.event.notify is zope.event.notify
    True
    """

def register_at_root():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.register('/', 'a:b')
    >>> zk.print_tree() # doctest: +ELLIPSIS
    /a:b
      pid = 9999
    /fooservice
    ...
    >>> zk.close()
    """

relative_property_links_data = """

/a
  /b
    x => c x
    xx => ./c x
    x2 => .. x
    x3 => ../c x
    x22 => ./.. x
    x33 => ./../c x
    x333 => .././c x
    /c
      x=1
  /c
    x = 3
  x = 2

"""
def relative_property_links():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.import_tree(relative_property_links_data)
    >>> p = zk.properties('/a/b')
    >>> p['x']
    1
    >>> p['xx']
    1
    >>> p['x2']
    2
    >>> p['x22']
    2
    >>> p['x3']
    3
    >>> p['x33']
    3
    >>> p['x333']
    3
    >>> zk.close()
    """

def property_links_expand_callbacks_to_linked_nodes():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.import_tree('''
    ... /a
    ...   /b
    ...     x => c
    ...     xx => ../c
    ...     /c
    ...       x = 1
    ...   /c
    ...     x = 2
    ... ''')

    >>> ab = zk.properties('/a/b')

    >>> @ab
    ... def _(properties):
    ...     print 'updated'
    updated

    >>> ac = zk.properties('/a/c')
    >>> ac.update(x=3)
    updated

    >>> ab.update(xx=2)
    updated

    >>> ac.update(x=4)

    >>> zk.close()
    """

def bad_links_are_reported_and_prevent_updates():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> properties = zk.properties('/fooservice')

    >>> properties.update({'c =>': '/a/b/c d'}, a=1, b=2, d=3, e=4)
    ... # doctest: +NORMALIZE_WHITESPACE
    Traceback (most recent call last):
    ...
    ValueError: ('Bad property link', 'c =>', '/a/b/c d',
    NoNodeError('/a/b/c',))
    >>> pprint(dict(properties), width=70)
    {u'database': u'/databases/foomain',
     u'favorite_color': u'red',
     u'threads': 1}

    >>> properties.update({'c =>': ''}, a=1, b=2, d=3, e=4)
    ... # doctest: +NORMALIZE_WHITESPACE
    Traceback (most recent call last):
    ...
    ValueError: ('Bad property link', 'c =>', '',
    ValueError('Bad link data',))
    >>> pprint(dict(properties), width=70)
    {u'database': u'/databases/foomain',
     u'favorite_color': u'red',
     u'threads': 1}

    >>> properties.update({'c =>': '/fooservice x'}, a=1, b=2, d=3, e=4)
    Traceback (most recent call last):
    ...
    ValueError: ('Bad property link', 'c =>', '/fooservice x', KeyError('x',))
    >>> pprint(dict(properties), width=70)
    {u'database': u'/databases/foomain',
     u'favorite_color': u'red',
     u'threads': 1}

    >>> properties.update({'c =>': '/fooservice threads x'}, a=1, b=2, d=3, e=4)
    ... # doctest: +NORMALIZE_WHITESPACE
    Traceback (most recent call last):
    ...
    ValueError: ('Bad property link', 'c =>', '/fooservice threads x',
    ValueError('Bad link data',))
    >>> pprint(dict(properties), width=70)
    {u'database': u'/databases/foomain',
     u'favorite_color': u'red',
     u'threads': 1}

    >>> properties.set({'c =>': '/a/b/c d'}, a=1, b=2, d=3, e=4)
    ... # doctest: +NORMALIZE_WHITESPACE
    Traceback (most recent call last):
    ...
    ValueError: ('Bad property link', 'c =>', '/a/b/c d',
    NoNodeError('/a/b/c',))
    >>> pprint(dict(properties), width=70)
    {u'database': u'/databases/foomain',
     u'favorite_color': u'red',
     u'threads': 1}

    >>> properties.set({'c =>': ''}, a=1, b=2, d=3, e=4)
    Traceback (most recent call last):
    ...
    ValueError: ('Bad property link', 'c =>', '', ValueError('Bad link data',))
    >>> pprint(dict(properties), width=70)
    {u'database': u'/databases/foomain',
     u'favorite_color': u'red',
     u'threads': 1}

    >>> zk.close()
    """

def contains_w_property_link():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> properties = zk.properties('/fooservice/providers')
    >>> properties.update({'c =>': '.. threads'})
    >>> 'c' in properties
    True

    >>> zk.close()
    """

def property_getitem_error_handling():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> _ = zk.set('/fooservice/providers', json.dumps({
    ... 'a =>': '/a/b',
    ... 'b =>': '/fooservice threads x',
    ... 'c =>': '',
    ... }))
    >>> properties = zk.properties('/fooservice/providers')
    >>> properties['a']
    Traceback (most recent call last):
    ...
    BadPropertyLink: (NoNodeError(u'/a/b',), "in 'a =>': u'/a/b'")
    >>> properties['b'] # doctest: +NORMALIZE_WHITESPACE
    Traceback (most recent call last):
    ...
    BadPropertyLink: (ValueError('Invalid property link',),
    "in 'b =>': u'/fooservice threads x'")
    >>> properties['c']
    Traceback (most recent call last):
    ...
    BadPropertyLink: (IndexError('pop from empty list',), "in 'c =>': u''")

    >>> zk.close()
    """

def property_link_loops():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.import_tree('''
    ... /a
    ...   x => ../b x
    ... /b
    ...   x => ../a x
    ... ''')
    >>> properties = zk.properties('/a')
    >>> properties['x'] # doctest: +NORMALIZE_WHITESPACE
    Traceback (most recent call last):
    ...
    BadPropertyLink:
    (BadPropertyLink(BadPropertyLink(LinkLoop((u'/b', u'/a', u'/b'),),
    "in u'x =>': u'../b x'"), "in u'x =>': u'../a x'"), "in 'x =>': u'../b x'")

    >>> zk.close()
    """

def deleting_linked_nodes():
    """
    Links are reestablished after deleting a linked node.

    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.import_tree('''
    ... /a
    ...   /b
    ...     x => ../c
    ...   /c
    ...     x = 1
    ... ''')

    >>> ab = zk.properties('/a/b')

    >>> @ab
    ... def _(properties):
    ...     print 'updated'
    updated

    >>> ab['x']
    1

    >>> zk.import_tree('''
    ... /d
    ...   x = 2
    ... ''')

    >>> _ = zk.set('/a', '{"c ->": "/d"}')
    >>> _ = zk.delete('/a/c')
    updated
    >>> ab['x']
    2

    >>> zk.close()
    """

def delete_recursive_dry_run():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.delete_recursive('/fooservice', dry_run=True)
    would delete /fooservice/providers.
    would delete /fooservice.

    >>> zk.print_tree()
    /fooservice
      database = u'/databases/foomain'
      favorite_color = u'red'
      threads = 1
      /providers

    >>> zk.close()
    """

def delete_recursive_force():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.register('/fooservice/providers', 'a:b')

    >>> zk.delete_recursive('/fooservice', dry_run=True, force=True)
    would delete /fooservice/providers/a:b.
    would delete /fooservice/providers.
    would delete /fooservice.

    >>> zk.print_tree()
    /fooservice
      database = u'/databases/foomain'
      favorite_color = u'red'
      threads = 1
      /providers
        /a:b
          pid = 9999

    >>> zk.delete_recursive('/fooservice', force=True)

    >>> zk.print_tree()
    <BLANKLINE>

    >>> zk.close()
    """

def is_ephemeral():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.register('/fooservice/providers', 'a:b')
    >>> zk.is_ephemeral('/fooservice')
    False
    >>> zk.is_ephemeral('/fooservice/providers')
    False
    >>> zk.is_ephemeral('/fooservice/providers/a:b')
    True
    >>> zk.close()
    """

def property_links_edge_cases():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.import_tree('''
    ... /app
    ...   threads => ..
    ...   color = 'red'
    ...   database -> /databases/foo
    ... ''', '/fooservice')
    >>> zk.print_tree()
    /fooservice
      database = u'/databases/foomain'
      favorite_color = u'red'
      threads = 1
      /app
        color = u'red'
        threads => = u'..'
        database -> /databases/foo
      /providers

    >>> properties = zk.properties('/fooservice/app')
    >>> sorted(properties)
    [u'color', u'database ->', u'threads']

    >>> sorted(properties.keys())
    [u'color', u'database ->', u'threads']

    >>> sorted(properties.values())
    [1, u'/databases/foo', u'red']

    >>> sorted(properties.items())
    [(u'color', u'red'), (u'database ->', u'/databases/foo'), (u'threads', 1)]

    >>> pprint(dict(properties))
    {u'color': u'red', u'database ->': u'/databases/foo', u'threads': 1}

    >>> zk.close()
    """

def no_spam_when_not_trimming_ephemeral_nodes():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.print_tree()
    /fooservice
      database = u'/databases/foomain'
      favorite_color = u'red'
      threads = 1
      /providers

    >>> zk.register('/fooservice/providers', 'a:a')
    >>> zk.print_tree()
    /fooservice
      database = u'/databases/foomain'
      favorite_color = u'red'
      threads = 1
      /providers
        /a:a
          pid = 9999

    >>> zk.import_tree('''
    ... /fooservice
    ...   database = u'/databases/foomain'
    ...   favorite_color = u'red'
    ...   threads = 1
    ...   /providers
    ... ''', trim=True)

    >>> zk.close()
    """

def cant_import_top_level_properties():
    r"""
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.import_tree('x = 1')
    Traceback (most recent call last):
    ...
    ValueError: Can't import properties above imported nodes.
    >>> zk.import_tree('/y\nx = 1')
    Traceback (most recent call last):
    ...
    ValueError: Can't import properties above imported nodes.
    """

connected_addrs = {
    'eth0': {2: [{'addr': '192.168.24.60',
                  'broadcast': '192.168.24.255',
                  'netmask': '255.255.255.0'}],
             10: [{'addr': 'fe80::21c:c0ff:fe1a:d12%eth0',
                   'netmask': 'ffff:ffff:ffff:ffff::'}],
             17: [{'addr': '00:1c:c0:1a:0d:12',
                   'broadcast': 'ff:ff:ff:ff:ff:ff'}]},
    'foo': {2: [{'addr': '192.168.24.61',
                 'broadcast': '192.168.24.255',
                 'netmask': '255.255.255.0'}],
            },
    'lo': {2: [{'addr': '127.0.0.1',
                'netmask': '255.0.0.0',
                'peer': '127.0.0.1'}],
           10: [{'addr': '::1',
                 'netmask': 'ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff'}],
           17: [{'addr': '00:00:00:00:00:00',
                 'peer': '00:00:00:00:00:00'}],
           },
    }
def blank_host_netifaces_connected():
    r"""
    If netifaces can be imported and we're connected to a network,
    then non-local interfaces will be registered when calling
    register:

    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> with mock.patch('netifaces.ifaddresses',
    ...                  side_effect=lambda iface: connected_addrs[iface]):
    ...   with mock.patch('netifaces.interfaces',
    ...                   side_effect=lambda : list(connected_addrs)):
    ...     zk.register('/fooservice/providers', ':8080')
    ...     zk.register('/fooservice/providers', ('', 8081))

    >>> zk.print_tree('/fooservice/providers')
    /providers
      /192.168.24.60:8080
        pid = 9999
      /192.168.24.60:8081
        pid = 9999
      /192.168.24.61:8080
        pid = 9999
      /192.168.24.61:8081
        pid = 9999

    >>> zk.close()
    """

def blank_host_nonetifaces():
    r"""
    If netifaces can't be imported, we use socket.fqdn:

    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')

    >>> import netifaces
    >>> netifaces = sys.modules['netifaces']
    >>> try:
    ...     sys.modules['netifaces'] = None
    ...     with mock.patch('socket.getfqdn',
    ...                      side_effect=lambda : 'service.example.com'):
    ...       zk.register('/fooservice/providers', ':8080')
    ...       zk.register('/fooservice/providers', ('', 8081))
    ... finally:
    ...     sys.modules['netifaces'] = netifaces

    >>> zk.print_tree('/fooservice/providers')
    /providers
      /service.example.com:8080
        pid = 9999
      /service.example.com:8081
        pid = 9999

    >>> zk.close()
    """

def test_special_values():
    r"""
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> props = zk.properties('/fooservice')

    >>> _ = zk.set('/fooservice', ''); print dict(props)
    {}

    >>> _ = zk.set('/fooservice', 'xxx'); print dict(props)
    {'string_value': 'xxx'}
    >>> _ = zk.set('/fooservice', '{xxx}'); print dict(props)
    {'string_value': '{xxx}'}
    >>> _ = zk.set('/fooservice', '\n{xxx}\n'); print dict(props)
    {'string_value': '\n{xxx}\n'}

    >>> props.set(b=2); print zk.get('/fooservice')[0]
    {"b":2}
    >>> props.set(); print zk.get('/fooservice')[0]
    {}
    >>> props.set(string_value='xxx'); print zk.get('/fooservice')[0]
    xxx

    >>> zk.close()
    """

def test_property_loops():
    r"""
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.import_tree('''
    ... /x
    ...   a = 1
    ...   b => ../y
    ... /y
    ...   a => ../x
    ...   b = 2
    ... ''')
    >>> logger = zklogger()
    >>> props = zk.properties('/x')
    >>> sorted(props.items())
    [(u'a', 1), (u'b', 2)]

    >>> zk.close()
    >>> logger.uninstall()
    """

def test_existing_client():
    r"""

    You can use an existing kazoo client:

    >>> import kazoo.client
    >>> client = kazoo.client.KazooClient('zookeeper.example.com:2181')
    >>> zk = zc.zk.ZooKeeper(client)
    >>> zk.client is client
    True

You have to start the client yourself:

    >>> try: zk.print_tree()
    ... except Exception: pass
    ... else: print 'oops'

    >>> client.start()

    >>> zk.print_tree()
    /fooservice
      database = u'/databases/foomain'
      favorite_color = u'red'
      threads = 1
      /providers

Closing doesn't close the client:

    >>> zk.close()

    >>> sorted(client.get_children('/'))
    [u'fooservice', u'zookeeper']

    >>> client.stop()
    >>> client.close()
    """

def test_register_server():
    """The older register_server name is preserved for backward compatibility.

    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.register_server('/fooservice', 'test:1')
    >>> zk.print_tree()
    /fooservice
      database = u'/databases/foomain'
      favorite_color = u'red'
      threads = 1
      /providers
      /test:1
        pid = 9999
    >>> zk.close()
    """

def no_error_calling_close_more_than_once():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.close()
    >>> zk.close()
    >>> zk.close()
    """

def backward_compatible_create_recursive():
    """
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    >>> zk.create_recursive(
    ...     '/fooservice/bas/boo', '{"a": 1}', zc.zk.READ_ACL_UNSAFE)
    >>> zk.print_tree()
    /fooservice
      database = u'/databases/foomain'
      favorite_color = u'red'
      threads = 1
      /bas
        /boo
          a = 1
      /providers

    >>> zk.client.get_acls('/fooservice/bas/boo')[0] == zc.zk.READ_ACL_UNSAFE
    True

    >>> zk.close()
    """

event = threading.Event()
def check_async(show=True, expected_status=0):
    event.clear()
    def check(handle, status, *args):
        if show:
            print 'async callback got', args
        event.set()
        zc.zk.testing.assert_(
            status==expected_status,
            "Bad cb status %s" % status,
            error=False)
    return check

def setUpEphemeral_node_recovery_on_session_reestablishment(test):
    zc.zk.testing.setUp(test)
    test.globs['check_async'] = check_async
    test.globs['event'] = event

def setUpREADME(test):
    zc.zk.testing.setUp(test)
    @side_effect(setupstack.context_manager(test, mock.patch('socket.getfqdn')))
    def getfqdn():
        return 'socket.getfqdn'

def disconnectiontestsSetup(test):
    zc.zk.testing.setUp(test)

checker = zope.testing.renormalizing.RENormalizing([
    (re.compile('pid = \d+'), 'pid = 9999'),
    (re.compile("{'pid': \d+}"), 'pid = 9999'),
    (re.compile('/zc\.zk\.testing\.test-root\d+'), ''),
    (re.compile(r'2 None\n4 None'), '4 None\n2 None'),
    ])

def test_suite():
    suite = unittest.TestSuite((
        manuel.testing.TestSuite(
            manuel.doctest.Manuel(
                checker=checker, optionflags=doctest.NORMALIZE_WHITESPACE) +
            manuel.capture.Manuel(),
            'README.txt',
            setUp=setUpREADME, tearDown=zc.zk.testing.tearDown,
            ),
        doctest.DocTestSuite(
            setUp=zc.zk.testing.setUp, tearDown=zc.zk.testing.tearDown,
            checker=checker,
            ),
        doctest.DocFileSuite(
            'monitor.test',
            checker = zope.testing.renormalizing.RENormalizing([
                (re.compile(':\d+'), ':9999'),
                ])
            ),
        ))
    if not zc.zk.testing.testing_with_real_zookeeper():
        suite.addTest(doctest.DocFileSuite(
            'ephemeral_node_recovery_on_session_reestablishment.test',
            setUp=setUpEphemeral_node_recovery_on_session_reestablishment,
            tearDown=zc.zk.testing.tearDown,
            checker=checker,
            ))
        suite.addTest(doctest.DocTestSuite(
            'zc.zk.disconnectiontests',
            setUp=disconnectiontestsSetup, tearDown=zc.zk.testing.tearDown,
            checker=checker,
            ))
        suite.addTest(doctest.DocTestSuite(
            'zc.zk.testing',
            setUp=zc.zk.testing.setUp, tearDown=zc.zk.testing.tearDown,
            checker=checker,
            )),

    return suite
