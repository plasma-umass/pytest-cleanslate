# pytest-CleanSlate: work around test state pollution
by [Juan Altmayer Pizzorno](https://jaltmayerpizzorno.github.io) and [Emery Berger](https://emeryberger.com)
at UMass Amherst's [PLASMA lab](https://plasma-umass.org/).

[![license](https://img.shields.io/github/license/plasma-umass/pytest-cleanslate?color=blue)](LICENSE)
[![pypi](https://img.shields.io/pypi/v/pytest-cleanslate?color=blue)](https://pypi.org/project/pytest-cleanslate/)
[![Downloads](https://static.pepy.tech/badge/pytest-cleanslate)](https://pepy.tech/project/pytest-cleanslate)
![pyversions](https://img.shields.io/pypi/pyversions/pytest-cleanslate?logo=python&logoColor=FBE072)
![tests](https://github.com/plasma-umass/pytest-cleanslate/workflows/tests/badge.svg)

## About
pytest-cleanslate is a small plugin for the [pytest](https://github.com/pytest-dev/pytest)
test framework which, as the name implies, helps give each test module a "clean slate" to execute.
Plugins such as [pytest-forked](https://github.com/pytest-dev/pytest-forked) and
[pytest-isolate](https://github.com/gilfree/pytest-isolate) allow you to execute tests
in separate processes, working around in-memory test "state pollution" resulting from
their execution, but do not protect against pollution caused by top-level code in test
modules. This is what pytest-CleanSlate remedies.
