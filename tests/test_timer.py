# © 2018, William Schwartz. All rights reserved. See the LICENSE file.

import os
import signal
import time
import unittest

from wrapitup import request, reset, Timer


class TestTimer(unittest.TestCase):

	# Python makes few guarantees about the precision of its various clocks.
	# https://stackoverflow.com/a/43773780
	if os.name == 'posix':
		time_limit = 0.001
		decimal_places = 3
	elif os.name == 'nt':
		time_limit = 0.1
		decimal_places = 1

	def test_wrapitup_timer(self):
		"Calling request causes Timer.expired to return True."
		request()
		self.assertTrue(Timer().expired())

	def test_bad_time_limit(self):
		self.assertRaises(TypeError, Timer, type)
		self.assertRaises(TypeError, Timer, 1j)
		self.assertRaises(TypeError, Timer, '1')
		self.assertRaises(TypeError, Timer, None)
		self.assertRaises(ValueError, Timer, float('nan'))

	def test_default_no_time_limit(self):
		"Test that the default time limit is None."
		s = Timer()
		t1 = s.remaining()
		u1 = s.expired()
		time.sleep(self.time_limit)
		t2 = s.remaining()
		u2 = s.expired()
		self.assertEqual(t1, float('inf'))
		self.assertEqual(t2, float('inf'))
		self.assertFalse(u1)
		self.assertFalse(u2)
		self.assertFalse(s.expired())

	def test_time_limit(self):
		s = Timer(self.time_limit)
		t1 = s.remaining()
		u1 = s.expired()
		time.sleep(self.time_limit / 2)
		t2 = s.remaining()
		u2 = s.expired()
		time.sleep(self.time_limit / 2)
		t3 = s.remaining()
		u3 = s.expired()
		self.assertAlmostEqual(t1, self.time_limit, places=self.decimal_places)
		self.assertGreater(t1, self.time_limit / 2)
		self.assertFalse(u1)
		self.assertGreater(t1 - t2, self.time_limit / 2, {"t1": t1, "t2": t2})
		self.assertFalse(u2)
		self.assertLess(t3, 0)
		self.assertTrue(u3)
		s.stop()
		self.assertTrue(s.expired())

		s = Timer(self.time_limit)
		s.stop()
		self.assertFalse(s.expired())
		time.sleep(self.time_limit)
		self.assertFalse(s.expired())  # The return value should not change

	def test_stop(self):
		s = Timer()
		time.sleep(self.time_limit)  # Needed on Windows
		self.assertGreater(s.stop(), 0)
		self.assertAlmostEqual(s.stop(), self.time_limit, places=self.decimal_places)
		s = Timer(self.time_limit)
		time.sleep(s.remaining())
		self.assertGreater(s.stop(), self.time_limit)
		self.assertAlmostEqual(
			s.stop(), self.time_limit, places=self.decimal_places - 1)

	def test_remaining(self):

		# Zero when shutdown requested
		s = Timer(self.time_limit)
		request()
		self.assertEqual(s.remaining(), 0)
		reset()

		# Greater than zero before timing out, less after
		s.start(self.time_limit)
		self.assertGreater(s.remaining(), 0)
		time.sleep(self.time_limit)
		self.assertLess(s.remaining(), 0)

		# Always zero after stopping
		s.start(self.time_limit)
		self.assertGreater(self.time_limit, s.stop())
		self.assertEqual(s.remaining(), 0)

	@unittest.skipIf(
		not hasattr(signal, 'setitimer'),
		"Requires signal.setitimer (Unix only)"
	)
	def test_alarm(self):
		called = False

		def handler(signum, stack_frame):
			nonlocal called
			called = True
		prev_handler = signal.signal(signal.SIGALRM, handler)
		prev_delay, prev_interval = signal.setitimer(signal.ITIMER_REAL, 10, 5)
		if prev_delay:
			outer = Timer(prev_delay)  # pragma: no cover
		try:
			s = Timer(self.time_limit)
			delay, interval = s.alarm()
			self.assertAlmostEqual(delay, 10, places=3)
			self.assertAlmostEqual(interval, 5, places=3)
			time.sleep(self.time_limit)
			self.assertTrue(called)

			self.assertLess(s.remaining(), 0)
			self.assertRaisesRegex(ValueError, r'expired.*-\d\.\d', s.alarm)
		finally:
			if prev_delay:
				signal.setitimer(   # pragma: no cover
					signal.ITIMER_REAL, outer.remaining(), prev_interval)
			else:
				signal.setitimer(signal.ITIMER_REAL, 0, 0)
			signal.signal(signal.SIGALRM, prev_handler)
