# © 2018, William Schwartz. All rights reserved. See the LICENSE file.

from distutils.version import StrictVersion
import unittest

from wrapitup import __version__


class TestVersion(unittest.TestCase):

	"""Test that WrapItUp's version string really looks like a version string."""

	def test_version(self):
		StrictVersion(__version__)
