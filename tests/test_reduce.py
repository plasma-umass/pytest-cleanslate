import pytest
import subprocess
import sys
from test_cleanslate import seq2p, tests_dir, make_polluted_suite, FAILURES
import json
from textwrap import dedent
from pathlib import Path

from pytest_cleanslate.reduce import MODULE_LIST_ARG, TEST_LIST_ARG, RESULTS_ARG, Results


def get_test_module(testid):
    return testid.split('::')[0]


def test_results_collect_failure(tests_dir):
    test1 = seq2p(tests_dir, 1)
    test1.write_text(dedent("""\
        def test_one():
            assert True
        """))

    test2 = seq2p(tests_dir, 2)
    test2.write_text(dedent("""\
        blargh this ain't python
        """))

    results_file = tests_dir.parent / "results.json"

    p = subprocess.run([sys.executable, '-m', 'pytest',
                        '-p', 'pytest_cleanslate.reduce', RESULTS_ARG, results_file],
                        check=False)
    assert p.returncode == pytest.ExitCode.INTERRUPTED

    r = Results(results_file)

    assert r.get_outcome(f"{test1}") == 'passed'
    assert r.get_outcome(f"{test2}") == 'failed'


@pytest.mark.parametrize('get_results', [False, True])
def test_module_list(tests_dir, get_results):
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

    modules = tests_dir.parent / "modules.txt"
    modules.write_text(dedent(f"""\
        {test1}
        {test3}
        """))

    results_file = tests_dir.parent / "results.json"

    p = subprocess.run([sys.executable, '-m', 'pytest',
                        '-p', 'pytest_cleanslate.reduce', MODULE_LIST_ARG, modules,
                        *((RESULTS_ARG, results_file) if get_results else ())],
                        check=False)
    assert p.returncode == pytest.ExitCode.TESTS_FAILED

    if get_results:
        r = Results(results_file)

        ids = r.get_tests()
        # the order should be as executed
        assert ids.index(f"{test1}::test_one") < ids.index(f"{test1}::test_two")

        assert r.get_outcome(f"{test1}::test_one") == 'passed'
        assert r.get_outcome(f"{test1}::test_two") == 'failed'
        assert r.get_outcome(f"{test3}::test_nothing") == 'passed'


@pytest.mark.parametrize('get_results', [False, True])
def test_test_list(tests_dir, get_results):
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

    results_file = tests_dir.parent / "results.json"

    p = subprocess.run([sys.executable, '-m', 'pytest',
                        '-p', 'pytest_cleanslate.reduce', TEST_LIST_ARG, tests, *((RESULTS_ARG, results_file) if get_results else ())],
                        check=False)
    assert p.returncode == pytest.ExitCode.OK

    if get_results:
        r = Results(results_file)

        assert r.get_outcome(f"{test1}") == 'passed'
        assert r.get_outcome(f"{test2}") == 'passed'
        assert f"{test1}::test_one" not in r.get_tests()
        assert r.get_outcome(f"{test1}::test_two") == 'passed'
        assert r.get_outcome(f"{test2}::test_one") == 'passed'


@pytest.mark.parametrize("n_tests", [0, 1, 10])
def test_reduce_nothing_fails(tests_dir, n_tests):
    for seq in range(n_tests):
        seq2p(tests_dir, seq).write_text('def test_foo(): pass')

    reduction_file = tests_dir.parent / "reduction.json"

    p = subprocess.run([sys.executable, '-m', 'pytest_cleanslate.reduce',
                        '--save-to', reduction_file, '--trace', tests_dir], check=False)
    assert p.returncode == 1

    with reduction_file.open("r") as f:
        reduction = json.load(f)

    assert reduction['failed'] == None
    assert 'error' in reduction


def test_reduce_test_fails_by_itself(tests_dir):
    for seq in range(10):
        seq2p(tests_dir, seq).write_text('def test_foo(): pass')

    failing = seq2p(tests_dir, 3)
    failing.write_text('def test_foo(): assert False')

    reduction_file = tests_dir.parent / "reduction.json"

    p = subprocess.run([sys.executable, '-m', 'pytest_cleanslate.reduce',
                        '--save-to', reduction_file, '--trace', tests_dir], check=False)
    assert p.returncode == 1

    with reduction_file.open("r") as f:
        reduction = json.load(f)

    assert reduction['failed'] == f"{failing}::test_foo"
    assert 'error' in reduction


@pytest.mark.parametrize("pollute_in_collect, fail_collect", [[False, False], [True, False], [True, True]])
def test_reduce(tests_dir, pollute_in_collect, fail_collect):
    failing, polluter, tests = make_polluted_suite(tests_dir, fail_collect=fail_collect, pollute_in_collect=pollute_in_collect)

    reduction_file = tests_dir.parent / "reduction.json"

    p = subprocess.run([sys.executable, '-m', 'pytest_cleanslate.reduce',
                        '--save-to', reduction_file, '--trace', tests_dir], check=False)
    assert p.returncode == 0

    with reduction_file.open("r") as f:
        reduction = json.load(f)

    assert reduction['failed'] == failing
    assert reduction['modules'] == [get_test_module(polluter)]
    assert reduction['tests'] == [] if pollute_in_collect else [polluter]


def test_reduce_other_collection_fails(tests_dir):
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

    reduction_file = tests_dir.parent / "reduction.json"

    p = subprocess.run([sys.executable, '-m', 'pytest_cleanslate.reduce',
                        '--save-to', reduction_file, '--trace', tests_dir], check=False)
    assert p.returncode == 0

    with reduction_file.open("r") as f:
        reduction = json.load(f)

    assert reduction['failed'] == failing
    assert reduction['modules'] == [get_test_module(polluter)]
    assert reduction['tests'] == []


@pytest.mark.parametrize("pollute_in_collect, fail_collect", [[False, False], [True, False], [True, True]])
def test_reduce_pytest_args(tests_dir, pollute_in_collect, fail_collect):
    failing, polluter, tests = make_polluted_suite(tests_dir, fail_collect=fail_collect, pollute_in_collect=pollute_in_collect)

    (tests_dir / "conftest.py").write_text(dedent("""\
        if read, this breaks everything
        """))

    reduction_file = tests_dir.parent / "reduction.json"

    p = subprocess.run([sys.executable, '-m', 'pytest_cleanslate.reduce',
                        '--save-to', reduction_file, '--trace',
                        '--pytest-args=--noconftest', tests_dir], check=False)
    assert p.returncode == 0

    with reduction_file.open("r") as f:
        reduction = json.load(f)

    assert reduction['failed'] == failing
    assert reduction['modules'] == [get_test_module(polluter)]
    assert reduction['tests'] == [] if pollute_in_collect else [polluter]


def test_reduce_polluter_test_in_single_module(tests_dir):
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

    reduction_file = tests_dir.parent / "reduction.json"

    p = subprocess.run([sys.executable, '-m', 'pytest_cleanslate.reduce',
                        '--save-to', reduction_file, '--trace', tests_dir], check=False)
    assert p.returncode == 0

    with reduction_file.open("r") as f:
        reduction = json.load(f)

    assert reduction['failed'] == f"{str(test)}::test_failing"
    assert reduction['modules'] == []
    assert reduction['tests'] == [f"{str(test)}::test_polluter"]
