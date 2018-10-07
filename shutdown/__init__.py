r"""
Provide hooks for interrupting long running code with signals and time limits.

Scripts can request that long running processes gracefully exit, or *shut down*
by calling :func:`request`. Those long running processes can *listen*, thereby
becoming *listeners*, by calling :func:`requested` occasionally. Scripts can
also pass listeners time limits, which the listeners can track with
:class:`Timer` instances; since those instances also check for requests to
shut down, listeners can encapsulate all their listening directly via
:class:`Timer`'s :meth:`Timer.remaining` and :meth:`Timer.expired`.

Scripts can allow users to interrupt listeners using :mod:`signal`\ s or Ctrl+C
via :func:`catch_signals`. It returns a context manager inside of which the
receipt of specified signals triggers :func:`request`.

The shutdown request API -- :func:`request`, :func:`requested`, and
:func:`reset` -- are thread safe, but :func:`catch_signals` must be called
from the `main thread only
<https://docs.python.org/3/library/signal.html#signals-and-threads>`_.
:class:`Timer` instances require external synchronization if you want to rely
on their timing features.
"""


from inspect import Parameter, signature
import os
import logging
import signal
import threading
from types import FrameType, MappingProxyType
import typing
import contextlib
from time import monotonic

__all__ = ['request', 'reset', 'requested', 'catch_signals', 'Timer']

_LOG = logging.getLogger(__name__)
_SIGNAL_NAMES = MappingProxyType({s: s.name for s in signal.Signals})
_flag = threading.Event()
_SignalType = typing.Union[
	typing.Callable[[signal.Signals, FrameType], None],
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


def _install_handler(
	intended_signal: signal.Signals,
	callback: typing.Callable[[signal.Signals, FrameType], None],
) -> _SignalType:
	"""Install shutdown handler for ``intended_signal`` & return its old handler.

	Must be called from the main thread.
	"""
	def handler(signum: signal.Signals, stack_frame: FrameType) -> None:
		assert signum == intended_signal
		request()
		_clear_signal_handlers()
		callback(signum, stack_frame)
	return signal.signal(intended_signal, handler)


def _default_callback(signum: signal.Signals, stack_frame: FrameType) -> None:
	"""Write to the ``shutdown`` log at :const:`logging.WARNING` level."""
	if signum == signal.SIGINT:
		msg = '. Press Ctrl+C again to exit immediately.'
	else:
		msg = ''
	_LOG.warning(
		'Commencing shutdown. (Signal %s, process %d.)%s',
		_SIGNAL_NAMES[signum], os.getpid(), msg)


def _two_pos_args(f: typing.Callable) -> typing.Union[int, float]:
	"""Return whether f can take exactly two positional arguments."""
	if not callable(f):
		return False
	required, available, kwargs_only = 0, 0.0, False
	for param in signature(f).parameters.values():
		if param.kind == Parameter.POSITIONAL_ONLY:
			required += 1
		elif param.kind == Parameter.POSITIONAL_OR_KEYWORD:
			available += 1
			if param.default == Parameter.empty:
				required += 1
		elif param.kind == Parameter.VAR_POSITIONAL:
			available = float('inf')
		elif param.kind == Parameter.KEYWORD_ONLY:
			kwargs_only = True
	return required <= 2 and available >= 2 and not kwargs_only


@contextlib.contextmanager
def catch_signals(
	signals: typing.Iterable[signal.Signals] = (
		signal.SIGTERM, signal.SIGINT, signal.SIGQUIT,
	),
	callback: typing.Optional[
		typing.Callable[[signal.Signals, FrameType], None]] = None,
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
	calls :func:`request`, replaces the remaining signal handlers with those
	installed before :func:`catch_signals`, and finally calls ``callback``.

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
	callback
		Called from within the installed signal handlers with the arguments
		that the Python :mod:`signal` system passes to the handler. The default,
		used if the argument is None, logs the event at the
		:const:`logging.WARNING` level to the logger whose name is this
		module's ``__name__``.

	Raises
	------
	TypeError
		If ``callback`` isn't a callable taking two positional arguments.
	ValueError
		If called from a thread other than the main thread, or if ``signals``
		is empty.
	"""
	signals = tuple(signals)
	names: typing.List[str] = []
	if not signals:
		raise ValueError('No signals selected')
	if callback is None:
		callback = _default_callback
	if not _two_pos_args(callback):
		raise TypeError(
			'callback is not a callable with two positional arguments: %r' %
			(callback,))
	for signum in signals:
		# Don't overwrite the first old handler if for some reason
		# _clear_signal_handlers does not run.
		_old_handlers.setdefault(signum, _install_handler(signum, callback))
		names.append(_SIGNAL_NAMES[signum])
	_LOG.info(
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


class Timer:
	"""Countdown timer that goes to zero during a shutdown request.

	The timer starts with a time limit in seconds. Pass a time limit to the
	class's constructor or :meth:`start`; in both places, the time limit
	defaults to infinity (``float('inf')``).

	Methods :meth:`remaining` and :meth:`expired` act as though the timer ran
	into its time limit if a shutdown has been requested via :func:`request`
	(which :func:`catch_signals` uses). However, the timer can continue as if
	nothing happened if :func:`reset` is called.
	"""

	def __init__(self, limit: float = float('inf')) -> None:
		"""Start the timer and set the time limit to ``limit``."""
		self.start(limit)

	def start(self, limit: float = float('inf')) -> None:
		"""Start or restart the timer. If restarting, replaces the time limit."""
		self.__start_time = monotonic()
		if limit is not None and not isinstance(limit, (float, int)):
			raise TypeError('limit must be a number: %r' % (limit,))
		self.__limit = float('inf') if limit is None else limit
		self.__running_time: typing.Optional[float] = None
		self.__shutdown_requested = False

	def stop(self) -> float:
		"""Stop, return elapsed time. Subsequent calls return original time."""
		if self.__running_time is None:
			self.__running_time = monotonic() - self.__start_time
		return self.__running_time

	def remaining(self) -> float:
		"""Return amount of time remaining under the time limit as float seconds.

		If a shutdown was requested through :func:`request`, return zero.
		"""
		if self.__running_time is None:
			if requested():
				self.__shutdown_requested = True
				return 0.0
			return self.__limit - monotonic() + self.__start_time
		return 0.0

	def expired(self) -> bool:
		"""Return whether the time limit has expired or a shutdown was requested.

		Before :meth:`stop` is called, :meth:`expired` returns whether
		time remains within the time limit or if a shutdown was requested
		through :func:`request`. After :meth:`stop` is called,
		:meth:`expired` returns whether a shutdown was requested at the time
		:meth:`stop` was called or if the total running time exceeded the
		time limit.
		"""
		if self.__running_time is None:
			return self.remaining() <= 0.0
		return self.__shutdown_requested or self.__running_time > self.__limit

	def alarm(self) -> typing.Tuple[float, float]:
		"""Send the :const:`signal.SIGALRM` signal when the time limit expires.

		Despite the name, this method uses :func:`signal.setitimer`, not
		:func:`signal.alarm`. The previous :const:`signal.ITIMER_REAL` timer's
		`seconds` and `interval` arguments are returned in case you want to
		restore it later. This method does not set an interval, so the signal
		is delivered only once. Don't forget to set a handler for
		:const:`signal.SIGALRM` before the signal arrives.

		Availability: Unix.

		Returns
		-------
		seconds
			The previous :const:`signal.ITIMER_REAL` timer's ``seconds``
			argument. Zero if no previous timer existed.
		interval
			The previous :const:`signal.ITIMER_REAL` timer's ``interval``
			argument.

		Raises
		------
		ValueError
			If the time limit expired, so that :meth:`remaining` returns
			negative, before setting the alarm.
		"""
		try:
			seconds, interval = signal.setitimer(signal.ITIMER_REAL, self.remaining())
		except signal.ItimerError:
			raise ValueError(
				'Time limit has expired: time remaining is %f' % self.remaining())
		return seconds, interval
