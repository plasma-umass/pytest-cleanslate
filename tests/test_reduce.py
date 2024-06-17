import pytest
import subprocess
import typing as T
import sys
from test_cleanslate import seq2p, tests_dir, make_polluted_suite, FAILURES
import json
from textwrap import dedent
from pathlib import Path

import pytest_cleanslate.reduce as reduce

from pytest_cleanslate.reduce import MODULE_LIST_ARG, TEST_LIST_ARG, RESULTS_ARG, Results, \
            get_module, get_function


def test_get_module():
    assert 'test.py' == get_module('test.py')
    assert 'test.py' == get_module('test.py::test_foo')
    assert 'test.py' == get_module('test.py::test_foo[1]')


def test_get_function():
    assert None == get_function('test.py')
    assert 'test_foo' == get_function('test.py::test_foo')
    assert 'test_foo' == get_function('test.py::test_foo[1]')


def test_run_pytest_collect_failure(tests_dir):
    test1 = seq2p(tests_dir, 1)
    test1.write_text(dedent("""\
        def test_one():
            assert True
        """))

    test2 = seq2p(tests_dir, 2)
    test2.write_text(dedent("""\
        blargh this ain't python
        """))

    r = reduce.run_pytest(tests_dir)

    assert r.get_outcome(f"{test1}") == 'passed'
    assert r.get_outcome(f"{test2}") == 'failed'


def test_run_pytest_module_list(tests_dir):
    test1 = seq2p(tests_dir, 1)
    test1.write_text(dedent("""\
        def test_one():
            assert True

        def test_two():
            assert False
        """))

    test2 = seq2p(tests_dir, 2)
    test2.write_text(dedent("""\
        blargh this ain't python
        """))

    test3 = seq2p(tests_dir, 3)
    test3.write_text(dedent("""\
        def test_nothing():
            pass
        """))

    r = reduce.run_pytest(tests_dir, modules=[str(test1), str(test3)])
    ids = r.get_tests()
    # the order should be as executed
    assert ids.index(f"{test1}::test_one") < ids.index(f"{test1}::test_two")

    assert r.get_outcome(f"{test1}::test_one") == 'passed'
    assert r.get_outcome(f"{test1}::test_two") == 'failed'
    assert r.get_outcome(f"{test3}::test_nothing") == 'passed'


def test_run_pytest_test_list(tests_dir):
    test1 = seq2p(tests_dir, 1)
    test1.write_text(dedent("""\
        def test_one():
            assert False

        def test_two():
            assert True
        """))

    test2 = seq2p(tests_dir, 2)
    test2.write_text(dedent("""\
        def test_one():
            assert True 
        """))

    tests = tests_dir.parent / "tests.txt"
    tests.write_text(dedent(f"""\
        {test1}::test_two
        {test2}::test_one
        """))

    r = reduce.run_pytest(tests_dir, tests=[f"{test1}::test_two", f"{test2}::test_one"])
    assert r.get_outcome(f"{test1}") == 'passed'
    assert r.get_outcome(f"{test2}") == 'passed'
    assert f"{test1}::test_one" not in r.get_tests()
    assert r.get_outcome(f"{test1}::test_two") == 'passed'
    assert r.get_outcome(f"{test2}::test_one") == 'passed'


def cli_reduce(*, tests_path: Path, pytest_args: T.List[str] = (), trace: bool = False, **args) -> dict:
    reduction_file = tests_path.parent / "reduction.json"

    p = subprocess.run([sys.executable, '-m', 'pytest_cleanslate.reduce',
                        '--save-to', reduction_file,
                        *((f"--pytest-args={' '.join(pytest_args)}",) if pytest_args else ()),
                        *(("--trace",) if trace else ()),
                        *(f"--{name}={value}" for name, value in args.items()),
                        tests_path], check=False)

    with reduction_file.open("r") as f:
        reduction = json.load(f)

    assert 'error' not in reduction or p.returncode == 1
    return reduction


@pytest.mark.parametrize("n_tests", [0, 1, 10])
@pytest.mark.parametrize("r", [reduce.reduce, cli_reduce])
def test_reduce_nothing_fails(tests_dir, n_tests, r):
    for seq in range(n_tests):
        seq2p(tests_dir, seq).write_text('def test_foo(): pass')

    reduction = r(tests_path=tests_dir, trace=True)

    assert reduction['failed'] == None
    assert 'error' in reduction


@pytest.mark.parametrize("r", [reduce.reduce, cli_reduce])
def test_reduce_test_fails_by_itself(tests_dir, r):
    for seq in range(10):
        seq2p(tests_dir, seq).write_text('def test_foo(): pass')

    failing = seq2p(tests_dir, 3)
    failing.write_text('def test_foo(): assert False')

    reduction = r(tests_path=tests_dir, trace=True)

    assert reduction['failed'] == f"{failing}::test_foo"
    assert 'error' in reduction


@pytest.mark.parametrize("pollute_in_collect, fail_collect", [[False, False], [True, False], [True, True]])
@pytest.mark.parametrize("r", [reduce.reduce, cli_reduce])
def test_reduce(tests_dir, pollute_in_collect, fail_collect, r):
    failing, polluter, tests = make_polluted_suite(tests_dir, fail_collect=fail_collect,
                                                   pollute_in_collect=pollute_in_collect)

    reduction_file = tests_dir.parent / "reduction.json"

    reduction = r(tests_path=tests_dir, trace=True)

    assert reduction['failed'] == failing
    assert reduction['modules'] == [get_module(polluter)]
# this would be more precise... is it the test or the module?
#    assert reduction['modules'] == ([get_module(polluter)] if pollute_in_collect else [])
    assert reduction['tests'] == ([] if pollute_in_collect else [polluter])


@pytest.mark.parametrize("pollute_in_collect, fail_collect", [[False, False], [True, False], [True, True]])
@pytest.mark.parametrize("r", [reduce.reduce, cli_reduce])
def test_reduce_pytest_args(tests_dir, pollute_in_collect, fail_collect, r):
    failing, polluter, tests = make_polluted_suite(tests_dir, fail_collect=fail_collect,
                               pollute_in_collect=pollute_in_collect)

    (tests_dir / "conftest.py").write_text(dedent("""\
        if read, this breaks everything
        """))

    reduction = r(tests_path=tests_dir, trace=True, pytest_args=['--noconftest'])

    assert reduction['failed'] == failing
    assert reduction['modules'] == [get_module(polluter)]
# this would be more precise... is it the test or the module?
#    assert reduction['modules'] == ([get_module(polluter)] if pollute_in_collect else [])
    assert reduction['tests'] == ([] if pollute_in_collect else [polluter])


@pytest.mark.parametrize("r", [reduce.reduce, cli_reduce])
def test_reduce_other_collection_fails(tests_dir, r):
    """Tests that we use --continue-on-collection-errors"""
    failing, polluter, tests = make_polluted_suite(tests_dir, pollute_in_collect=True, fail_collect=False,
                                                   polluter_seq = 3, failing_seq = 8)

    seq2p(tests_dir, 0).write_text(dedent("""\
        import sys
        sys.needs_this = True

        def test_nothing():
            assert True
        """))

    # this one fails collection pytest runs set to ignore the one above
    seq2p(tests_dir, 2).write_text(dedent("""\
        import sys

        if not hasattr(sys, 'needs_this'):
            raise RuntimeError('argh')

        def test_nothing():
            assert True
        """))

    reduction = r(tests_path=tests_dir, trace=True)

    assert reduction['failed'] == failing
    assert reduction['modules'] == [get_module(polluter)]
    assert reduction['tests'] == []


@pytest.mark.parametrize("r", [reduce.reduce, cli_reduce])
def test_reduce_polluter_test_in_single_module(tests_dir, r):
    test = seq2p(tests_dir, 0)
    test.write_text(dedent("""\
        import sys

        def test_polluter():
            sys.needs_this = True
            assert True

        def test_nothing():
            assert True

        def test_failing():
            assert not hasattr(sys, 'needs_this')
        """))

    reduction = r(tests_path=tests_dir, trace=True)

    assert reduction['failed'] == f"{str(test)}::test_failing"
    assert reduction['modules'] == []
    assert reduction['tests'] == [f"{str(test)}::test_polluter"]
