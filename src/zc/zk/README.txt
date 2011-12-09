========================
High-level ZooKeeper API
========================

The zc.zk package provides some high-level interfaces to the low-level
zookeeper extension.  It's not complete, in that it doesn't try, at
this time, to be a complete high-level interface. Rather, it provides
facilities we need to use ZooKeeper to connect services:

- ZODB database clients and servers
- HTTP-based clients and services
- Load balancers and HTTP application servers

The current (initial) use cases are:

- Register a server providing a service.
- Get the addresses of servers providing a service.
- Get and set service configuration data.
- Model system architecture as a tree.

This package makes no effort to support Windows.  (Patches to support
Windows might be accepted if they don't add much complexity.)

.. contents::

Installation
============

You can install this as you would any other distribution. Note,
however, that you must also install the Python ZooKeeper binding
provided with ZooKeeper.  Because this binding is packaged a number of
different ways, it isn't listed as a distribution requirement.

An easy way to get the Python zookeeper binding is by installing
``zc-zookeeper-static``, which is a self-contained statically built
distribution.

Instantiating a ZooKeeper helper
================================

To use the helper API, create a ZooKeeper instance::

    >>> import zc.zk
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')

The ZooKeeper constructor takes a ZooKeeper connection string, which is a
comma-separated list of addresses of the form *HOST:PORT*.  It defaults
to ``'127.0.0.1:2181'``, which is convenient during development.

Register a server providing a service
=====================================

To register a server, use the ``register_server`` method, which takes
a service path and the address a server is listing on::

    >>> zk.register_server('/fooservice/providers', ('192.168.0.42', 8080))

.. test

   >>> import os
   >>> zk.get_properties('/fooservice/providers/192.168.0.42:8080'
   ...                   ) == dict(pid=os.getpid())
   True


``register_server`` creates a read-only ephemeral ZooKeeper node as a
child of the given service path.  The name of the new node is (a
string representation of) the given address. This allows clients to
get the list of addresses by just getting the list of the names of
children of the service path.

Ephemeral nodes have the useful property that they're automatically
removed when a ZooKeeper session is closed or when the process
containing it dies.  De-registration is automatic.

When registering a server, you can optionally provide server (node)
data as additional keyword arguments to register_server.  By default,
the process id is set as the ``pid`` property.  This is useful to
tracking down the server process.

Get the addresses of service providers
======================================

Getting the addresses providing a service is accomplished by getting the
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

You can also get the number of children with ``len``:

    >>> len(addresses)
    2

You can call the iterable with a callback function that is called
whenever the list of children changes::

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

Get service configuration data
==============================

You get service configuration data by getting properties associated with a
ZooKeeper node.  The interface for getting properties is similar to the
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
as function decorators to get update notification::

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

Updating node properties
========================

You can't set properties, but you can update properties by calling the
``update`` method::

    >>> thread_info = {'threads': 2}
    >>> data.update(thread_info, secret='123')
    data updated
    database: u'/databases/foomain'
    favorite_color: u'red'
    secret: u'123'
    threads: 2

or by calling the ``set`` method, which removes keys not listed::

    >>> data.set(threads= 3, secret='1234')
    data updated
    secret: u'1234'
    threads: 3

Both ``update`` and ``set`` can take data from a positional data argument, or
from keyword parameters.  Keyword parameters take precedent over the
positional data argument.

Tree-definition format, import, and export
==========================================

You can describe a ZooKeeper tree using a textual tree
representation. You can then populate the tree by importing the
representation.  Heres an example::

  /lb : ipvs
    /pools
      /cms
        # The address is fixed because it's
        # exposed externally
        address = '1.2.3.4:80'
        providers -> /cms/providers
      /retail
        address = '1.2.3.5:80'
        providers -> /cms/providers

  /cms : z4m cms
    threads = 3
    /providers
    /databases
      /main
        /providers

  /retail : z4m retail
    threads = 1
    /providers
    /databases
      main -> /cms/databases/main
      /ugc
        /providers

.. -> tree_text

This example defines a tree with 3 top nodes, ``lb`` and ``cms``, and
``retail``.  The ``retail`` node has two sub-nodes, ``providers`` and
``databases`` and a property ``threads``.

The ``/retail/databases`` node has symbolic link, ``main`` and a
``ugc`` sub-node.  The symbolic link is implemented as a property named
`` We'll say more about symbolic links in a later section.

The ``lb``, ``cms`` and ``retail`` nodes have *types*.  A type is
indicated by following a node name with a colon and a string value.
The string value is used to populate a ``type`` property.  Types are
useful to document the kinds of services provided at a node and can be
used by deployment tools to deploy service providers.

You can import a tree definition with the ``import_tree`` method::

    >>> zk.import_tree(tree_text)

This imports the tree at the top of the ZooKeeper tree.

We can also export a ZooKeeper tree::

    >>> print zk.export_tree(),
    /cms : z4m cms
      threads = 3
      /databases
        /main
          /providers
      /providers
    /fooservice
      secret = u'1234'
      threads = 3
      /providers
    /lb : ipvs
      /pools
        /cms
          address = u'1.2.3.4:80'
          providers -> /cms/providers
        /retail
          address = u'1.2.3.5:80'
          providers -> /cms/providers
    /retail : z4m retail
      threads = 1
      /databases
        main -> /cms/databases/main
        /ugc
          /providers
      /providers

Note that when we export a tree:

- The special reserved top-level zookeeper node is omitted.
- Ephemeral nodes are omitted.
- Each node's information is sorted by type (properties, then links,
- then sub-nodes) and then by name,

You can export just a portion of a tree::

    >>> print zk.export_tree('/fooservice'),
    /fooservice
      secret = u'1234'
      threads = 3
      /providers

You can optionally see ephemeral nodes::

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

  /lb : ipvs
    /pools
      /cms
        # The address is fixed because it's
        # exposed externally
        address = '1.2.3.4:80'
        providers -> /cms/providers

  /cms : z4m cms
    threads = 4
    /providers
    /databases
      /main
        /providers

.. -> tree_text

and re-import::

    >>> zk.import_tree(tree_text)
    extra path not trimmed: /lb/pools/retail

We got a warning about nodes left over from the old tree.  We can see
this if we look at the tree::

    >>> print zk.export_tree(),
    /cms : z4m cms
      threads = 4
      /databases
        /main
          /providers
      /providers
    /fooservice
      secret = u'1234'
      threads = 3
      /providers
    /lb : ipvs
      /pools
        /cms
          address = u'1.2.3.4:80'
          providers -> /cms/providers
        /retail
          address = u'1.2.3.5:80'
          providers -> /cms/providers
    /retail : z4m retail
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

That's what we'd expect, so we go ahead::

    >>> zk.import_tree(tree_text, trim=True)
    >>> print zk.export_tree(),
    /cms : z4m cms
      threads = 4
      /databases
        /main
          /providers
      /providers
    /fooservice
      secret = u'1234'
      threads = 3
      /providers
    /lb : ipvs
      /pools
        /cms
          address = u'1.2.3.4:80'
          providers -> /cms/providers
    /retail : z4m retail
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

Recursive deletion
==================

ZooKeeper only allows deletion of nodes without children.
The ``delete_recursive`` method automates removing a node and all of
it's children.

If we want to remove the ``retail`` top-level node, we can use
delete_recursive::

    >>> zk.delete_recursive('/retail')
    >>> print zk.export_tree(),
    /cms : z4m cms
      threads = 4
      /databases
        /main
          /providers
      /providers
    /fooservice
      secret = u'1234'
      threads = 3
      /providers
    /lb : ipvs
      /pools
        /cms
          address = u'1.2.3.4:80'
          providers -> /cms/providers

You can't delete nodes ephemeral nodes, or nodes that contain them::

    >>> zk.delete_recursive('/fooservice')
    Not deleting /fooservice/providers/192.168.0.42:8080 because it's ephemeral.
    Not deleting /fooservice/providers/192.168.0.42:8081 because it's ephemeral.
    Not deleting /fooservice/providers/192.168.0.42:8082 because it's ephemeral.
    /fooservice/providers not deleted due to ephemeral descendent.
    /fooservice not deleted due to ephemeral descendent.

Symbolic links
==============

ZooKeeper doesn't have a concept of symbolic links, but ``zc.zk``
provides a convention for dealing with symbolic links.  When trying to
resolve a path, if a node lacks a child, but have a property with a
name ending in ``' ->'``, the child will be found by following the
path in the property value.

The ``resolve`` method is used to resolve a path to a real path::

    >>> zk.resolve('/lb/pools/cms/providers')
    u'/cms/providers'

In this example, the link was at the endpoint of the virtual path, but
it could be anywhere::

    >>> zk.register_server('/cms/providers', '1.2.3.4:5')
    >>> zk.resolve('/lb/pools/cms/providers/1.2.3.4:5')
    u'/cms/providers/1.2.3.4:5'

Note a limitation of symbolic links is that they can be hidden by
children.  For example, if we added a real node, at
``/lb/pools/cms/provioders``, it would shadow the link.

``children``, ``properties``, and ``register_server`` will
automatically use ``resolve`` to resolve paths.

When the ``children`` and ``properties`` are used for a node, the
paths they use will be adjusted dynamically when paths are removed.
To illustrate this, let's get children of ``/cms/databases/main``::

    >>> main_children = zk.children('/cms/databases/main')
    >>> main_children.path
    '/cms/databases/main'
    >>> main_children.real_path
    '/cms/databases/main'

.. test

    >>> main_properties = zk.properties('/cms/databases/main')
    >>> main_properties.path
    '/cms/databases/main'
    >>> main_properties.real_path
    '/cms/databases/main'

``Children`` and ``Properties`` objects have a ``path`` attribute that
has the value passed to the ``children`` or ``properties``
methods. They have a ``real_path`` attribute that contains the path
after resolving symbolic links.  Let's suppose we want to move the
database node to '/databases/cms'.  First we'll export it::

    >>> export = zk.export_tree('/cms/databases/main', name='cms')
    >>> print export,
    /cms
      /providers

Note that we used the export ``name`` option to specify a new name for
the exported tree.

Now, we'll create a databases node::

    >>> zk.create('/databases', '', zc.zk.OPEN_ACL_UNSAFE)
    '/databases'

And import the export::

    >>> zk.import_tree(export, '/databases')
    >>> print zk.export_tree('/databases'),
    /databases
      /cms
        /providers

Next, we'll create a symbolic link at the old location. We can use the
``ln`` convenience method::

    >>> zk.ln('/databases/cms', '/cms/databases/main')
    >>> zk.get_properties('/cms/databases')
    {u'main ->': u'/databases/cms'}

Now, we can remove ``/cms/databases/main`` and ``main_children`` will
be updated::

    >>> zk.delete_recursive('/cms/databases/main')
    >>> main_children.path
    '/cms/databases/main'
    >>> main_children.real_path
    u'/databases/cms'

.. test

    >>> main_properties.path
    '/cms/databases/main'
    >>> main_properties.real_path
    u'/databases/cms'

If we update ``/databases/cms``, ``main_children`` will see the
updates::

    >>> sorted(main_children)
    ['providers']
    >>> zk.delete('/databases/cms/providers')
    0
    >>> sorted(main_children)
    []

.. test

    >>> dict(main_properties)
    {}
    >>> zk.properties('/databases/cms').set(a=1)
    >>> dict(main_properties)
    {u'a': 1}

Node deletion
=============

If a node is deleted and ``Children`` or ``Properties`` instances have
been created for it, and the paths they were created with can't be
resolved using symbolic links, then the instances' data will be
cleared.  Attempts to update properties will fail.  If callbacks have
been registered, they will be called without arguments, if possible.
It would be bad, in practice, to remove a node that processes are
watching.

ZooKeeper Session Management
============================

``zc.zk`` takes care of ZooKeeper session management for you. It
establishes and, if necessary, reestablishes sessions for you.  In
particular, it takes care of reestablishing ZooKeeper watches and
ephemeral nodes when a session is reestablished.

Note
  To reestablish ephemeral nodes, it's necessary for ``zc.zk`` to
  track node-moderation operations, so you have to access the
  ZooKeeper APIs through the `zc.zk.ZooKeeper`_ object, rather than
  using the low-level extension directly.

ZooKeeper logging
=================

``zc.zk`` bridges the low-level ZooKeeper logging API and the Python
logging API.  ZooKeeper log messages are forwarded to the Python
``'ZooKeeper'`` logger.

Reference
=========

zc.zk.ZooKeeper
---------------

``zc.zk.ZooKeeper(connection_string)``
    Return a new instance given a ZooKeeper connection string.

``children(path)``
   Return a `zc.zk.Children`_ for the path.

   Note that there is a fair bit of machinery in `zc.zk.Children`_
   objects to support keeping them up to date, callbacks, and cleaning
   them up when they are no-longer used.  If you only want to get the
   list of children once, use ``get_children``.

``close()``
    Close the ZooKeeper session.

    This should be called when cleanly shutting down servers to more
    quickly remove ephemeral nodes.

``delete_recursive(path[, dry_run])``
   Delete a node and all of it's sub-nodes.

   Ephemeral nodes or nodes containing them are not deleted.

   The dry_run option causes a summary of what would be deleted to be
   printed without actually deleting anything.

``export_tree(path[, ephemeral[, name]])``
    Export a tree to a text representation.

    path
      The path to export.

    ephemeral
       Boolean, defaulting to false, indicating whether to include
       ephemeral nodes in the export.  Including ephemeral nodes is
       mainly useful for visualizing the tree state.

    name
       The name to use for the top-level node.

       This is useful when using export and import to copy a tree to
       a different location and name in the hierarchy.

       Normally, when exporting the root node, ``/``, the root isn't
       included, but it is included if a name is given.

``get_children(path)``
   Get a list of the names of the children the node at the given path.

   This is more efficient than ``children`` when all you need is to
   read the list once, as it doesn't create a `zc.zk.Children`_
   object.

``get_properties(path)``
   Get the properties for the node at the given path as a dictionary.

   This is more efficient than ``properties`` when all you need is to
   read the properties once, as it doesn't create a
   `zc.zk.Properties`_ object.

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
       specified, then full access is allowed to everyone.

    dry_run
       Boolean, defaulting to false, indicating whether to do a dry
       run of the import, without applying any changes.

``ln(source, destination)``
   Create a symbolic link at the destination path pointing to the
   source path.

   If the destination path ends with ``'/'``, then the source name is
   appended to the destination.

``print_tree(path='/')``
   Print the tree at the given path.

   This is just a short-hand for::

     print zk.export_tree(path, ephemeral=True),

``properties(path)``
   Return a `zc.zk.Properties`_ for the path.

   Note that there is a fair bit of machinery in `zc.zk.Properties`_
   objects to support keeping them up to date, callbacks, and cleaning
   them up when they are no-longer used.  If you only want to get the
   properties once, use ``get_properties``.

``register_server(path, address, acl=zc.zk.READ_ACL_UNSAFE, **data)``
    Register a server at a path with the address.

    An ephemeral child node of ``path`` will be created with name equal
    to the string representation (HOST:PORT) of the given address.

    ``address`` must be a host and port tuple.

    ``acl`` is a ZooKeeper access control list.

    Optional node properties can be provided as keyword arguments.

``resolve(path)``
   Find the real path for the given path.

In addition, ``ZooKeeper`` instances provide access to the following
ZooKeeper functions as methods: ``acreate``, ``add_auth``,
``adelete``, ``aexists``, ``aget``, ``aget_acl``, ``aget_children``,
``aset``, ``aset_acl``, ``async``, ``create``, ``delete``, ``exists``,
``get``, ``get_acl``, ``is_unrecoverable``, ``recv_timeout``, ``set``,
``set2``, ``set_acl``, and ``set_watcher``.  When calling these as
methods on ``ZooKeeper`` instances, it isn't necessary to pass a
handle, as that is provided automatically.

zc.zk.Children
--------------

``__iter__()``
    Return an iterator over the child names.

``__call__(callable)``
    Register a callback to be called whenever a child node is added or
    removed.

    The callback is passed the children instance when a child node is
    added or removed.

    The ``Children`` instance is returned.

zc.zk.Properties
----------------

Properties objects provide the usual read-only mapping methods,
__getitem__, __len__, etc..

``set(data=None, **properties)``
   Set the properties for the node, replacing existing data.

   The data argument, if given, must be a dictionary or something that
   can be passed to the ``dict`` constructor.  Items supplied as
   keywords take precedence over items supplied in the data argument.

``update(data=None, **properties)``
   Update the properties for the node.

   The data argument, if given, must be a dictionary or something that
   can be passed to a dictionary's ``update`` method.  Items supplied
   as keywords take precedence over items supplied in the data
   argument.

``__call__(callable)``
    Register a callback to be called whenever a node's properties are changed.

    The callback is passed the properties instance when properties are
    changed.

    The ``Properties`` instance is returned.

Testing support
---------------

The ``zc.zk.testing`` module provides ``setUp`` and ``tearDown``
functions that can be used to emulate a ZooKeeper server. To find out
more, use the help function::

    >>> import zc.zk.testing
    >>> help(zc.zk.testing)

.. -> ignore

    >>> import zc.zk.testing


Change History
==============

0.3.0 (2011-12-??)
------------------

- Fixed bug: Ephemeral nodes weren't recreated when sessions were
  reestablished.

- Added a testing module that provides ZooKeeper emulation for
  testing complex interactions with zc.zk without needing a running
  ZooKeeper server.

- `zc.zk.Children`_ objects now have a __len__, which is mainly useful
  for testing whether they are empty.


0.2.0 (2011-12-05)
~~~~~~~~~~~~~~~~~~

- Added tree import and export.
- Added symbolic-links.
- properties set and update methods now accept positional
  mapping objects (or iterables of items) as well as keyword arguments.
- Added recursive node-deletion API.
- Added ``get_properties`` to get properties without creating watches.
- Added convenience access to low-level ZooKeeper APIs.
- Added ``OPEN_ACL_UNSAFE`` and ``READ_ACL_UNSAFE`` (in ``zc.zk``),
  which are mentioned by the ZooKeeper documentation. but not included in the
  ``zookeeper`` module.
- ``Children`` and ``Properties`` objects are now cleaned up when
  no-longer used.  Previously, they remained in memory for the life of
  the session.

0.1.0 (2011-11-27)
~~~~~~~~~~~~~~~~~~

Initial release

.. test cleanup

   >>> zk.close()
