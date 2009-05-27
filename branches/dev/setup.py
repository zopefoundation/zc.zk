##############################################################################
#
# Copyright (c) Zope Corporation and Contributors.
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
name, version = '', '0'

from setuptools import setup

extras_require = dict(test=['zope.testing'])

entry_points = """
"""

setup(
    name = name, version = version,

    author = 'Jim Fulton',
    author_email = 'jim@zope.com',
    long_description=open('README.txt').read(),
    description = open('README.txt').read().strip().split('\n')[0],
    license = 'ZPL 2.1',

    packages = ['zc', name],
    namespace_packages = ['zc'],
    package_dir = {'': 'src'},
    install_requires = ['setuptools'],
    zip_safe = False,
    entry_points=entry_points,
    package_data = {name: ['*.txt', '*.test', '*.html']},
    extras_require = extras_require,
    tests_require = extras_require['test'],
    test_suite = name+'.tests.test_suite',
    )
