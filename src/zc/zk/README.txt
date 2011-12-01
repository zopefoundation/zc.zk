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

An easy way to get the Python zookeeper binding is by installing
``zc-zookeeper-static``, whch is a self-contained statically building
distribution.

Instantiating a ZooKeeper helper
--------------------------------

To use the helper API, create a ZooKeeper instance::

    >>> import zc.zk
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')

The ZooKeeper constructor takes a ZooKeeper connection string, which is a
comma-separated list of addresses of the form HOST:PORT.  It defaults
to '127.0.0.1:2181', which is convenient during development.

Register a server providing a service.
--------------------------------------

To register a server, use the ``register_server`` method, which takes
a service path and the address a server is listing on::

    >>> zk.register_server('/fooservice/providers', ('192.168.0.42', 8080))

.. test

   >>> import os
   >>> zc.zk.decode(ZooKeeper.get(
   ...     0, '/fooservice/providers/192.168.0.42:8080')[0]
   ...     ) == dict(pid=os.getpid())
   True


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

Get the addresses of service providers.
---------------------------------------

Getting the adresses providing a service is accomplished by getting the
children of a service node::

    >>> addresses = zk.children('/fooservice/providers')
    >>> sorted(addresses)
    ['192.168.0.42:8080']

The ``children`` method returns an iterable of names of child nodes of
the node specified by the given path.  The iterable is automatically
updated when new providers are registered::

    >>> zk.register_server('/fooservice/providers', ('192.168.0.42', 8081))
    >>> sorted(addresses)
    ['192.168.0.42:8080', '192.168.0.42:8081']

You can call the iterable with a callback function that is called
whenenever the list of children changes::

    >>> @zk.children('/fooservice/providers')
    ... def addresses_updated(addresses):
    ...     print 'addresses changed'
    ...     print sorted(addresses)
    addresses changed
    ['192.168.0.42:8080', '192.168.0.42:8081']

The callback is called immediately with the children.  When we add
another child, it'll be called again::

    >>> zk.register_server('/fooservice/providers', ('192.168.0.42', 8082))
    addresses changed
    ['192.168.0.42:8080', '192.168.0.42:8081', '192.168.0.42:8082']

Get service configuration data.
-------------------------------

You get service configuration data by getting data associated with a
ZooKeeper node.  The interface for getting data is similar to the
interface for getting children::

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
``update`` method::

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

Tree-definition format, import, and export
------------------------------------------

You can describe a ZooKeeper tree using a textual tree
representation. You can then populate the tree by importing the
representation.  Heres an example::

  /lb
    /pools
      /cms
        # The address is fixed because it's
        # exposed externally
        address = '1.2.3.4:80'
        providers -> /cms/providers
      /retail
        address = '1.2.3.5:80'
        providers -> /cms/retail

  /cms
    threads = 3
    /providers
    /databases
      /main
        /providers

  /retail
    threads = 1
    /providers
    /databases
      main -> /cms/databases/main
      /ugc
        /providers

.. -> tree_text

This example defines a tree with 3 top nodes, ``lb`` and ``cms``, and
``retail``.  The ``retail`` node has two subnodes, ``providers`` and
``databases`` and a property ``threads``.  The ``/retail/databases``
node has symbolic link, ``main`` and a ``ugc`` subnode.  The symbolic
link is implemented as a property named ``main ->``.  We'll say more
about symbolic links in a later section.

You can import a tree definition with the ``import_tree`` method:

    >>> zk.import_tree(tree_text)

This imports the tree at the top pf the ZooKeeper tree.

We can also export a ZooKeeper tree:

    >>> print zk.export_tree(),
    /cms
      threads = 3
      /databases
        /main
          /providers
      /providers
    /fooservice
      secret = u'1234'
      threads = 3
      /providers
    /lb
      /pools
        /cms
          address = u'1.2.3.4:80'
          providers -> /cms/providers
        /retail
          address = u'1.2.3.5:80'
          providers -> /cms/retail
    /retail
      threads = 1
      /databases
        main -> /cms/databases/main
        /ugc
          /providers
      /providers

Note that when we export a tree:

- The special reserverd top-level zookeeper node is omitted.
- Ephemeral nodes are ommitted.
- Each node's information is sorted by type (properties, then links,
- then subnodes) and then by name,

You can export just a portion of a tree:

    >>> print zk.export_tree('/fooservice'),
    /fooservice
      secret = u'1234'
      threads = 3
      /providers

You can optionally see ephemeral nodes:

    >>> print zk.export_tree('/fooservice', ephemeral=True),
    /fooservice
      secret = u'1234'
      threads = 3
      /providers
        /192.168.0.42:8080
          pid = 81176
        /192.168.0.42:8081
          pid = 81176
        /192.168.0.42:8082
          pid = 81176

We can import a tree over an existing tree and changes will be
applied.  Let's update our textual description::

  /lb
    /pools
      /cms
        # The address is fixed because it's
        # exposed externally
        address = '1.2.3.4:80'
        providers -> /cms/providers

  /cms
    threads = 4
    /providers
    /databases
      /main
        /providers

.. -> tree_text

and reimport::

    >>> zk.import_tree(tree_text)
    extra path not trimmed: /lb/pools/retail

We got a warning about nodes left over from the old tree.  We can see
this if we export the tree:

    >>> print zk.export_tree(),
    /cms
      threads = 4
      /databases
        /main
          /providers
      /providers
    /fooservice
      secret = u'1234'
      threads = 3
      /providers
    /lb
      /pools
        /cms
          address = u'1.2.3.4:80'
          providers -> /cms/providers
        /retail
          address = u'1.2.3.5:80'
          providers -> /cms/retail
    /retail
      threads = 1
      /databases
        main -> /cms/databases/main
        /ugc
          /providers
      /providers

If we want to trim these, we can add a ``trim`` option.  This is a
little scary, so we'll use the dry-run option to see what it's going
to do::

    >>> zk.import_tree(tree_text, trim=True, dry_run=True)
    would delete /lb/pools/retail.

That's what we'd expect, so we go ahead:

    >>> zk.import_tree(tree_text, trim=True)
    >>> print zk.export_tree(),
    /cms
      threads = 4
      /databases
        /main
          /providers
      /providers
    /fooservice
      secret = u'1234'
      threads = 3
      /providers
    /lb
      /pools
        /cms
          address = u'1.2.3.4:80'
          providers -> /cms/providers
    /retail
      threads = 1
      /databases
        main -> /cms/databases/main
        /ugc
          /providers
      /providers

Note that nodes containing (directly or recursively) ephemeral nodes
will never be trimmed.  Also node that top-level nodes are never
automatically trimmed.  So we weren't warned about the unreferenced
top-level nodes in the import.

Recursice Deletion
------------------

ZooKeeper only allows deletion of nodes without children.
The ``delete_recursive`` method automates removing a node and all of
it's children.

If we want to remove the ``retail`` top-level node, we can use
delete_recursive::

    >>> zk.delete_recursive('/retail')
    >>> print zk.export_tree(),
    /cms
      threads = 4
      /databases
        /main
          /providers
      /providers
    /fooservice
      secret = u'1234'
      threads = 3
      /providers
    /lb
      /pools
        /cms
          address = u'1.2.3.4:80'
          providers -> /cms/providers

You can't delete nodes ephemeral nodes, or nodes that contain them:

    >>> zk.delete_recursive('/fooservice')
    Not deleting /fooservice/providers/192.168.0.42:8080 because it's ephemeral.
    Not deleting /fooservice/providers/192.168.0.42:8081 because it's ephemeral.
    Not deleting /fooservice/providers/192.168.0.42:8082 because it's ephemeral.
    /fooservice/providers not deleted due to ephemeral descendent.
    /fooservice not deleted due to ephemeral descendent.


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

``import_tree(text[, path='/'[, trim[, acl[, dry_run]]]])``
    Create tree nodes by importing a textual tree representation.

    text
       A textual representation of the tree.

    path
       The path at which to create the top-level nodes.

    trim
       Boolean, defaulting to false, indicating whether nodes not in
       the textual representation should be removed.

    acl
       An access control-list to use for imported nodes.  If not
       specifuied, then full access is allowed to everyone.

    dry_run
       Boolean, defaulting to false, indicating whether to do a dry
       run of the import, without applying any changes.

``export_tree(path[, include_ephemeral])``
    Export a tree to a text representation.

    path
      The path to export.

    include_ephemeral
       Boolean, defaulting to false, indicating whether to include
       ephemeral nodes in the export.  Including ephemeral nodes is
       mainly useful for visualizing the tree state.

``delete_recursive(path[, dry_run])``
   Delete a node and all of it's subnodes.

   Ephemeral nodes or nodes containing them are not deleted.

   The dry_run option causes a summary of what would be deleted to be
   printed without actually deleting anything.

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

In addition, ``ZooKeeper`` instances provide access to the following
ZooKeeper functions as methods: ``acreate``, ``add_auth``,
``adelete``, ``aexists``, ``aget``, ``aget_acl``, ``aget_children``,
``aset``, ``aset_acl``, ``async``, ``client_id``, ``create``,
``delete``, ``exists``, ``get``, ``get_acl``, ``get_children``,
``is_unrecoverable``, ``recv_timeout``, ``set``, ``set2``,
``set_acl``, ``set_debug_level``, ``set_log_stream``, ``set_watcher``,
and ``zerror``. When calling these as methods on ``ZooKeeper``
instances, it isn't necessary to pass a handle, as that is provided
automatically.

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

0.2.0 (2011-12-??)
~~~~~~~~~~~~~~~~~~

- Added tree import and export.
- Added recursive node-deletion API.
- Added symbolic-links.
- Added convenience access to low-level ZooKeeper APIs.
- Added ``OPEN_ACL_UNSAFE`` and ``READ_ACL_UNSAFE`` (in ``zc.zk``),
  which are mentioned by the ZooKeeper docs. but not included in the
  ``zookeeper`` module.

0.1.0 (2011-11-27)
~~~~~~~~~~~~~~~~~~

Initial release
