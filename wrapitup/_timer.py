# © 2018, William Schwartz. All rights reserved. See the LICENSE file.

"""Implements the timer API."""


from math import isnan
import signal
from time import monotonic
import typing

from wrapitup._requests import requested


__all__ = ['Timer']


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

	def __init__(self, limit: float = float('inf')):
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

	if hasattr(signal, "setitimer"):  # pragma: no branch
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
