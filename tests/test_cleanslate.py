import pytest
import sys
import subprocess
from pathlib import Path
import json
import random
from textwrap import dedent

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='Unix-only')


def seq2p(tests_dir, seq):
    return tests_dir / f"test_{seq:02}.py"


FAILURES = {
    'assert': 'assert False',
    'exception': 'raise RuntimeError("test")',
    'kill': 'os.kill(os.getpid(), 9)',
    'exit': 'pytest.exit("goodbye")',
    'interrupt': 'raise KeyboardInterrupt()'
}

def make_polluted_suite(tests_dir: Path, *, pollute_in_collect: bool = True, fail_collect: bool = False,
                        fail_kind: str = 'assert', polluter_seq: int = None, failing_seq: int = None):
    """in a suite with 10 tests, 'polluter' doesn't fail, but causes 'failing' to fail."""
    # note the polluter must run before the failing test
    N_TESTS = 10

    assert (polluter_seq is None and failing_seq is None) or (failing_seq > polluter_seq)

    if polluter_seq is None:
        polluter_seq = random.choice(range(N_TESTS-1))

    polluter = seq2p(tests_dir, polluter_seq)
    if pollute_in_collect:
        polluter.write_text(dedent("""\
            import sys
            sys.foobar=True

            def test_bar():
                assert True
            """))
    else:
        polluter.write_text(dedent("""\
            import sys

            def test_polluter():
                sys.foobar=True
                assert True

            def test_bar():
                assert True
            """))
        polluter = f"{polluter}::test_polluter"

    if failing_seq is None:
        failing_seq = random.choice(range(polluter_seq+1, N_TESTS))

    failing = seq2p(tests_dir, failing_seq)
    if fail_collect:
        failing.write_text(dedent(f"""\
            import sys
            import os
            import pytest

            if getattr(sys, 'foobar', False):
                {FAILURES[fail_kind]}

            def test_ok():
                assert True
            """))
    else:
        failing.write_text(dedent(f"""\
            import sys
            import os
            import pytest

            def test_failing():
                if getattr(sys, 'foobar', False):
                    {FAILURES[fail_kind]}

            def test_ok():
                assert True
            """))
        failing = f"{failing}::test_failing"

    tests = [seq for seq in range(N_TESTS) if seq not in (polluter_seq, failing_seq)]
    for seq in tests:
        seq2p(tests_dir, seq).write_text('def test_foo(): pass')

    return str(failing), str(polluter), tests


@pytest.fixture
def tests_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tests_dir = Path('tests')
    tests_dir.mkdir()
    yield tests_dir


@pytest.mark.parametrize("pollute_in_collect, fail_collect", [[False, False], [True, False], [True, True]])
@pytest.mark.parametrize("fail_kind", list(FAILURES.keys() - {'kill'}))
def test_check_suite_fails(tests_dir, pollute_in_collect, fail_collect, fail_kind):
    make_polluted_suite(tests_dir, pollute_in_collect=pollute_in_collect,
                        fail_collect=fail_collect, fail_kind=fail_kind)

    p = subprocess.run([sys.executable, '-m', 'pytest', tests_dir], check=False)
    if fail_collect or fail_kind in ('exit', 'interrupt'):
        assert p.returncode == pytest.ExitCode.INTERRUPTED
    else:
        assert p.returncode == pytest.ExitCode.TESTS_FAILED


@pytest.mark.parametrize("plugin", ['asyncio', 'no:asyncio'])
@pytest.mark.parametrize("pollute_in_collect, fail_collect", [[False, False], [True, False], [True, True]])
@pytest.mark.parametrize("fail_kind", list(FAILURES.keys()))
def test_isolate_polluted(tests_dir, pollute_in_collect, fail_collect, fail_kind, plugin):
    make_polluted_suite(tests_dir, pollute_in_collect=pollute_in_collect,
                        fail_collect=fail_collect, fail_kind=fail_kind)

    p = subprocess.run([sys.executable, '-m', 'pytest', '-p', plugin, '--cleanslate', tests_dir], check=False)
    assert p.returncode == pytest.ExitCode.OK


@pytest.mark.parametrize("fail_kind", list(FAILURES.keys()))
def test_pytest_discover_tests(tests_dir, fail_kind):
    make_polluted_suite(tests_dir, fail_collect=False, fail_kind=fail_kind)

    p = subprocess.run([sys.executable, '-m', 'pytest', '--cleanslate'], check=False) # no tests_dir here
    assert p.returncode == pytest.ExitCode.OK


@pytest.mark.parametrize("pollute_in_collect, fail_collect", [[False, False], [True, False], [True, True]])
@pytest.mark.parametrize("fail_kind", list(FAILURES.keys()))
def test_unconditionally_failing_test(tests_dir, pollute_in_collect, fail_collect, fail_kind):
    _, _, tests = make_polluted_suite(tests_dir, pollute_in_collect=pollute_in_collect,
                                      fail_collect=fail_collect, fail_kind=fail_kind)

    # _unconditionally_ failing test
    failing = seq2p(tests_dir, random.choice(tests))
    failing.write_text(f"""\
import sys
import os
import pytest

def failure():
    {FAILURES[fail_kind]}

def test_foo():
    failure()

{'test_foo()' if fail_collect else ''}
""")

    p = subprocess.run([sys.executable, '-m', 'pytest', '--cleanslate', tests_dir], check=False)
    assert p.returncode == pytest.ExitCode.TESTS_FAILED


def test_isolate_module_yields_collector(tests_dir):
    # A pytest.Collector.collect()'s return value may include not only pytest.Item,
    # but also pytest.Collector.
    #
    # Here we test for this by including a class within the test module:
    # when the module is being collected, pytest.Module.collect() will include
    # a pytest.Class collector to actually collect items from within the class.

    test = seq2p(tests_dir, 1)
    test.write_text("""\
class TestClass:
    def test_foo(self):
        assert True
""")

    p = subprocess.run([sys.executable, '-m', 'pytest', '--cleanslate', tests_dir], check=False)
    assert p.returncode == pytest.ExitCode.OK


# If asyncio is missing/disabled, the test may show as skipped; we detect it here
# with the 'fail=True' version of the test.
@pytest.mark.parametrize("fail", [False, True])
def test_asyncio(tests_dir, fail):
    test = seq2p(tests_dir, 1)
    test.write_text(f"""\
import pytest
import asyncio

async def foo(s):
    return s

@pytest.mark.asyncio
async def test_asyncio():
    assert "bar" {'!=' if fail else '=='} await foo("bar")
""")

    p = subprocess.run([sys.executable, '-m', 'pytest', '--cleanslate', tests_dir], check=False)
    if fail:
        assert p.returncode == pytest.ExitCode.TESTS_FAILED
    else:
        assert p.returncode == pytest.ExitCode.OK


@pytest.mark.parametrize("tf", ['test_one', 'test_two'])
def test_mark(tests_dir, tf):
    # the built-in "mark" plugin implements '-k' and '-m'

    test = seq2p(tests_dir, 1)
    test.write_text("""\
def test_one():
    assert True

def test_two():
    assert False
""")

    p = subprocess.run([sys.executable, '-m', 'pytest', '--cleanslate', '-k', tf, tests_dir], check=False)
    if tf == 'test_two':
        assert p.returncode == pytest.ExitCode.TESTS_FAILED
    else:
        assert p.returncode == pytest.ExitCode.OK


def test_exitfirst(tests_dir):
    test = seq2p(tests_dir, 1)
    test.write_text("""\
from pathlib import Path

def test_one():
    assert False

def test_two():
    Path('litmus.txt').touch()
""")

    p = subprocess.run([sys.executable, '-m', 'pytest', '--cleanslate', '--exitfirst', '-s', tests_dir], check=False,
                       capture_output=True)
    assert p.returncode == pytest.ExitCode.TESTS_FAILED
    assert not Path('litmus.txt').exists()
    assert 'CRASHED' not in str(p.stdout, 'utf-8')


def test_shouldstop(tests_dir):
    test = seq2p(tests_dir, 1)
    test.write_text("""\
import pytest
from pathlib import Path

def test_one():
    assert False

def test_two():
    Path('litmus.txt').touch()
""")

    # --stepwise sets session.shouldstop upon a test failure.
    p = subprocess.run([sys.executable, '-m', 'pytest', '--cleanslate', '--stepwise', '-s', tests_dir], check=False,
                       capture_output=True)
    assert p.returncode == pytest.ExitCode.INTERRUPTED
    assert not Path('litmus.txt').exists()
    assert 'CRASHED' not in str(p.stdout, 'utf-8')


def test_polluter_test_in_single_module(tests_dir):
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

    p = subprocess.run([sys.executable, '-m', 'pytest', '--cleanslate', tests_dir], check=False)
    assert p.returncode == pytest.ExitCode.OK
