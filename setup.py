from pathlib import Path
import re

from setuptools import setup


with open(str(Path(__file__).parent / 'wrapitup' / '_version.py')) as file:
	version = file.read().strip()
match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", version, re.MULTILINE)
if match:
	version = match.group(1)
else:
	raise ValueError('Cannot find version number')


setup(
	name='wrapitup',
	version=version,
	description="Tools for requesting long-running processes shut down gracefully",
	packages=['wrapitup'],
	package_data={'wrapitup': ['py.typed']},
	author='William Schwartz',
	url='https://github.com/wkschwartz/wrapitup',
	# Requires time.monotonic (introduced in 3.3). Assumes all signals are
	# available from signal.Signals enum, introduced in 3.5.
	python_requires='>=3.5',
	zip_safe=False,
	classifiers = [
		'Development Status :: 5 - Production/Stable',
		'Intended Audience :: Developers',
		'License :: OSI Approved :: BSD License',
		'Programming Language :: Python :: 3.5',
		'Programming Language :: Python :: 3.6',
		'Programming Language :: Python :: 3.7',
		'Programming Language :: Python :: 3 :: Only',
		'Programming Language :: Python :: Implementation :: CPython',
		'Programming Language :: Python :: Implementation :: PyPy',
	]
)
