# shutdown
Tools for requesting long-running process shutdown gracefully

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
