# wrapitup
Tools for requesting long-running process shut down gracefully.

[![Build Status](https://travis-ci.org/wkschwartz/wrapitup.svg?branch=master)](https://travis-ci.org/wkschwartz/wrapitup)
[![Coverage Status](https://coveralls.io/repos/github/wkschwartz/wrapitup/badge.svg?branch=master)](https://coveralls.io/github/wkschwartz/wrapitup?branch=master)
[![Docs](https://readthedocs.org/projects/wrapitup/badge/?version=latest)](https://wrapitup.readthedocs.io/en/latest/?badge=latest)

## Installation for development

Once you have the repository, change into its root directory, create a virtual
environment, and install it.

```bash
$ git clone https://github.com/wkschwartz/wrapitup
$ cd wrapitup
$ python3 -m venv venv
$ source venv/bin/activate # may differ on Windows
(venv) $ pip install -e .  # or python setup.py develop
```

## Updating the version

The version lives in exactly one place, `wrapitup/_version.py`.

## Running the tests

Install prerequisites using
```bash
(venv) $ pip install -r tests/requirements.txt
```

Use
```bash
(venv) $ python -m unittest discover tests
```

On Windows, you can run the tests only with `cmd.exe`. The tests pass in
PowerShell, but then PowerShell exits automatically. (By the way, if you want
to activate a virtual environment in PowerShell, you may need to execute
`Set-ExecutionPolicy RemoteSigned` as Administrator first.) They do not run in
MinGW (which is what Git Bash uses) using `winpty python`, and crash the
terminal without `winpty`. I have not tested WrapItUp in Cygwin.

Then you can Mypy, Flake8, and Coverage.py as in `.travis.yml`.

## Building the documentation

To build the documentation, use [Sphinx](http://www.sphinx-doc.org).
First, install it, then switch to the `docs` directory, and then build the
documentation in the format you want.
```bash
(venv) $ pip install -r docs/requirements.txt
(venv) $ cd docs
(venv) $ make html
```
