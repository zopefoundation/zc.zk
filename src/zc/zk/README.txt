=================================================
Service registration and discovery with ZooKeeper
=================================================

The zc.zk package provides support for registering and discovering
services with ZooKeeper. It also provides support for defining
services with a tree-based model and syncing the model with ZooKeeper.

The use cases are:

- Register a server providing a service.
- Get the addresses of servers providing a service.
- Get and set service configuration data.
- Model system architecture as a tree.

Important note for zc.zk 1.x users
  Version 2 is mostly. but not entirely backward compatible.

  Although the goal of version 1 was primarily service registration
  and discovery, it also provided a high-level ZooKeeper API.  `Kazoo
  <https://pypi.python.org/pypi/kazoo/>`_ is a much better high-level
  interface for ZooKeeper because:

  - It isn't based on the buggy ZooKeeper C interface and Python
    extension.

  - It doesn't assumne that ephemeral nodes should be reestablished
    when a session expires and is recreated.

  zc.zk 2 uses Kazoo.

This package makes no effort to support Windows.  (Patches to support
Windows might be accepted if they don't add much complexity.)

.. contents::

Installation
============

You can install this as you would any other distribution.
It requires the kazoo Python ZooKeeper interface.

Instantiating a ZooKeeper helper
================================

To use the helper API, create a ZooKeeper instance::

    >>> import zc.zk
    >>> zk = zc.zk.ZooKeeper('zookeeper.example.com:2181')

The ZooKeeper constructor takes a ZooKeeper connection string, which is a
comma-separated list of addresses of the form *HOST:PORT*.  It defaults
to ``'127.0.0.1:2181'``, which is convenient during development.

You can also pass a kazoo client object, instead of a connection string.


Register a server providing a service
=====================================

To register a server, use the ``register`` method, which takes
a service path and the address a server is listing on::

    >>> zk.register('/fooservice/providers', ('192.168.0.42', 8080))

.. test

   >>> import os
   >>> zk.get_properties('/fooservice/providers/192.168.0.42:8080'
   ...                   ) == dict(pid=os.getpid())
   True


``register`` creates a read-only ephemeral ZooKeeper node as a
child of the given service path.  The name of the new node is (a
string representation of) the given address. This allows clients to
get the list of addresses by just getting the list of the names of
children of the service path.

Ephemeral nodes have the useful property that they're automatically
removed when a ZooKeeper session is closed or when the process
containing it dies.  De-registration is automatic.

When registering a server, you can optionally provide server (node)
data as additional keyword arguments to register.  By default,
the process id is set as the ``pid`` property.  This is useful to
tracking down the server process.  In addition, an event is generated,
providing subscribers to add properties as a server is being
registered. (See `Server-registration events`_.)

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

    >>> zk.register('/fooservice/providers', ('192.168.0.42', 8081))
    >>> sorted(addresses)
    ['192.168.0.42:8080', '192.168.0.42:8081']

You can also get the number of children with ``len``::

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

    >>> zk.register('/fooservice/providers', ('192.168.0.42', 8082))
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

You can update properties by calling the ``update`` method::

    >>> thread_info = {'threads': 2}
    >>> data.update(thread_info, secret='123')
    data updated
    database: u'/databases/foomain'
    favorite_color: u'red'
    secret: u'123'
    threads: 2

You can also set individual properties:

    >>> data['threads'] = 1
    data updated
    database: u'/databases/foomain'
    favorite_color: u'red'
    secret: u'123'
    threads: 1

If you call the ``set`` method, keys not listed are removed:

    >>> data.set(threads= 3, secret='1234')
    data updated
    secret: u'1234'
    threads: 3

Both ``update`` and ``set`` can take data from a positional data argument, or
from keyword parameters.  Keyword parameters take precedent over the
positional data argument.

Getting property data without tracking changes
==============================================


Sometimes, you want to get service data, but don't want to watch for
changes. If you pass ``watch=False`` to ``properties``, Then properties
won't track changes.  In this case, you can't set callback functions,
but you can still update data.

.. test

    >>> p2 = zk.properties('/fooservice', watch=False)
    >>> sorted(p2)
    [u'secret', u'threads']
    >>> p2(lambda data: None)
    Traceback (most recent call last):
    ...
    TypeError: Can't set callbacks without watching.

    >>> p2['threads'] = 2 # doctest: +ELLIPSIS
    data updated
    ...
    threads: 2
    >>> p2.update(threads=3) # doctest: +ELLIPSIS
    data updated
    ...
    threads: 3

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
          pid = 9999
        /192.168.0.42:8081
          pid = 9999
        /192.168.0.42:8082
          pid = 9999

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

If we know we're not trimming things and want to avoid a warning, we
can use trim=False:

    >>> zk.import_tree(tree_text, trim=False)

We can see that this didn't trim by using dry-run again:

    >>> zk.import_tree(tree_text, trim=True, dry_run=True)
    would delete /lb/pools/retail.

We do want to trim, so we use trim=True:

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


Bt default, ``delete_recursive`` won't delete ephemeral nodes, or
nodes that contain them::

    >>> zk.delete_recursive('/fooservice')
    Not deleting /fooservice/providers/192.168.0.42:8080 because it's ephemeral.
    Not deleting /fooservice/providers/192.168.0.42:8081 because it's ephemeral.
    Not deleting /fooservice/providers/192.168.0.42:8082 because it's ephemeral.
    /fooservice/providers not deleted due to ephemeral descendent.
    /fooservice not deleted due to ephemeral descendent.

You can use the ``force`` option to force ephemeral nodes to be
deleted.

Symbolic links
==============

ZooKeeper doesn't have a concept of symbolic links, but ``zc.zk``
provides a convention for dealing with symbolic links.  When trying to
resolve a path, if a node lacks a child, but has a property with a
name ending in ``' ->'``, the child will be found by following the
path in the property value.

The ``resolve`` method is used to resolve a path to a real path::

    >>> zk.resolve('/lb/pools/cms/providers')
    u'/cms/providers'

In this example, the link was at the endpoint of the virtual path, but
it could be anywhere::

    >>> zk.register('/cms/providers', '1.2.3.4:5')
    >>> zk.resolve('/lb/pools/cms/providers/1.2.3.4:5')
    u'/cms/providers/1.2.3.4:5'

Note a limitation of symbolic links is that they can be hidden by
children.  For example, if we added a real node, at
``/lb/pools/cms/provioders``, it would shadow the link.

``children``, ``properties``, and ``register`` will
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

    >>> zk.create('/databases')
    u'/databases'

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
    >>> _ = zk.delete('/databases/cms/providers')
    >>> sorted(main_children)
    []

.. test

    >>> dict(main_properties)
    {}
    >>> zk.properties('/databases/cms').set(a=1)
    >>> dict(main_properties)
    {u'a': 1}

Symbolic links can be relative. If a link doesn't start with a slash,
it's interpreted relative to the node the link occurs in.  The special
names ``.`` and ``..`` have their usual meanings.

So, in::

    /a
      /b
        l -> c
        l2 -> ../c
        /c
      /c

.. -> relative_link_source

    >>> zk.import_tree(relative_link_source)
    >>> zk.resolve('/a/b/l')
    u'/a/b/c'
    >>> zk.resolve('/a/b/l2')
    u'/a/c'

    >>> zk.delete_recursive('/a')

The link at ``/a/b/l`` resolves to ``/a/b/c`` and ``/a/b/l2`` resolves
to ``/a/c``.

Property links
==============

In addition to symbolic links between nodes, you can have links
between properties.  In our earlier example, both the ``/cms`` and
``/fooservice`` nodes had ``threads`` properties::

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

If we wanted ``/cms`` to have the same ``threads`` settings, we could
use a property link::

    /cms : z4m cms
      threads => /fooservice threads
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

.. -> property_link_source

    >>> _ = zk.create('/test-propery-links', '', zc.zk.OPEN_ACL_UNSAFE)

    >>> zk.import_tree(property_link_source, '/test-propery-links')
    >>> properties = zk.properties('/test-propery-links/cms')
    >>> properties['threads =>']
    u'/fooservice threads'
    >>> properties['threads']
    3

    >>> zk.import_tree('/cms\n  threads => /fooservice\n',
    ...                '/test-propery-links')
    extra path not trimmed: /test-propery-links/cms/databases
    extra path not trimmed: /test-propery-links/cms/providers
    >>> properties['threads =>']
    u'/fooservice'
    >>> properties['threads']
    3

    >>> zk.delete_recursive('/test-propery-links')

Property links are indicated with ``=>``. The value is a node path and
optional property name, separated by whitespace.  If the name is
ommitted, then the refering name is used.  For example, the name could
be left off of the property link above.

Node deletion
=============

If a node is deleted and ``Children`` or ``Properties`` instances have
been created for it, and the paths they were created with can't be
resolved using symbolic links, then the instances' data will be
cleared.  Attempts to update properties will fail.  If callbacks have
been registered, they will be called without arguments, if possible.
It would be bad, in practice, to remove a node that processes are
watching.

Registering a server with a blank hostname
==========================================

It's common to use an empty string for a host name when calling bind
to listen on all IPv4 interfaces.  If you pass an address with an
empty host to ``register`` and `netifaces
<http://alastairs-place.net/projects/netifaces/>`_ is installed, then
all of the non-local IPv4 addresses [#ifaces]_ (for the given port) will be
registered.

If there are no non-local interfaces (not connected to network), then
the local IPV4 interface will be registered.

If netifaces isn't installed and you pass an empty host
name, then the fully-qualified domain name, as returned by
``socket.getfqdn()`` will be used for the host.

Server-registration events
==========================

When ``register`` is called, a ``zc.zk.RegisteringServer``
event is emmitted with a properties attribute that can be updated by
subscribers prior to creating the ZooKeeper ephemeral node.  This
allows third-party code to record extra server information.

Events are emitted by passing them to ``zc.zk.event.notify``. If
``zope.event`` is installed, then ``zc.zk.event.notify`` is an alias
for ``zope.event.notify``, otherwise, ``zc.zk.event.notify`` is an
empty function that can be replaced by applications.

ZooKeeper Session Management
============================

Kazoo takes care of reestablishing ZooKeeper sessions. Watches created
with the ``children`` and ``properties`` methods are reestablished when
new sessions are established.  ``zc.zk`` also recreates ephemeral
nodes created via ``register``.

zookeeper_export script
=======================

The `zc.zk` package provides a utility script for exporting a
ZooKeeper tree::

    $ zookeeper_export -e zookeeper.example.com:2181 /fooservice
    /fooservice
      secret = u'1234'
      threads = 3
      /providers
        /192.168.0.42:8080
          pid = 9999
        /192.168.0.42:8081
          pid = 9999
        /192.168.0.42:8082
          pid = 9999

.. -> sh

    >>> command, expected = sh.strip().split('\n', 1)
    >>> _, command, args = command.split(None, 2)
    >>> import pkg_resources
    >>> export = pkg_resources.load_entry_point(
    ...     'zc.zk', 'console_scripts', command)
    >>> import sys, StringIO
    >>> sys.stdout = f = StringIO.StringIO(); export(args.split())
    >>> got = f.getvalue()
    >>> import zc.zk.tests
    >>> zc.zk.tests.checker.check_output(expected.strip(), got.strip(), 0)
    True

    >>> export(['zookeeper.example.com:2181', '/fooservice'])
    /fooservice
      secret = u'1234'
      threads = 3
      /providers

    >>> export(['zookeeper.example.com:2181'])
    /cms : z4m cms
      threads = 4
      /databases
        main -> /databases/cms
      /providers
    /databases
      /cms
        a = 1
    /fooservice
      secret = u'1234'
      threads = 3
      /providers
    /lb : ipvs
      /pools
        /cms
          address = u'1.2.3.4:80'
          providers -> /cms/providers

    >>> export(['zookeeper.example.com:2181', '/fooservice', '-oo'])
    >>> print open('o').read(),
    /fooservice
      secret = u'1234'
      threads = 3
      /providers

The export script provides the same features as the ``export_tree``
method. Use the ``--help`` option to see how to use it.

zookeeper_import script
=======================

The `zc.zk` package provides a utility script for importing a
ZooKeeper tree.  So, for example, given the tree::

  /provision
    /node1
    /node2

.. -> file_source

    >>> with open('mytree.txt', 'w') as f: f.write(file_source)

In the file ``mytree.txt``, we can import the file like this::

    $ zookeeper_import zookeeper.example.com:2181 mytree.txt /fooservice

.. -> sh

    >>> command = sh.strip()
    >>> expected = ''
    >>> _, command, args = command.split(None, 2)
    >>> import_ = pkg_resources.load_entry_point(
    ...     'zc.zk', 'console_scripts', command)
    >>> import_(args.split())

    >>> zk.print_tree()
    /cms : z4m cms
      threads = 4
      /databases
        main -> /databases/cms
      /providers
        /1.2.3.4:5
          pid = 9999
    /databases
      /cms
        a = 1
    /fooservice
      secret = u'1234'
      threads = 3
      /providers
        /192.168.0.42:8080
          pid = 9999
        /192.168.0.42:8081
          pid = 9999
        /192.168.0.42:8082
          pid = 9999
      /provision
        /node1
        /node2
    /lb : ipvs
      /pools
        /cms
          address = u'1.2.3.4:80'
          providers -> /cms/providers

  Read from stdin:

    >>> stdin = sys.stdin
    >>> sys.stdin = StringIO.StringIO('/x\n/y')
    >>> import_('-d zookeeper.example.com:2181 - /fooservice'.split())
    add /fooservice/x
    add /fooservice/y

    >>> sys.stdin = StringIO.StringIO('/x\n/y')
    >>> import_('-d zookeeper.example.com:2181'.split())
    add /x
    add /y

  Trim:

    >>> sys.stdin = StringIO.StringIO('/provision\n/y')
    >>> import_('-dt zookeeper.example.com:2181 - /fooservice'.split())
    would delete /fooservice/provision/node1.
    would delete /fooservice/provision/node2.
    add /fooservice/y

    >>> sys.stdin = stdin

The import script provides the same features as the ``import_tree``
method, with the exception that it provides less flexibility for
specifing access control lists. Use the ``--help`` option to see how
to use it.

Propery-update script
=====================

The `zc.zk` package provides a utility script for updating individual
properties::

  zookeeper_set_property zookeeper.example.com:2181 /fooservice \
      threads=4 debug=True comment='ok'

.. -> example

    >>> example = example.replace('\\', '')
    >>> args = example.strip().split()
    >>> set_property = pkg_resources.load_entry_point(
    ...     'zc.zk', 'console_scripts', args.pop(0))
    >>> set_property(args)
    data updated
    comment: u'ok'
    debug: True
    secret: u'1234'
    threads: 4
    >>> zk.print_tree('/fooservice')
    /fooservice
      comment = u'ok'
      debug = True
      secret = u'1234'
      threads = 4
      /providers
        /192.168.0.42:8080
          pid = 9999
        /192.168.0.42:8081
          pid = 9999
        /192.168.0.42:8082
          pid = 9999
      /provision
        /node1
        /node2


The first argument to the script is the path of the node to be
updated. Any number of additional arguments of the form:
``NAME=PYTHONEXPRESSION`` are provided to supply updates.  If setting
strings, you may have to quote the argument, as in "comment='a
comment'".

Iterating over a tree
=====================

The ``walk`` method can be used to walk over the nodes in a tree::

    >>> for path in zk.walk():
    ...     print path
    /
    /cms
    /cms/databases
    /cms/providers
    /cms/providers/1.2.3.4:5
    /databases
    /databases/cms
    /fooservice
    /fooservice/providers
    /fooservice/providers/192.168.0.42:8080
    /fooservice/providers/192.168.0.42:8081
    /fooservice/providers/192.168.0.42:8082
    /fooservice/provision
    /fooservice/provision/node1
    /fooservice/provision/node2
    /lb
    /lb/pools
    /lb/pools/cms
    /zookeeper
    /zookeeper/quota

    >>> for path in zk.walk('/fooservice'):
    ...     print path
    /fooservice
    /fooservice/providers
    /fooservice/providers/192.168.0.42:8080
    /fooservice/providers/192.168.0.42:8081
    /fooservice/providers/192.168.0.42:8082
    /fooservice/provision
    /fooservice/provision/node1
    /fooservice/provision/node2

You can omit ephemeral nodes:

    >>> for path in zk.walk('/fooservice', ephemeral=False):
    ...     print path
    /fooservice
    /fooservice/providers
    /fooservice/providers/192.168.0.42:8080
    /fooservice/providers/192.168.0.42:8081
    /fooservice/providers/192.168.0.42:8082
    /fooservice/provision
    /fooservice/provision/node1
    /fooservice/provision/node2

You can also get a mutable list of children, which you can mutate:

    >>> i = zk.walk('/fooservice', children=True)
    >>> path, children = i.next()
    >>> path, children
    ('/fooservice', [u'providers', u'provision'])

    >>> del children[0]
    >>> for path in i:
    ...     print path
    /fooservice/provision
    /fooservice/provision/node1
    /fooservice/provision/node2


Modifications to nodes are reflected while traversing::

    >>> for path in zk.walk('/fooservice'):
    ...     print path
    ...     if 'provision' in zk.get_children(path):
    ...         zk.delete_recursive(path+'/provision')
    /fooservice
    /fooservice/providers
    /fooservice/providers/192.168.0.42:8080
    /fooservice/providers/192.168.0.42:8081
    /fooservice/providers/192.168.0.42:8082


Graph analysis
==============

The textual tree representation can be used to model and analyze a
system architecturte.  You can get a parsed representation of a tree
using ``zc.zk.parse_tree`` to parse a text tree representation
generated by hand for import, or using the ``export_tree`` method.

::

    >>> tree = zc.zk.parse_tree(tree_text)
    >>> sorted(tree.children)
    ['cms', 'lb']
    >>> tree.children['lb'].properties
    {'type': 'ipvs'}

The demo module, ``zc.zk.graphvis`` shows how you might generate
system diagrams from tree models.

Reference
=========

zc.zk.ZooKeeper
---------------

``zc.zk.ZooKeeper([connection_string[, session_timeout[, wait]]])``
    Return a new instance given a ZooKeeper connection string.

    The connection string defaults to '127.0.0.1:2181'.

    If a session timeout (``session_timeout``) isn't specified, the
    ZooKeeper server's default session timeout is used.  If the
    connection to ZooKeeper flaps, setting this to a higher value can
    avoid having clients think a server has gone away, when it hasn't.
    The downside of setting this to a higher value is that if a server
    crashes, it will take longer for ZooKeeper to notice that it's
    gone.

    The ``wait`` flag indicates whether the constructor should wait
    for a connection to ZooKeeper.  It defaults to False.

    If a connection can't be made, a ``zc.zk.FailedConnect`` exception
    is raised.

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

``delete_recursive(path[, dry_run[, force[, ignore_if_ephemeral]]])``
   Delete a node and all of it's sub-nodes.

   Ephemeral nodes or nodes containing them are not deleted by
   default. To force deletion of ephemeral nodes, supply the ``force``
   option with a true value.

   Normally, a message is printed if a node can't be deleted because
   it's ephemeral or has ephemeral sub-nodes.  If the
   ``ignore_if_ephemeral`` option is true, the a message isn't printed
   if the node's path was passed to ``delete_recursive`` directly.
   (This is used by ``import_tree`` when the only nodes that would be
   trimmed are ephemeral nodes.)

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

``is_ephemeral(path)``
   Return ``True`` if the node at ``path`` is ephemeral,``False`` otherwise.

``ln(source, destination)``
   Create a symbolic link at the destination path pointing to the
   source path.

   If the destination path ends with ``'/'``, then the source name is
   appended to the destination.

``print_tree(path='/')``
   Print the tree at the given path.

   This is just a short-hand for::

     print zk.export_tree(path, ephemeral=True),

``properties(path, watch=True)``
   Return a `zc.zk.Properties`_ for the path.

   Note that there is a fair bit of machinery in `zc.zk.Properties`_
   objects to support keeping them up to date, callbacks, and cleaning
   them up when they are no-longer used.  If you don't want to track
   changes, pass ``watch=False``.

``register(path, address, acl=zc.zk.READ_ACL_UNSAFE, **data)``
    Register a server at a path with the address.

    An ephemeral child node of ``path`` will be created with name equal
    to the string representation (HOST:PORT) of the given address.

    ``address`` must be a host and port tuple.

    ``acl`` is a ZooKeeper access control list.

    Optional node properties can be provided as keyword arguments.

``resolve(path)``
   Find the real path for the given path.

``walk(path)``
   Iterate over the nodes of a tree rooted at path.

In addition, ``ZooKeeper`` instances provide shortcuts to the following
kazoo client methods: ``exists``, ``create``, ``delete``,
``get_children``, ``get``, and ``set``.

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

Other module attributes
------------------------

``zc.zk.ZK``
   A convenient aliad for ``zc.zk.ZooKeeper`` for people who hate to
   type.

Testing support
---------------

The ``zc.zk.testing`` module provides ``setUp`` and ``tearDown``
functions that can be used to emulate a ZooKeeper server. To find out
more, use the help function::

    >>> import zc.zk.testing
    >>> help(zc.zk.testing)

.. -> ignore

    >>> import zc.zk.testing

.. cleanup

    >>> zk.close()


Change History
==============

2.0.0a5 (2014-02-10)
--------------------

This release has a number of backward-compatibility changes made after
testing some existing client software with the a5 release.

- Restored the ``wait`` constructor flag to keep trying if a connection
  fails.

- Restored the ``recv_timeout`` for test backward compatibility.

- Restored the test handle-management mechanism for test
  backward-compatibility.

- Fixed a bug in the way test machinery used internal handles.

- Restored the create_recursive method for backward compatibility.

2.0.0a5 (2014-01-30)
--------------------

- Log when sessions are lost and ephemeral nodes are restored.


Fixed: Kazoo returns node children as Unicode.
       zc.zk client applications expect children as
       returned by the children to have bytes values and
       they use the values to connect sockets.

       ``Children`` objects returned by zc.zk.children now encode
       child names using UTF-8.

Fixed: zc.zk 2 didn't accept a value of None for session_timeout
       constructor argument, breaking some old clients.

2.0.0a4 (2014-01-13)
--------------------

Fixed: When saving properties in ZooKeeper nodes, empty properties
       were encoded as empty strings.  When Kazoo saves empty strings,
       it does so in a way that causes the ZooKeeper C client (or at
       least the Python C binding) to see semi-random data, sometimes
       including data written previously to other nodes.  This can
       cause havoc when data for one node leaks into another.

       Now, we save empty properties as ``'{}'``.

2.0.0a3 (2014-01-08)
--------------------

- Renamed ``get_raw_properties`` back to ``get_properties``, for
  backward compatibility, now that we've decided not to have a
  separate package.

- Added ``ensure_path`` to the testing client.

- Updated the ``ZooKeeper.close`` method to allow multiple calls.
  (Calls after the first have no effect.)

2.0.0a2 (2014-01-06)
--------------------

Fixed packaging bug.

2.0.0a1 (2014-01-06)
--------------------

Initial version forked from zc.zk 1.2.0

----------------------------------------------------------------------

.. [#ifaces] It's a little more complicated.  If there are non-local
   interfaces, then only non-local addresses are registered.  In
   normal production, there's really no point in registering local
   addresses, as clients on other machines can't make any sense of
   them. If *only* local interfaces are found, then local addresses
   are registered, under the assumption that someone is developing on
   a disconnected computer.

