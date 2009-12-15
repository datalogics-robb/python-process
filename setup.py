#!/usr/bin/env python

from distutils.core import setup

setup(name='python_processes',
      version='1.0', # A DL-specific version number
      description='Extensions to the subprocess module',
      author='Benjamin Smedberg',
      author_email='benjamin@smedbergs.us',
      url='http://benjamin.smedbergs.us/blog/2006-11-09/adventures-in-python-launching-subprocesses/',
      package_dir={'python_processes' : ''},
      packages=['python_processes'])
