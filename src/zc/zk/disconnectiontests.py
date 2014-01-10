##############################################################################
#
# Copyright Zope Foundation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################

# This module has tests that involve zookeeper being disconnected.

# Their in a separate module to avoid testing with a real zookeeper
# server, which we can't control (or at least don't want to work hard
# enough to control).

from pprint import pprint
from zope.testing.wait import wait
import zc.zk
import zope.testing.loggingsupport

def session_timeout_with_child_and_data_watchers():
    """

Set up a session with some watchers:

    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')

    >>> handler = zope.testing.loggingsupport.InstalledHandler('zc.zk')

    >>> properties = zk.properties('/fooservice')
    >>> @properties
    ... def changed(a):
    ...     print 'properties changed', a is properties
    properties changed True

    >>> pprint(dict(properties), width=60)
    {u'database': u'/databases/foomain',
     u'favorite_color': u'red',
     u'threads': 1}

    >>> children = zk.children('/fooservice')
    >>> @children
    ... def changed(a):
    ...     print 'children changed', a is children
    children changed True

    >>> sorted(children)
    ['providers']

Now, we'll expire the session:

    >>> handler.clear()
    >>> zk.client.lose_session()

Now, if we make changes, they'll be properly reflected:

    >>> _ = zk.set('/fooservice', '{"a": 1}')
    properties changed True

    >>> dict(properties)
    {u'a': 1}

    >>> zk.register('/fooservice', 'x')
    children changed True

    >>> sorted(children)
    ['providers', 'x']

    >>> print handler
    zc.zk INFO
      connected

    If changes are made while we're disconnected, we'll still see them:

    >>> @zk.client.lose_session
    ... def _():
    ...     zk2 = zc.zk.ZooKeeper('zookeeper.example.com:2181')
    ...     zk2.set('/fooservice', '{"test": 1}')
    ...     zk2.create('/fooservice/y')
    ...     zk2.close()
    properties changed True
    children changed True

    Our handlers were called because data changed.

    >>> dict(properties)
    {u'test': 1}
    >>> sorted(children)
    ['providers', 'x', 'y']

    >>> zk.close()
    """
