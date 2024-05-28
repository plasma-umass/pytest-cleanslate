# pytest-cleanslate: work around or find test state pollution
by [Juan Altmayer Pizzorno](https://jaltmayerpizzorno.github.io) and [Emery Berger](https://emeryberger.com)
at UMass Amherst's [PLASMA lab](https://plasma-umass.org/).

[![license](https://img.shields.io/github/license/plasma-umass/pytest-cleanslate?color=blue)](LICENSE)
[![pypi](https://img.shields.io/pypi/v/pytest-cleanslate?color=blue)](https://pypi.org/project/pytest-cleanslate/)
![pyversions](https://img.shields.io/pypi/pyversions/pytest-cleanslate?logo=python&logoColor=FBE072)
![tests](https://github.com/plasma-umass/pytest-cleanslate/workflows/tests/badge.svg)
[![Downloads](https://static.pepy.tech/badge/pytest-cleanslate)](https://pepy.tech/project/pytest-cleanslate)

## About
pytest-cleanslate is a small plugin for the [pytest](https://github.com/pytest-dev/pytest)
test framework which, as the name implies, helps give each test module a "clean slate" to execute.
Plugins such as [pytest-forked](https://github.com/pytest-dev/pytest-forked) and
[pytest-isolate](https://github.com/gilfree/pytest-isolate) allow you to execute tests
in separate processes, working around in-memory test "state pollution" resulting from
their execution, but do not protect against pollution caused by top-level code in test
modules; this is what pytest-cleanslate remedies.

This module also includes `cleanslate-reduce`, a tool for finding where the state pollution
is occurring.
Invoked on a test suite with a failing test, `cleanslate-reduce` looks for a smaller
set of test modules and functions that still lead to the test failure.

## How to use
After `pip install pytest-cleanslate`, simply add `--cleanslate` to your `pytest` command line (or configuration options).

## Interaction with other plugins
Running with `--cleanslate` also makes use of `pytest-forked`, i.e., it is as though you installed that
plugin and passed in `--forked` to execute all tests in separate processes.

It also subverts somewhat `pytest`'s mode of operation in that it postpones collecting
test items within test modules (i.e., within Python test files) until the test execution phase.
While we have attempted to stay as compatible with other plugins as possible, it is likely
to not work in some combinations (such as, for example, [pytest-xdist](https://github.com/pytest-dev/pytest-xdist)).
Feel free to [open an issue](https://github.com/plasma-umass/pytest-cleanslate/issues) if you come across a case where it doesn't work.

## Requirements
Python 3.8+, Linux or MacOS.
