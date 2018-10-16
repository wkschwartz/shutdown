# © 2018, William Schwartz. All rights reserved. See the LICENSE file.

r"""Facilitate interrupting slow code with signals and time limits.

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


from wrapitup._catch_signals import catch_signals
from wrapitup._requests import request, reset, requested
from wrapitup._version import __version__
from wrapitup._timer import Timer


__all__ = [
	'request', 'reset', 'requested', 'catch_signals', 'Timer', '__version__']
