##############################################################################
#
# Copyright (c) Zope Foundation and Contributors.
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
name, version = 'zc.zk', '0'

install_requires = ['setuptools', 'zc.thread']
extras_require = dict(
    test=['zope.testing', 'zc-zookeeper-static', 'mock', 'manuel',
          'zope.event', 'netifaces', 'zope.component', 'zc.monitor'],
    static=['zc-zookeeper-static'],
    )

entry_points = """
[console_scripts]
zookeeper_export = zc.zk.scripts:export
zookeeper_import = zc.zk.scripts:import_
"""

from setuptools import setup
import os
readme = open(os.path.join('src', 'zc', 'zk', 'README.txt')).read()

setup(
    author = 'Jim Fulton',
    author_email = 'jim@zope.com',
    license = 'ZPL 2.1',

    name = name, version = version,
    long_description=readme,
    description = readme.strip().split('\n')[1],
    packages = [name.split('.')[0], name],
    namespace_packages = [name.split('.')[0]],
    package_dir = {'': 'src'},
    install_requires = install_requires,
    zip_safe = False,
    entry_points=entry_points,
    include_package_data = True,
    extras_require = extras_require,
    tests_require = extras_require['test'],
    test_suite = name+'.tests.test_suite',
    )
