# © 2018, William Schwartz. All rights reserved. See the LICENSE file.

"""Implement the requests API."""

import threading


__all__ = ['request', 'reset', 'requested']


_flag = threading.Event()


def request() -> None:
	"""Request all listeners running in this process to shut down."""
	_flag.set()


def reset() -> None:
	"""Stop requesting listeners running in this process to shut down."""
	_flag.clear()


def requested() -> bool:
	"""Return whether listeners should shut down."""
	return _flag.is_set()
