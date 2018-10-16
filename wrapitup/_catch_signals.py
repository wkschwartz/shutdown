# © 2018, William Schwartz. All rights reserved. See the LICENSE file.

"""This module implements that signals-catching API."""


from inspect import Parameter, signature
import os
import logging
import signal
from types import FrameType, MappingProxyType, TracebackType
import typing

from wrapitup._requests import request, reset, requested


__all__ = ['catch_signals']

_LOG = logging.getLogger('wrapitup')
_SIGNAL_NAMES = MappingProxyType({s: s.name for s in signal.Signals})
_SignalType = typing.Union[
	typing.Callable[[signal.Signals, FrameType], None],
	int,
	signal.Handlers,
	None
]


# SIGINT is generally what happens when you hit Ctrl+C.
_DEFAULT_SIGS = (signal.SIGINT,)  # type: typing.Tuple[signal.Signals, ...]
if os.name == 'posix':
	# On macOS, SIGTERM is what happens when you hit "Quit" in Activity Monitor.
	_DEFAULT_SIGS += (signal.SIGTERM,)
elif os.name == 'nt':
	# The best resource for learning about how Python interacts with signals
	# on Windows is https://bugs.python.org/msg260201
	# The only useful signals are SIGINT and Windows's non-standard SIGBREAK.
	# *Only* processes connected to a console session can receive the signals.
	# To send these two signals using os.kill, you must use
	# signal.CTRL_C_EVENT and signal.CTRL_BREAK_EVENT.
	_DEFAULT_SIGS += (signal.SIGBREAK,)
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


_ExcType = typing.TypeVar('_ExcType', bound=BaseException)


class catch_signals:
	r"""Return a context manager to catch signals to request listeners to shut down.

	Upon receipt of one of the signals in ``signals``, :func:`catch_signals`
	calls :func:`request`, replaces the remaining signal handlers with those
	installed before :func:`catch_signals`, and finally calls ``callback``.

	When the context manager exits the :keyword:`with` block, or when any of the
	installed handlers catches its corresponding signal, all the signal handlers
	installed before the block started will be reinstalled unconditionally. When
	the :keyword:`with` block exits, the value returned by :func:`requested`
	will be returned unconditionally to its value before entrance to the
	:keyword:`with` block.

	:func:`catch_signals` instances are `reentrant and reusable
	<https://docs.python.org/3/library/contextlib.html#single-use-reusable-and-reentrant-context-managers>`_.
	However, keep in mind that signals and the state of :func:`requested` are
	global.

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
		`supports on Windows <https://bugs.python.org/msg260201>`_. To check
		whether the current process is attached to a console, import
		:mod:`sys`. ``sys.__stderr__.isatty()`` returns whether the process is
		attached to a console. The only console that seems to work in the tests
		of :func:`catch_signals` is :program:`cmd.exe`.

	:param signals: Signals to listen for. The default includes
		:const:`signal.SIGINT`, which Ctrl+C sends and normally causes Python
		to raise a :exc:`KeyboardInterrupt`. On Windows, ``signals`` must
		contain no signals other than :const:`signal.SIGINT` or
		:const:`signal.SIGBREAK`, the two of which are the defaults on Windows.
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

	.. versionadded:: 0.3.0
		Windows support.

	.. versionchanged:: 0.3.0
		:func:`catch_signals` became reentrant and reusable.
	"""

	def __init__(
		self,
		signals: typing.Iterable[signal.Signals] = _DEFAULT_SIGS,
		callback: typing.Optional[
			typing.Callable[[signal.Signals, FrameType], None]] = None,
	) -> None:  # noqa: D107
		signals = tuple(signals)
		if not signals:
			raise ValueError('No signals selected')
		if callback is None:
			callback = _default_callback
		if not _two_pos_args(callback):
			raise TypeError(
				'callback is not a callable with two positional arguments: %r' %
				(callback,))
		if os.name == 'nt':
			if not (set(signals) <= set(_DEFAULT_SIGS)):
				raise ValueError(
					"Windows does not support one of the signals: %r" % (signals,))
		self._signals = signals
		self._callback = callback
		# No need for a lock because signals can only be set from the main thread.
		self._old_handlers = []  # type: typing.List[typing.Dict[int, _SignalType]]
		self._depth = 0

	def __enter__(self) -> None:
		"""Install signal handlers and log at :const:`logging.INFO` level."""
		self._old_handlers.append({})
		self._depth += 1
		names = []  # type: typing.List[str]
		for signum in self._signals:
			self._old_handlers[-1][signum] = self._install_handler(
				signum, self._callback)
			names.append(_SIGNAL_NAMES[signum])
		_LOG.info(
			'Process %d now listening for shut down signals: %s',
			os.getpid(), ', '.join(names))
		self._old_requested = requested()

	def __exit__(
		self,
		exc_type: typing.Optional[typing.Type[_ExcType]],
		exc_value: typing.Optional[_ExcType],
		traceback: typing.Optional[TracebackType]
	) -> bool:
		"""Uninstall signal handlers if that has not already happened."""
		self._clear_signal_handlers()
		self._depth -= 1
		if self._old_requested:
			request()
		else:
			reset()
		return False

	def _clear_signal_handlers(self) -> None:
		"""Clear all installed signal handlers. Must be called from main thread.

		Installed handlers are replaced with the handlers that were around before
		:func:`catch_signals` was called.
		"""
		if len(self._old_handlers) < self._depth:
			return
		old_handlers = self._old_handlers[-1]
		for signum, old_handler in old_handlers.copy().items():
			signal.signal(signum, old_handler)
			del old_handlers[signum]
		self._old_handlers.pop()

	def _install_handler(
		self,
		intended_signal: signal.Signals,
		callback: typing.Callable[[signal.Signals, FrameType], None],
	) -> _SignalType:
		"""Install shutdown handler for ``intended_signal`` & return its old handler.

		Must be called from the main thread.
		"""
		def handler(signum: signal.Signals, stack_frame: FrameType) -> None:
			assert signum == intended_signal
			request()
			self._clear_signal_handlers()
			callback(signum, stack_frame)
		return signal.signal(intended_signal, handler)
