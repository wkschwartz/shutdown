# © 2018, William Schwartz. All rights reserved. See the LICENSE file.

r"""
This package facilitates interrupting slow code with signals and time limits.

Scripts can request that long running processes gracefully exit, or :dfn:`shut
down` by calling :func:`request`. Those long running processes can
:dfn:`listen`, thereby becoming :dfn:`listeners`, by querying :func:`requested`
occasionally. Scripts can also pass listeners time limits, which the listeners
can track with :class:`Timer` instances; since those instances also check for
requests to shut down, listeners can encapsulate all their listening directly
via :class:`Timer`'s :meth:`Timer.remaining` and :meth:`Timer.expired` methods.

Scripts can allow users to interrupt listeners using :mod:`signal`\ s or Ctrl+C
via :func:`catch_signals`. It returns a context manager inside of which the
receipt of specified signals triggers :func:`request`.

Example
^^^^^^^

A typical use of this package might look like the following.

.. code-block:: python
	:caption: :file:`my_script.py`
	:linenos:

	import wrapitup
	from my_library import a_lot_of_work
	with wrapitup.catch_signals():
		a_lot_of_work(data, time_limit)

.. code-block:: python
	:caption: :file:`my_library.py`
	:name: my_library
	:linenos:
	:emphasize-lines: 5

	import wrapitup
	def a_lot_of_work(data, time_limit):
		timer = wrapitup.Timer(time_limit)
		for datum in data:
			if timer.expired():
				break
			do_work(datum)

Then ``timer.expired()`` in :ref:`my_library` will be :py:const:`True`, and
break out of the :keyword:`for` loop, upon the earlier of

#. the time limit having run out or
#. the process receiving a Ctrl+C or similar signal.

.. note::

	The request API --- :func:`request`, :func:`requested`, and :func:`reset`
	--- is thread safe, but :func:`catch_signals` must be called from the `main
	thread only <https://docs.python.org/3/library/signal.html#signals-and-
	threads>`_. :class:`Timer` instances require external synchronization if you
	want to rely on their timing features.
"""


from inspect import Parameter, signature
from math import isnan
import os
import logging
import signal
import threading
from types import FrameType, MappingProxyType
import typing
import contextlib
from time import monotonic

from wrapitup._version import __version__


__all__ = [
	'request', 'reset', 'requested', 'catch_signals', 'Timer', '__version__']

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
_old_handlers = {}  # type: typing.Dict[int, _SignalType]


def request() -> None:
	"""Request all listeners running in this process to shut down."""
	_flag.set()


def reset() -> None:
	"""Stop requesting listeners running in this process to shut down."""
	_flag.clear()


def requested() -> bool:
	"""Return whether listeners should shut down."""
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


_DEFAULT_SIGS = ()  # type: typing.Tuple[signal.Signals, ...]
if os.name == 'posix':  # pragma: no cover
	_DEFAULT_SIGS = (signal.SIGINT, signal.SIGQUIT, signal.SIGTERM)
elif os.name == 'nt':
	# The best resource for learning about how Python interacts with signals
	# on Windows is https://bugs.python.org/msg260201
	# The only useful signals are SIGINT and Windows's non-standard SIGBREAK.
	# *Only* processes connected to a console session can receive the signals.
	# To send these two signals using os.kill, you must use
	# signal.CTRL_C_EVENT and signal.CTRL_BREAK_EVENT.
	_DEFAULT_SIGS = (signal.SIGINT, signal.SIGBREAK)
else:
	raise NotImplementedError('unsupported operating system: %s' % os.name)


def _default_callback(signum: signal.Signals, stack_frame: FrameType) -> None:
	"""Write to the ``wrapitup`` log at :const:`logging.WARNING` level."""
	if signum == signal.SIGINT:
		msg = '. Press Ctrl+C again to exit immediately.'
	else:
		msg = ''
	_LOG.warning(
		'Commencing shut down. (Signal %s, process %d.)%s',
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
	signals: typing.Iterable[signal.Signals] = _DEFAULT_SIGS,
	callback: typing.Optional[
		typing.Callable[[signal.Signals, FrameType], None]] = None,
) -> typing.Iterator[None]:
	r"""Return context manager to catch signals to request listeners to shut down.

	Upon receipt of one of the signals in ``signals``, :func:`catch_signals`
	calls :func:`request`, replaces the remaining signal handlers with those
	installed before :func:`catch_signals`, and finally calls ``callback``.

	When the context manager exits the :keyword:`with` block, or when any of the
	installed handlers catches its corresponding signal, all the signal handlers
	installed before the block started will be reinstalled unconditionally. When
	the :keyword:`with` block exits, the value returned by :func:`requested`
	will be returned unconditionally to its value before entrance to the
	:keyword:`with` block.

	.. note::

		:func:`catch_signals` must be used from the `main thread only
		<https://docs.python.org/3/library/signal.html#signals-and-threads>`_,
		or it will raise a :exc:`ValueError`. Note that if you're running
		listeners in multiple threads started in the :keyword:`with` block, you
		must join them in the same block or there will be a race between
		uninstalling the signal handlers and finishing the listeners.

	.. note::

		On Windows, only processes attached to a console session can receive
		Ctrl+C or Ctrl+Break events, which are the only signals Python really
		[supports on Windows](https://bugs.python.org/msg260201). To check
		whether the current process is attached to a console, import
		:mod:`sys`. ``sys.__stderr__.isatty()`` returns whether the process is
		attached to a console.

	:param signals: Signals to listen for. The default includes
		:const:`signal.SIGINT`, which Ctrl+C sends and normally causes Python
		to raise a :exc:`KeyboardInterrupt`. On Windows, ``signals`` must
		contain no signals other than :const:`signal.SIGINT` or
		:const:`signal.SIGBREAK`.
	:param callback: Called from within the installed signal handlers with the
		arguments that the Python :mod:`signal` system passes to the handler.
		The default, used if the argument is :const:`None`, logs the event at
		the :const:`logging.WARNING` level to the logger whose name is this
		module's ``__name__``.
	:raises TypeError: If ``callback`` isn't a callable taking two positional
		arguments.
	:raises ValueError: If called from a thread other than the main thread, or
		if ``signals`` is empty, or, on Windows, if ``signals`` contains
		signals other than those allowed.
	:return: A context manager to use in a :keyword:`with` block.

	.. versionadded:: 0.2.0
		The *callback* parameter.

	.. versionchanged:: 0.3.0
		Windows support
	"""
	signals = tuple(signals)
	names = []  # type: typing.List[str]
	if not signals:
		raise ValueError('No signals selected')
	if callback is None:
		callback = _default_callback
	if not _two_pos_args(callback):
		raise TypeError(
			'callback is not a callable with two positional arguments: %r' %
			(callback,))
	if os.name == 'nt':  # pragma: no cover
		if not (set(signals) <= set(_DEFAULT_SIGS)):
			raise ValueError(
				"Windows does not support one of the signals: %r" % (signals,))
	for signum in signals:
		# Don't overwrite the first old handler if for some reason
		# _clear_signal_handlers does not run.
		_old_handlers.setdefault(signum, _install_handler(signum, callback))
		names.append(_SIGNAL_NAMES[signum])
	_LOG.info(
		'Process %d now listening for shut down signals: %s',
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
	"""Countdown timer that goes to zero while a request to shut down is active.

	The timer starts with a time limit in seconds. Pass a time limit to the
	class's constructor or :meth:`start`; in both places, the time limit
	defaults to infinity (``float('inf')``).

	Methods :meth:`remaining` and :meth:`expired` act as though the timer ran
	into its time limit if a shut down has been requested via :func:`request`
	(which :func:`catch_signals` uses). However, the timer can continue as if
	nothing happened if :func:`reset` is called.

	:param float limit: Time limit after which this timer expires, in
		seconds.
	:raises TypeError: if ``limit`` is not a :class:`float` or :class:`int`.
	:raises ValueError: if ``limit`` is not a number (NaN).

	.. versionchanged:: 0.2.0
		Renamed from ``Shutter``. Constructor argument name changed from
		``timeout``.
	"""

	def __init__(self, limit: float = float('inf')) -> None:  # noqa: D107
		self.start(limit)

	def start(self, limit: float = float('inf')) -> None:
		"""(Re)start the timer. If restarting, replaces the time limit.

		:param float limit: Time limit after which this timer expires, in
			seconds.
		:raises TypeError: if ``limit`` is not a :class:`float` or :class:`int`.
		:raises ValueError: if ``limit`` is not a number (NaN).

		.. versionchanged:: 0.2.0
			Renamed from ``start_timer``, and argument name changed from
			``timeout``.
		"""
		self.__start_time = monotonic()
		if not isinstance(limit, (float, int)):
			raise TypeError('limit must be a number: %r' % (limit,))
		if isnan(limit):
			raise ValueError('limit is NaN (not a number)')
		self.__limit = float('inf') if limit is None else limit
		self.__running_time = None  # type: typing.Optional[float]
		self.__shutdown_requested = False

	def stop(self) -> float:
		"""Stop and return elapsed time.

		:return: Time in seconds between more recent of construction or call to
			:meth:`start` and the first call to :meth:`stop`. Subsequent calls
			after the first return the same value as the first one does.

		.. versionchanged:: 0.2.0
			Renamed from ``stop_timer``.
		"""
		if self.__running_time is None:
			self.__running_time = monotonic() - self.__start_time
		return self.__running_time

	def remaining(self) -> float:
		"""Return amount of time remaining under the time limit.

		:return: Time in seconds remaining under the time limit. If a shut down
			was requested through :func:`request`, return zero. This can change
			if :func:`reset` is called later.

		.. versionchanged:: 0.2.0
			Renamed from ``time_left``.
		"""
		if self.__running_time is None:
			if requested():
				self.__shutdown_requested = True
				return 0.0
			return self.__limit - monotonic() + self.__start_time
		return 0.0

	def expired(self) -> bool:
		"""Return whether the time limit has expired or a shut down was requested.

		:return:
			* Before :meth:`stop` is called, :meth:`expired` returns whether
				time remains within the time limit or if a shut down was
				requested through :func:`request`. This can change if
				:func:`reset` is called later.
			* After :meth:`stop` is called, :meth:`expired` returns whether a
				shut down was requested at the time :meth:`stop` was called or
				if the total running time exceeded the time limit. This *cannot*
				change if :func:`reset` is called later.

		.. versionchanged:: 0.2.0
			Renamed from ``timedout``.
		"""
		if self.__running_time is None:
			return self.remaining() <= 0.0
		return self.__shutdown_requested or self.__running_time > self.__limit

	if hasattr(signal, "setitimer"):
		def alarm(self) -> typing.Tuple[float, float]:
			"""Send the :const:`signal.SIGALRM` signal when the time limit expires.

			Despite the name, this method uses :func:`signal.setitimer`, not
			:func:`signal.alarm`. The previous :const:`signal.ITIMER_REAL` timer's
			`seconds` and `interval` arguments are returned in case you want to
			restore it later. This method does not set an interval, so the signal
			is delivered only once. Don't forget to set a handler for
			:const:`signal.SIGALRM` before the signal arrives.

			Availability: Unix.

			:return:
				:seconds:
					The previous :const:`signal.ITIMER_REAL` timer's ``seconds``
					argument for :func:`signal.setitimer`. Zero if no previous timer
					existed.
				:interval:
					The previous :const:`signal.ITIMER_REAL` timer's ``interval``
					argument for :func:`signal.setitimer`.
			:raises ValueError: If the time limit expired, so that :meth:`remaining`
				returns negative, before setting the alarm.

			.. versionadded:: 0.2.0
			"""
			try:
				seconds, interval = signal.setitimer(signal.ITIMER_REAL, self.remaining())
			except signal.ItimerError:
				raise ValueError(
					'Time limit has expired: time remaining is %f' % self.remaining())
			return seconds, interval
