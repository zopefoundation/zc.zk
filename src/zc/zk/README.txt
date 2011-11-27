High-level ZooKeeper API
========================

The zc.zk package provides some high-level interfaces to the low-level
zookeeper extension.  It's not complete, in that it doesn't try, at
this time, to be a complete high-level interface. Rather, it provides
facilities we need to use Zookeeeper to services together:

- ZODB database clients and servers
- HTTP-based clients and services
- Load balencers

The current (initial) use cases are:

- Register a server providing a service.
- Get the addresses of servers providing a service.
- Get abd set service configuration data.

This package makes no effort to support Windows.  (Patches to support
Windows might be accepted if they don't add much complexity.)

.. contents::

Installation
------------

You can install this as you would any other distribution. Note,
however, that you must also install the Python ZooKeeper binding
provided with ZooKeeper.  Because this binding is packaged a number of
different ways, it isn't listed as a distribution requirement.

Instantiating a ZooKeeper helper
--------------------------------

To use the helper API, create a ZooKeeper instance:

.. test

    >>> import zookeeper
    >>> @side_effect(init)
    ... def _(addr, func):
    ...     global session_watch
    ...     session_watch = func
    ...     func(0, zookeeper.SESSION_EVENT, zookeeper.CONNECTED_STATE, '')
    ...     assert_(addr=='zookeeper.example.com:2181', addr)

    >>> @side_effect(state)
    ... def _(handle):
    ...     assert_(handle==0)
    ...     return zookeeper.CONNECTED_STATE

::

    >>> import zc.zk
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')

The ZooKeeper constructor takes a ZooKeeper connection string, which is a
comma-separated list of addresses of the form HOST:PORT.  It defaults
to '127.0.0.1:2181', which is convenient during development.

Register a server providing a service.
--------------------------------------

To register a server, use the ``register_server`` method, which takes
a service path and the address a server is listing on

.. test

    >>> import os, json, zookeeper
    >>> path = '/fooservice/servers'
    >>> addrs = []
    >>> child_handler = None
    >>> @side_effect(create)
    ... def _(handle, path_, data, acl, flags):
    ...     assert_(handle == 0)
    ...     path_, addr = path_.rsplit('/', 1)
    ...     assert_(path_ == path)
    ...     assert_(json.loads(data) == dict(pid=os.getpid()))
    ...     addrs.append(addr)
    ...     assert_(acl == [zc.zk.world_permission()])
    ...     assert_(flags == zookeeper.EPHEMERAL)
    ...     global child_handler
    ...     if child_handler is not None:
    ...         child_handler(handle, zookeeper.CHILD_EVENT,
    ...                       zookeeper.CONNECTED_STATE, path_)
    ...         child_handler = None

::

    >>> zk.register_server('/fooservice/servers', ('192.168.0.42', 8080))


``register_server`` creates a read-only ephemeral ZooKeeper node as a
child of the given service path.  The name of the new node is the
given address. This allows clients to get the list of addresses by
just getting the list of the names of children of the service path.

Ephemeral nodes have the useful property that they're automatically
removed when a ZooKeeper session is closed or when the process
containing it dies.  De-deregistration is automatic.

When registering a server, you can optionally provide server (node)
data as additional keyword arguments to register_server.  By default,
the process id is set as the ``pid`` server key.  This is useful to
tracking down the server process.

Get the addresses of servers providing a service.
-------------------------------------------------

Getting the adresses providing a service is accomplished by getting the
children of a service node.

.. test

    >>> @side_effect(get_children)
    ... def _(handle, path, handler):
    ...     assert_(handle == 0, handle)
    ...     assert_(path == '/fooservice/servers', path)
    ...     global child_handler
    ...     child_handler = handler
    ...     return addrs

::

    >>> addresses = zk.children('/fooservice/servers')
    >>> sorted(addresses)
    ['192.168.0.42:8080']

The ``children`` method returns an iterable of names of child nodes of
the node specified by the given path.  The iterable is automatically
updated when new servers are registered::

    >>> zk.register_server('/fooservice/servers', ('192.168.0.42', 8081))
    >>> sorted(addresses)
    ['192.168.0.42:8080', '192.168.0.42:8081']

You can call the iterable with a callback function that is called
whenenever the list of children changes::

    >>> @zk.children('/fooservice/servers')
    ... def addresses_updated(addresses):
    ...     print 'addresses changed'
    ...     print sorted(addresses)
    addresses changed
    ['192.168.0.42:8080', '192.168.0.42:8081']

The callback is called immediately with the children.  When we add
another child, it'll be called again::

    >>> zk.register_server('/fooservice/servers', ('192.168.0.42', 8082))
    addresses changed
    ['192.168.0.42:8080', '192.168.0.42:8081', '192.168.0.42:8082']

Get service configuration data.
-------------------------------

You get service configuration data by getting data associated with a
ZooKeeper node.  The interface for getting data is similar to the
interface for getting children:


.. test

    >>> node_data = json.dumps(dict(
    ...     database = "/databases/foomain",
    ...     threads = 1,
    ...     favorite_color= "red"))
    >>> @side_effect(get)
    ... def _(handle, path, handler):
    ...     assert_(handle == 0)
    ...     assert_(path == '/fooservice')
    ...     global get_handler
    ...     get_handler = handler
    ...     return node_data, {}

::

    >>> data = zk.properties('/fooservice')
    >>> data['database']
    u'/databases/foomain'
    >>> data['threads']
    1

The ``properties`` method returns a mapping object that provides access to
node data.  (ZooKeeper only stores string data for nodes. ``zc.zk``
provides a higher-level data interface by storing JSON strings.)

The properties objects can be called with callback functions and used
as function decorators to get update notification:

    >>> @zk.properties('/fooservice')
    ... def data_updated(data):
    ...     print 'data updated'
    ...     for item in sorted(data.items()):
    ...         print '%s: %r' % item
    data updated
    database: u'/databases/foomain'
    favorite_color: u'red'
    threads: 1

The callback is called immediately. It'll also be called when data are
updated.

Updating node data
------------------

You can't set data properties, but you can update data by calling it's
``update`` method:

.. test

    >>> @side_effect(set)
    ... def _(handle, path, data):
    ...     global node_data
    ...     node_data = data
    ...     get_handler(handle, zookeeper.CHANGED_EVENT,
    ...                 zookeeper.CONNECTED_STATE, path)

::

    >>> data.update(threads=2, secret='123')
    data updated
    database: u'/databases/foomain'
    favorite_color: u'red'
    secret: u'123'
    threads: 2

or by calling it's ``set`` method, which removes keys not listed::

    >>> data.set(threads=3, secret='1234')
    data updated
    secret: u'1234'
    threads: 3

ZooKeeper Session Management
----------------------------

``zc.zk`` takes care of ZooKeeper session management for you. It
establishes and, if necessary, reestablishes sessions for you.  In
particular, it takes care of reestablishing ZooKeeper watches when a
session is reestablished.

ZooKeeper logging
-----------------

``zc.zk`` bridges the low-level ZooKeeper logging API and the Python
logging API.  ZooKeeper log messages are forwarded to the Python
``'ZooKeeper'`` logger.

``zc.zk.ZooKeeper``
-------------------

``zc.zk.ZooKeeper(connection_string)``
    Return a new instance given a ZooKeeper connection string.

``children(path)``
   Return a `zc.zk.Children`_ for the path.

``properties(path)``
   Return a `zc.zk.Properties`_ for the path.

``handle``
    The ZooKeeper session handle

    This attribute can be used to call the lower-level API provided by
    the ``zookeeper`` extension.

``register_server(path, address, **data)``
    Register a server at a path with the address.

    An ephemeral child node of ``path`` will be created with name equal
    to the string representation (HOST:PORT) of the given address.

    ``address`` must be a host and port tuple.

    Optional node properties can be provided as keyword arguments.

``close()``
    Close the ZooKeeper session.

    This should be called when cleanly shutting down servers to more
    quickly remove ephemeral nodes.

zc.zk.Children
--------------

``__iter__()``
    Return an iterator over the child names.

``__call__(callable)``
    Register a callback to be called whenever a child node is added or
    removed.

    The callback is passed the children instance when a child node is
    added or removed.

zc.zk.Properties
----------------

Properties objects provide the usual read-only mapping methods,
__getitem__, __len__, etc..

``set(**properties)``
   Set the properties for the node, replacing existing data.

``update(**properties)``
   Update the properties for the node.

``__call__(callable)``
    Register a callback to be called whenever a node's properties are changed.

    The callback is passed the properties instance when properties are
    changed.

Node deletion
-------------

If a node is deleted and ``Children`` or ``Properties`` instances have
been created for it, the instances' data will be cleared.  Attempts to
update properties will fail.  If callbacks have been registered, they
will be called without arguments, if possible.  It would be bad, in
practice, to remove a node that processes are watching.

Changes
-------

0.1.0 (2011-11-27)
~~~~~~~~~~~~~~~~~~

Initial release
