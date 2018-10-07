from pathlib import Path
import re

from setuptools import setup


with open(str(Path(__file__).parent / 'shutdown' / '_version.py')) as file:
	version = file.read().strip()
match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", version, re.MULTILINE)
if match:
	version = match.group(1)
else:
	raise ValueError('Cannot find version number')


setup(
	name='shutdown',
	version=version,
	description= None,
	packages=['shutdown'],
	package_data={'shutdown': ['py.typed']},
	author='William Schwartz',
	url='https://github.com/wkschwartz/shutdown',
	python_requires='>=3.3', # Requires time.monotonic
	zip_safe=False,
)
