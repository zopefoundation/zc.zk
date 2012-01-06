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

def wait_for_zookeeper():
    """
    Normally, zc.zk.ZooKeeper raises an exception if it can't connect to
    ZooKeeper in a second.  Some applications might want to wait, so
    zc.zk.ZooKeeper accepts a wait parameter that causes it to wait for a
    connection.

    >>> zk = None
    >>> import zc.zk, zc.thread, zookeeper, zope.testing.loggingsupport

    >>> handler = zope.testing.loggingsupport.InstalledHandler('zc.zk')

    >>> @zc.thread.Thread
    ... def connect():
    ...     global zk
    ...     zk = zc.zk.ZooKeeper('Invalid', wait=True)

    We'll wait a while while it tries in vane to connect:

    >>> wait_until((lambda : zk is not None), 4)
    Traceback (most recent call last):
    ...
    AssertionError: timeout

    >>> print handler # doctest: +ELLIPSIS
    zc.zk CRITICAL
      Can't connect to ZooKeeper at 'Invalid'
    zc.zk CRITICAL
      Can't connect to ZooKeeper at 'Invalid'
    ...
    >>> handler.uninstall()

    Now, we'll make the connection possible:

    >>> ZooKeeper._allow_connection('Invalid')
    >>> wait_until(lambda : zk is not None)

    >>> zk.state == zookeeper.CONNECTED_STATE
    True

    Yay!

    >>> zk.close()
    """

