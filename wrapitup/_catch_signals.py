# © 2018, William Schwartz. All rights reserved. See the LICENSE file.

"""Implement signals-catching API."""


from inspect import Parameter, signature
import os
import logging
import signal
from types import FrameType, TracebackType
import typing

from wrapitup._requests import request, reset, requested


__all__ = ['catch_signals']

_LOG = logging.getLogger(__package__)
_ExcType = typing.TypeVar('_ExcType', bound=BaseException)
_HandlerType = typing.Union[
	typing.Callable[[signal.Signals, FrameType], None],
	int,
	signal.Handlers,
	None
]
_HandlersListType = typing.List[typing.Dict[signal.Signals, _HandlerType]]


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


class catch_signals:
	r"""Return a context manager to catch signals to request listeners to shut down.

	Upon entrance to the context manager, a message at the :const:`logging.INFO`
	level is written to the logger whose name is this module's
	:const:`__package__` advising which signals are being listend for. Entrance
	to the context manager `returns
	<https://docs.python.org/3/reference/datamodel.html#object.__enter__>`_
	nothing and thus binds nothing but :const:`None` to the target of
	:keyword:`as <with>`.

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

	Availability: Unix (including macOS and Linux), Windows.

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

	:param signals: Signals from the :mod:`signal` module to listen for. If the
		objects in the iterable are :class:`int`\ s or :class:`str`\ s,
		:func:`catch_signals` attempts to convert them to
		:class:`signal.Signals`. The default includes :const:`~signal.SIGINT`,
		which Ctrl+C sends and normally causes Python to raise a
		:exc:`KeyboardInterrupt`.

		On Windows
			``signals`` must contain no signals other than
			:const:`~signal.SIGINT` or :const:`~signal.SIGBREAK`, the two of
			which are together the default.

		On Unix
			the default is :const:`~signal.SIGINT` and
			:const:`~signal.SIGTERM`. On macOS, :const:`~signal.SIGTERM` is what
			:program:`Activity Monitor` sends to processes when you select a
			program and hit :menuselection:`🛑 --> Quit`.

	:param callback: Called from within the installed signal handlers with the
		arguments that the Python :func:`~signal.signal` system passes to the handler,
		except that the ``signum`` argument is converted to type
		:class:`signal.Signals` first. The default, used if the argument is
		:const:`None`, logs the event at the :const:`logging.WARNING` level to
		the logger whose name is this module's :const:`__package__`.
	:raises KeyError: If the :mod:`signal` module does not recognize a string
		signal name in ``signals``.
	:raises TypeError: If ``callback`` isn't a callable taking two positional
		arguments.
	:raises ValueError: If called from a thread other than the main thread, or
		if ``signals`` is empty, or, if ``signals`` contains objects that cannot
		be converted to :class:`~signal.Signals` type, or, on Windows, if
		``signals`` contains signals other than those allowed.
	:return: A context manager to use in a :keyword:`with` block.

	.. versionadded:: 0.2.0
		The *callback* parameter.

	.. versionadded:: 0.3.0
		Windows support.

	.. versionchanged:: 0.3.0
		:func:`catch_signals` became reentrant and reusable.
	"""

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

	def __init__(
		self,
		signals: typing.Iterable[
			typing.Union[signal.Signals, int, str]] = _DEFAULT_SIGS,
		callback: typing.Optional[
			typing.Callable[[signal.Signals, typing.Optional[FrameType]], None]] = None,
	):
		signals = list(signals)
		signals_tmp = []  # type: typing.List[signal.Signals]
		for sig in signals:
			if isinstance(sig, int):
				sig = signal.Signals(sig)
			elif isinstance(sig, str):
				sig = signal.Signals[sig]
			if isinstance(sig, signal.Signals):  # This makes Mypy happy.
				signals_tmp.append(sig)
			else:
				raise ValueError('Cannot convert to signal.Signals: %r' % (sig,))
		if not signals:
			raise ValueError('No signals selected')
		if callback is None:
			callback = self._default_callback
		if not _two_pos_args(callback):
			raise TypeError(
				'callback is not a callable with two positional arguments: %r' %
				(callback,))
		if os.name == 'nt':
			if not (set(signals_tmp) <= set(self._DEFAULT_SIGS)):
				raise ValueError(
					"Windows does not support one of the signals: %r" % (signals,))
		self._signals = tuple(signals_tmp)  # type: typing.Tuple[signal.Signals, ...]
		self._callback = callback
		# No need for a lock because signals can only be set from the main thread.
		self._old_handlers = []  # type: _HandlersListType
		self._depth = 0

	def __enter__(self) -> None:
		"""Install signal handlers and log at :const:`logging.INFO` level."""
		self._old_handlers.append({})
		self._depth += 1
		names = []  # type: typing.List[str]
		for signum in self._signals:
			self._old_handlers[-1][signum] = self._install_handler(
				signum, self._callback)
			names.append(signum.name)
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
	) -> _HandlerType:
		"""Install shutdown handler for ``intended_signal`` & return its old handler.

		Must be called from the main thread.
		"""
		def handler(signum: signal.Signals, stack_frame: FrameType) -> None:
			signum = signal.Signals(signum)
			assert signum == intended_signal
			request()
			self._clear_signal_handlers()
			callback(signum, stack_frame)
		return signal.signal(intended_signal, handler)

	def _default_callback(
		self,
		signum: signal.Signals,
		stack_frame: typing.Optional[FrameType]
	) -> None:
		"""Write to the ``wrapitup`` log at :const:`logging.WARNING` level."""
		if signum == signal.SIGINT:
			msg = '. Press Ctrl+C again to exit immediately.'
		else:
			msg = ''
		_LOG.warning(
			'Commencing shut down. (Signal %s, process %d.)%s',
			signum.name, os.getpid(), msg)
