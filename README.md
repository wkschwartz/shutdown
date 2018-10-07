# shutdown
Tools for requesting long-running process shutdown gracefully

[![Coverage Status](https://coveralls.io/repos/github/wkschwartz/shutdown/badge.svg?branch=master)](https://coveralls.io/github/wkschwartz/shutdown?branch=master)

## Installation for development or building the documentation

Once you have the repository, change into its root directory, create a virtual
environment, and install it.

```bash
$ git clone https://github.com/wkschwartz/shutdown
$ cd shutdown
$ python3 -m venv venv
$ source venv/bin/activate # may differ on Windows
(venv) $ pip install -e .  # or python setup.py develop
```

## Updating the version

The version lives in exactly one place, `shutdown/_version.py`.

## Building the documentation

To build the documentation, use [Sphinx](http://www.sphinx-doc.org).
First, install it, then switch to the `docs` directory, and then build the
documentation in the format you want.
```bash
(venv) $ pip install sphinx
(venv) $ cd docs
(venv) $ make html
```
If Sphinx complains that it cannot import shutdown, make sure you have installed
shutdown.
