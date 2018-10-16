# © 2018, William Schwartz. All rights reserved. See the LICENSE file.

import unittest

from wrapitup import request, reset, requested


class TestRequest(unittest.TestCase):

	def test_request(self):
		self.assertFalse(requested())
		request()
		self.assertTrue(requested())
		reset()
		self.assertFalse(requested())
