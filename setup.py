from setuptools import setup


setup(
	name='shutdown',
	version='0.2.0',
	packages=['shutdown'],
	package_data={'shutdown': ['py.typed']},
	author='William Schwartz',
	url='https://github.com/wkschwartz/shutdown',
	python_requires='>=3.3', # Requires time.monotonic
	zip_safe=False,
)
