#!/usr/bin/env python
import os
from setuptools import setup


def _read(fname):
    try:
        return open(os.path.join(os.path.dirname(__file__), fname)).read()
    except IOError:
        return ''


REQUIREMENTS = [l for l in _read('requirements.txt').split('\n') if l and not l.startswith('#')]
VERSION = '0.0.1'

setup(
        name='pxe-tools',
        version=VERSION,
        url='https://github.com/rpcope1/pxe-tools',
        description='Tools for augmenting and simplifying PXE.',
        long_description=_read("README.md"),
        author='Robert Cope',
        author_email='robert@copesystems.com',
        license='MIT',
        platforms='any',
        packages=["pxe_tools"],
        install_requires=REQUIREMENTS,
        tests_require=REQUIREMENTS + ["tox", "pytest", "coverage"],
        classifiers=[
            'Development Status :: 1 - Planning',
            'License :: OSI Approved :: MIT License',
            'Operating System :: OS Independent',
            'Topic :: System :: Boot',
            'Topic :: System :: Networking',
            'Topic :: System :: Systems Administration',
            'Programming Language :: Python',
            'Programming Language :: Python :: 3.5',
            'Programming Language :: Python :: 3.6',
            'Programming Language :: Python :: 3.7',
            'Programming Language :: Python :: 3.8',
            'Topic :: Software Development :: Libraries :: Python Modules'
        ]
)
