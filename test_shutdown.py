import os
import signal
from threading import Event, Thread
import time
import types
import unittest

from shutdown import request, reset, requested, catch_signals, Shutter


class TestRequest(unittest.TestCase):

	def tearDown(self):
		reset()
		super().tearDown()

	def test_request(self):
		self.assertFalse(requested())
		request()
		self.assertTrue(requested())
		reset()
		self.assertFalse(requested())

	def test_shutdown_shutter(self):
		"Calling request causes Shutter.timedout to return True."
		request()
		self.assertTrue(Shutter().timedout())


class TestCatchSignals(unittest.TestCase):

	def setUp(self):
		super(TestCatchSignals, self).setUp()
		self.handler_called = False
		signal.signal(signal.SIGUSR1, self.handler)

	def tearDown(self):
		signal.signal(signal.SIGUSR1, signal.SIG_DFL)
		signal.signal(signal.SIGUSR2, signal.SIG_DFL)
		reset()
		super(TestCatchSignals, self).tearDown()

	def handler(self, signum, stack_frame):
		self.handler_called = True

	def catch_signals(self, callback=None):
		return catch_signals(
			signals=(signal.SIGUSR1, signal.SIGUSR2), callback=callback)

	def assert_logging(self, msgs, default_callback=True):
		self.assertEqual(len(msgs), 1 + default_callback)
		self.assertRegex(
			msgs[0],
			(
				r'INFO:shutdown:Process \d+ now listening for shutdown signals:'
				r' SIGUSR1, SIGUSR2'
			),
		)
		if default_callback:
			self.assertRegex(
				msgs[1],
				(
					r'WARNING:shutdown:Commencing shutdown. \(Signal [A-Z1-9]{6,7}'
					r', process \d+.\)'
				),
			)

	def test_signals_list_empty(self):
		with self.assertRaisesRegex(ValueError, 'No signals selected'):
			with catch_signals(signals=[]):
				pass  # pragma: no coverage

	def test_not_main_thread(self):
		success = Event()

		def subthread():
			try:
				with self.catch_signals():
					self.fail(
						'shutdown.catch_signals should raise ValueError in non-'
						'main thread')  # pragma: no coverage
			except ValueError:
				success.set()
		thread = Thread(target=subthread)
		thread.start()
		thread.join()
		self.assertTrue(success.is_set())

	def get_handlers(self):
		"Return a list indexed by signal number of all current handlers."
		handlers = [None] * signal.NSIG
		for name, signum in signal.__dict__.items():
			if name.startswith('SIG') and '_' not in name:
				handlers[signum] = signal.getsignal(signum)
		return handlers

	def test_default_shutdown_signals(self):
		old_handlers = self.get_handlers()
		with catch_signals():
			new_handlers = self.get_handlers()
		reset_handlers = self.get_handlers()
		# Known: len(old_handlers) == len(new_handlers) == signal.NSIG
		diff = []
		for signum in range(signal.NSIG):
			if old_handlers[signum] != new_handlers[signum]:
				diff.append(signum)
		expected = (signal.SIGINT, signal.SIGTERM, signal.SIGQUIT)
		self.assertCountEqual(diff, expected)
		# Just so we know the test didn't pollute the environment:
		self.assertEqual(old_handlers, reset_handlers)

	def test_context_manager_installs_default_handlers(self):
		with self.assertLogs('shutdown') as logcm, self.catch_signals():
			self.assertFalse(requested())
			os.kill(os.getpid(), signal.SIGUSR1)
			self.assertTrue(requested())
		self.assertFalse(requested())  # The context manager cleans up
		self.assertFalse(self.handler_called)
		self.assert_logging(logcm.output)

	def assert_context_manager_callbacks(self, error: bool):
		callback_args = None

		class Exc(Exception):
			pass

		def callback(signum: signal.Signals, stack_frame: types.FrameType) -> None:
			nonlocal callback_args
			callback_args = (signum, stack_frame)
			if error:
				raise Exc

		def callback_star_args(*args):
			return callback(args[0], args[1])

		def callback_args_defaults(a=None, b=None, c=None):
			return callback(a, b)

		def callback_args_partial(a, *args):
			return callback(a, args[0])

		callbacks = (
			callback, callback_star_args, callback_args_defaults,
			callback_args_partial,
		)
		for cb in callbacks:
			self.setUp()
			callback_args = None
			with self.subTest(callback=cb.__name__):
				with self.assertLogs('shutdown') as logcm, self.catch_signals(cb):
					self.assertFalse(requested())
					if error:
						with self.assertRaises(Exc):
							os.kill(os.getpid(), signal.SIGUSR2)
					else:
						os.kill(os.getpid(), signal.SIGUSR2)
					self.assertTrue(requested())

					self.assertFalse(self.handler_called)
					os.kill(os.getpid(), signal.SIGUSR1)
					self.assertTrue(self.handler_called)
				self.assert_logging(logcm.output, default_callback=False)
				self.assertEqual(callback_args[0], signal.SIGUSR2)
				self.assertIsInstance(callback_args[1], types.FrameType)

	def test_context_manager_installs_custom_callbacks(self):
		self.assert_context_manager_callbacks(False)

	def test_context_manager_installs_callback_error(self):
		"""Errors in callbacks shouldn't requesting shutdown or clearing handlers."""
		self.assert_context_manager_callbacks(True)

	def test_bad_callbacks(self):
		not_callable = object()

		def one(a):
			return

		def three(a, b, c):
			return

		def kwargs_only1(a, *, b):
			return

		def kwargs_only2(*, a, b):
			return

		def kwargs_only3(a, b, *, c):
			return
		bad_callbacks = (
			not_callable, one, three, kwargs_only1, kwargs_only2, kwargs_only3)
		for bad_callback in bad_callbacks:
			with self.subTest(bad_callback=bad_callback):
				with self.assertRaisesRegex(TypeError, "callback"):
					with self.catch_signals(bad_callback):
						os.kill(os.getpid(), signal.SIGUSR1)
						self.fail(
							"catch_signals should have had a TypeError by now")

	def test_context_manager_resets_handlers(self):
		with self.catch_signals():
			self.assertFalse(self.handler_called)
		os.kill(os.getpid(), signal.SIGUSR1)
		self.assertTrue(self.handler_called)

	def test_handler_reset_after_its_own_signal(self):
		with self.assertLogs('shutdown') as logcm, self.catch_signals():
			self.assertFalse(requested())
			os.kill(os.getpid(), signal.SIGUSR1)
			self.assertTrue(requested())

			self.assertFalse(self.handler_called)
			os.kill(os.getpid(), signal.SIGUSR1)
			self.assertTrue(self.handler_called)
		self.assert_logging(logcm.output)

	def test_handler_reset_after_other_signals(self):
		with self.assertLogs('shutdown') as logcm, self.catch_signals():
			self.assertFalse(requested())
			os.kill(os.getpid(), signal.SIGUSR2)
			self.assertTrue(requested())

			self.assertFalse(self.handler_called)
			os.kill(os.getpid(), signal.SIGUSR1)
			self.assertTrue(self.handler_called)
		self.assert_logging(logcm.output)

	def test_handler_reset_is_idempotent(self):
		self.assertFalse(requested())
		with self.assertLogs('shutdown') as logcm, self.catch_signals():
			self.assertFalse(requested())
			os.kill(os.getpid(), signal.SIGUSR2)
			self.assertTrue(requested())

			self.assertFalse(self.handler_called)
			os.kill(os.getpid(), signal.SIGUSR1)
			self.assertTrue(self.handler_called)
		self.assertFalse(requested())

		self.handler_called = False
		os.kill(os.getpid(), signal.SIGUSR1)
		self.assertTrue(self.handler_called)
		self.assert_logging(logcm.output)

	def test_catch_signals_resets_requests(self):
		with self.assertLogs('shutdown') as logcm, self.catch_signals():
			self.assertFalse(requested())
			os.kill(os.getpid(), signal.SIGUSR1)
			self.assertTrue(requested())
		self.assertFalse(requested())  # The context manager cleans up
		self.assertFalse(self.handler_called)
		self.assert_logging(logcm.output)

		# Do not overwrite existing request
		request()
		with self.assertLogs('shutdown') as logcm, self.catch_signals():
			self.assertTrue(requested())
			os.kill(os.getpid(), signal.SIGUSR1)
			self.assertTrue(requested())
		self.assertTrue(requested())
		self.assertFalse(self.handler_called)
		self.assert_logging(logcm.output)

	def test_special_sigint_message(self):
		with self.assertLogs('shutdown') as logcm:
			with catch_signals(signals=[signal.SIGINT]):
				os.kill(os.getpid(), signal.SIGINT)
		self.assertEqual(len(logcm.output), 2)
		self.assertRegex(
			logcm.output[0],
			r'INFO:shutdown:Process \d+ now listening for shutdown signals: SIGINT')
		self.assertRegex(logcm.output[1], (
			r'WARNING:shutdown:Commencing shutdown. \(Signal [A-Z1-9]{6,7},'
			r' process \d+.\). Press Ctrl\+C again to exit immediately.'
		))


class TestShutter(unittest.TestCase):

	# The tests get unreliable when I make timeout smaller.
	timeout = 0.001
	decimal_places = 3

	def test_bad_timeout(self):
		self.assertRaises(TypeError, Shutter, type)
		self.assertRaises(TypeError, Shutter, 1j)
		self.assertRaises(TypeError, Shutter, '1')

	def test_default_no_timeout(self):
		"Test that the default timeout is None."
		s = Shutter()
		t1 = s.time_left()
		u1 = s.timedout()
		time.sleep(self.timeout)
		t2 = s.time_left()
		u2 = s.timedout()
		self.assertEqual(t1, float('inf'))
		self.assertEqual(t2, float('inf'))
		self.assertFalse(u1)
		self.assertFalse(u2)
		self.assertFalse(s.timedout())

	def test_timeout(self):
		s = Shutter(self.timeout)
		t1 = s.time_left()
		u1 = s.timedout()
		time.sleep(self.timeout / 2)
		t2 = s.time_left()
		u2 = s.timedout()
		time.sleep(self.timeout / 2)
		t3 = s.time_left()
		u3 = s.timedout()
		self.assertLess(t1, self.timeout)
		self.assertGreater(t1, self.timeout / 2)
		self.assertFalse(u1)
		self.assertGreater(t1 - t2, self.timeout / 2, f"t1={t1}, t2={t2}")
		self.assertFalse(u2)
		self.assertLess(t3, 0)
		self.assertTrue(u3)
		s.stop_timer()
		self.assertTrue(s.timedout())

		s = Shutter(self.timeout)
		s.stop_timer()
		self.assertFalse(s.timedout())
		time.sleep(self.timeout)
		self.assertFalse(s.timedout())  # The return value should not change

	def test_stop_timer(self):
		s = Shutter()
		self.assertGreater(s.stop_timer(), 0)
		self.assertAlmostEqual(s.stop_timer(), 0, places=self.decimal_places)
		s = Shutter(self.timeout)
		time.sleep(s.time_left())
		self.assertGreater(s.stop_timer(), self.timeout)
		self.assertAlmostEqual(
			s.stop_timer(), self.timeout, places=self.decimal_places - 1)

	def test_time_left(self):

		# Zero when shutdown requested
		s = Shutter(self.timeout)
		request()
		self.assertEqual(s.time_left(), 0)
		reset()

		# Greater than zero before timing out, less after
		s.start_timer(self.timeout)
		self.assertGreater(s.time_left(), 0)
		time.sleep(self.timeout)
		self.assertLess(s.time_left(), 0)

		# Always zero after stopping
		s.start_timer(self.timeout)
		self.assertGreater(self.timeout, s.stop_timer())
		self.assertEqual(s.time_left(), 0)


if __name__ == '__main__':
	unittest.main()
