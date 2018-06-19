"""Provide hooks for interrupting long running code.

The shutdown request API -- `request`, `requested` and `reset` -- are thread
safe, but `catch_signals` must be called from the main thread.

We call code that checks `requested` to see whether it should shutdown a
_listener_. Use the `Shutter` class to both listen for shutdown requests and
have a timer. Code can occasionally check the `s.timedout()` return value on a
`Shutter` instance `s` to see if it should wrap things up gracefully.
"""


import os
import logging
import signal
import threading
import types
import typing
import contextlib
from time import monotonic

__all__ = ['request', 'reset', 'requested', 'catch_signals', 'Shutter']

LOG = logging.getLogger(__name__)

_signal_names: typing.List[typing.Optional[str]] = [None] * signal.NSIG
for name, value in signal.__dict__.items():
	if name.startswith('SIG') and '_' not in name:
		_signal_names[value] = name
_SIGNAL_NAMES = tuple(_signal_names)
del _signal_names
_flag = threading.Event()
# No need for a lock because signals can only be set from the main thread.
_old_handlers: typing.Mapping[int, typing.Callable[[typing.Union[signal.Signals, signal.Handlers], types.FrameType], None]] = {}


def request() -> None:
	"Request all listeners running in this process to shutdown."
	_flag.set()


def reset() -> None:
	"Stop requesting that new listeners running in this process to shutdown."
	_flag.clear()


def requested() -> bool:
	"Return whether `request` has been called and listeners should shutdown."
	return _flag.is_set()


def _clear_signal_handlers():
	"Clear all installed signal handlers. Must be called from main thread."
	for signum, old_handler in _old_handlers.copy().items():
		signal.signal(signum, old_handler)
		del _old_handlers[signum]


def _install_handler(intended_signal):
	"Install shutdown handler for `intended_signal` and return its old handler."
	def handler(signum, stack_frame):
		assert signum == intended_signal
		if signum == signal.SIGINT:
			msg = '. Press Ctrl+C again to exit immediately.'
		else:
			msg = ''
		LOG.warning('Commencing shutdown. (Signal %s, process %d.)%s',
					_SIGNAL_NAMES[signum], os.getpid(), msg)
		request()
		_clear_signal_handlers()
	return signal.signal(intended_signal, handler)


@contextlib.contextmanager
def catch_signals(signals=(signal.SIGTERM, signal.SIGINT, signal.SIGQUIT)):
	"""Return context manager to catch signals and request listeners shutdown.

	It should be used with `with`, and probably just around a listener:

	    with shutdown.catch_signals():
	        long_running_function_that_checks_shutdown_requested_occaisionally()

	When the context manager exits the `with` block, or when any of the
	installed handlers catches its corresponding signal, all the signal handlers
	installed when the block started will be reinstalled unconditionally. When
	the `with` block exits, the value returned by `requested` will be reset to
	its value before entrance to the `with` block.

	`catch_signals` must be used from the main thread only, or it will raise a
	`ValueError`. Note that if you're running listeners in multiple threads
	started in the with block, you must join them in the same block or there
	will be a race between uninstalling the signal handlers and finishing the
	listeners.

	Argument `signals` accepts an iterable of valid signal numbers (from the
	standard library's `signal` module). Note that by default, `signals`
	includes `SIGINT`, which Ctrl+C sends and normally causes Python to raise a
	`KeyboardInterrupt`.
	"""
	signals, names = tuple(signals), []
	if not signals:
		raise ValueError('No signals selected')
	for signum in signals:
		# Don't overwrite the first old handler if for some reason
		# _clear_signal_handlers does not run.
		_old_handlers.setdefault(signum, _install_handler(signum))
		names.append(_SIGNAL_NAMES[signum])
	LOG.info('Process %d now listening for shutdown signals: %s', os.getpid(),
			 ', '.join(names))
	old_requested = requested()
	try:
		yield
	finally:
		_clear_signal_handlers()
		if old_requested:
			request()
		else:
			reset()


class Shutter:

	def __init__(self, timeout:typing.Optional[float] = None) -> None:
		self.start_timer(timeout)
		super().__init__()

	def start_timer(self, timeout:typing.Optional[float] = None) -> None:
		"Start or restart the timer. If restarting, replaces timeout."
		self.__start_time = start_time = monotonic()
		if timeout is not None and not isinstance(timeout, (float, int)):
			raise TypeError(f'timeout must be a number: {timeout!r}')
		self.__timeout = float('inf') if timeout is None else timeout
		self.__running_time: typing.Optional[float] = None
		self.__shutdown_requested = False

	def stop_timer(self) -> float:
		"Stop, return elapsed time. Subsequent calls return original time."
		shutdown_requested = requested()
		try:
			running_time = self.__running_time
		except AttributeError:
			raise RuntimeError(f'{self}: Cannot stop timer before it starts.')
		if self.__running_time is None:
			self.__running_time = monotonic() - self.__start_time
			self.__shutdown_requested
		return self.__running_time

	def time_left(self) -> float:
		"Return amount of time remaining under the timeout as float seconds."
		if self.__running_time is None:
			if requested():
				self.__shutdown_requested = True
				return 0.0
			return self.__timeout - monotonic() + self.__start_time
		return 0.0

	def timedout(self) -> bool:
		"""Return whether the timeout has expired or a shutdown was requested.

		Before `stop_timer()`, `timedout()` returns whether time remains within
		the timeout limit or if a shutdown was requested through `request`.
		Before `stop_timer()`, `timedout()` returns whether a shutdown was
		requested by the time `stop_timer()` was called, or if the total running
		time exceeded the timeout limit.
		"""
		if self.__running_time is None:
			return self.time_left() <= 0.0
		return self.__shutdown_requested or self.__running_time > self.__timeout

