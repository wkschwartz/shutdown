r"""
Provide hooks for interrupting long running code with signals and time limits.

Scripts can request that long running processes gracefully exit, or *shut down*
by calling :func:`request`. Those long running processes can *listen*, thereby
becoming *listeners*, by calling :func:`requested` occaisionally. Scripts can
also pass listeners time limits, which the listeners can track with
:class:`Shutter` instances; since those instances also check for requests to
shut down, listeners can encapsulate all their listening directly via
:class:`Shutter`'s :meth:`Shutter.time_left` and :meth:`Shutter.timedout`.

Scripts can allow users to interrupt listeners using :mod:`signal`\ s or Ctrl+C
via :func:`catch_signals`. It returns a context manager inside of which the
receipt of specified signals triggers :func:`request`.

The shutdown request API -- :func:`request`, :func:`requested`, and
:func:`reset` -- are thread safe, but :func:`catch_signals` must be called
from the `main thread only
<https://docs.python.org/3/library/signal.html#signals-and-threads>`_.
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
_SIGNAL_NAMES = types.MappingProxyType({s: s.name for s in signal.Signals})
_flag = threading.Event()
_SignalType = typing.Union[
	typing.Callable[[signal.Signals, types.FrameType], None],
	int,
	signal.Handlers,
	None
]
# No need for a lock because signals can only be set from the main thread.
_old_handlers: typing.Dict[int, _SignalType] = {}


def request() -> None:
	"""Request all listeners running in this process to shutdown."""
	_flag.set()


def reset() -> None:
	"""Stop requesting new listeners running in this process to shutdown."""
	_flag.clear()


def requested() -> bool:
	"""Return if :func:`request` has been called so listeners should shutdown."""
	return _flag.is_set()


def _clear_signal_handlers() -> None:
	"""Clear all installed signal handlers. Must be called from main thread.

	Installed handlers are replaced with the handlers that were around before
	:func:`catch_signals` was called.
	"""
	for signum, old_handler in _old_handlers.copy().items():
		signal.signal(signum, old_handler)
		del _old_handlers[signum]


def _install_handler(intended_signal: signal.Signals) -> _SignalType:
	"""Install shutdown handler for ``intended_signal`` & return its old handler.

	Must be called from the main thread.
	"""
	def handler(signum: signal.Signals, stack_frame: types.FrameType) -> None:
		assert signum == intended_signal
		if signum == signal.SIGINT:
			msg = '. Press Ctrl+C again to exit immediately.'
		else:
			msg = ''
		LOG.warning(
			'Commencing shutdown. (Signal %s, process %d.)%s',
			_SIGNAL_NAMES[signum], os.getpid(), msg)
		request()
		_clear_signal_handlers()
	return signal.signal(intended_signal, handler)


@contextlib.contextmanager
def catch_signals(
	signals: typing.Iterable[signal.Signals] = (
		signal.SIGTERM, signal.SIGINT, signal.SIGQUIT,
	),
) -> typing.Iterator[None]:
	r"""Return context manager to catch signals to request listeners to shutdown.

	It should be used with ``with``, and probably just around a listener:

		with shutdown.catch_signals():
			long_running_function_that_checks_shutdown_requested_occaisionally()

	When the context manager exits the ``with`` block, or when any of the
	installed handlers catches its corresponding signal, all the signal handlers
	installed when the block started will be reinstalled unconditionally. When
	the ``with`` block exits, the value returned by :func:`requested` will be
	reset to its value before entrance to the ``with`` block by calling either
	:func:`request` or :func:`reset`.

	Upon receipt of one of the signals in ``signals``, :func:`catch_signals`
	calls :func:`request`, writes a :const:`logging.WARNING`-level message to
	:mod:`shutdown`'s :mod:`logging` logger, and replaces the remaining signal
	handlers with those installed before :func:`catch_signals`.

	:func:`catch_signals` must be used from the `main thread only
	<https://docs.python.org/3/library/signal.html#signals-and-threads>`_, or it
	will raise a :exc:`ValueError`. Note that if you're running listeners in
	multiple threads started in the with block, you must join them in the same
	block or there will be a race between uninstalling the signal handlers and
	finishing the listeners.

	Parameters
	----------
	signals
		Iterable of :class:`signal.Signal`\ s to listen for. The default
		includes :const:`signal.SIGINT`, which Ctrl+C sends and normally causes
		Python to raise a :exc:`KeyboardInterrupt`.

	Raises
	------
	ValueError
		If called from a thread other than the main thread, or if ``signals``
		is empty.
	"""
	signals = tuple(signals)
	names: typing.List[str] = []
	if not signals:
		raise ValueError('No signals selected')
	for signum in signals:
		# Don't overwrite the first old handler if for some reason
		# _clear_signal_handlers does not run.
		_old_handlers.setdefault(signum, _install_handler(signum))
		names.append(_SIGNAL_NAMES[signum])
	LOG.info(
		'Process %d now listening for shutdown signals: %s',
		os.getpid(), ', '.join(names))
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
	"""Countdown timer that goes to zero during a shutdown request.

	The timer starts with a time limit in seconds. Pass a time limit to the
	class's constructor or :meth:`start_timer`; in both places, the time limit
	defaults to infinity (``float('inf')``).

	Methods :meth:`time_left` and :meth:`timedout` act as though the timer ran
	into its time limit if a shutdown has been requested via :func:`request`
	(which :func:`catch_signals` uses). However, the timer can continue as if
	nothing happend if :func:`reset` is called.
	"""

	def __init__(self, timeout: float = float('inf')) -> None:
		"""Start the timer and set the time limit to ``timeout``."""
		self.start_timer(timeout)

	def start_timer(self, timeout: float = float('inf')) -> None:
		"""Start or restart the timer. If restarting, replaces the time limit."""
		self.__start_time = monotonic()
		if timeout is not None and not isinstance(timeout, (float, int)):
			raise TypeError(f'timeout must be a number: {timeout!r}')
		self.__timeout = float('inf') if timeout is None else timeout
		self.__running_time: typing.Optional[float] = None
		self.__shutdown_requested = False

	def stop_timer(self) -> float:
		"""Stop, return elapsed time. Subsequent calls return original time."""
		if self.__running_time is None:
			self.__running_time = monotonic() - self.__start_time
		return self.__running_time

	def time_left(self) -> float:
		"""Return amount of time remaining under the time limit as float seconds.

		If a shutdown was requested through :func:`request`, return zero.
		"""
		if self.__running_time is None:
			if requested():
				self.__shutdown_requested = True
				return 0.0
			return self.__timeout - monotonic() + self.__start_time
		return 0.0

	def timedout(self) -> bool:
		"""Return whether the time limit has expired or a shutdown was requested.

		Before :meth:`stop_timer` is called, :meth:`timedout` returns whether
		time remains within the time limit or if a shutdown was requested
		through :func:`request`. After :meth:`stop_timer` is called,
		:meth:`timedout` returns whether a shutdown was requested at the time
		:meth:`stop_timer` was called or if the total running time exceeded the
		time limit.
		"""
		if self.__running_time is None:
			return self.time_left() <= 0.0
		return self.__shutdown_requested or self.__running_time > self.__timeout
