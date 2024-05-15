import pytest
import sys
import subprocess
from pathlib import Path
import json

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='Unix-only')


def seq2p(tests_dir, seq):
    return tests_dir / f"test_{seq}.py"


FAILURES = {
    'assert': 'assert False',
    'exception': 'raise RuntimeError("test")',
    'kill': 'os.kill(os.getpid(), 9)',
    'exit': 'pytest.exit("goodbye")',
    'interrupt': 'raise KeyboardInterrupt()'
}

N_TESTS=10
def make_polluted_suite(tests_dir: Path, fail_collect: bool, fail_kind: str):
    """In a suite with 10 tests, test 6 fails; test 3 doesn't fail, but causes 6 to fail."""

    for seq in range(N_TESTS):
        seq2p(tests_dir, seq).write_text('def test_foo(): pass')

    polluter = seq2p(tests_dir, 3)
    polluter.write_text("import sys\n" + "sys.foobar = True\n" + "def test_foo(): pass")

    failing = seq2p(tests_dir, 6)
    failing.write_text(f"""\
import sys
import os
import pytest

def failure():
    {FAILURES[fail_kind]}

def test_foo():
    if getattr(sys, 'foobar', False):
        failure()

{'test_foo()' if fail_collect else ''}
""")

    return failing, polluter


@pytest.mark.parametrize("fail_collect", [True, False])
@pytest.mark.parametrize("fail_kind", list(FAILURES.keys() - {'kill'}))
def test_check_suite_fails(tmp_path, monkeypatch, fail_collect, fail_kind):
    monkeypatch.chdir(tmp_path)
    tests_dir = Path('tests')
    tests_dir.mkdir()
    make_polluted_suite(tests_dir, fail_collect, fail_kind)

    p = subprocess.run([sys.executable, '-m', 'pytest', tests_dir], check=False)
    if fail_collect or fail_kind in ('exit', 'interrupt'):
        assert p.returncode == pytest.ExitCode.INTERRUPTED
    else:
        assert p.returncode == pytest.ExitCode.TESTS_FAILED


@pytest.mark.parametrize("fail_collect", [True, False])
@pytest.mark.parametrize("fail_kind", list(FAILURES.keys()))
def test_isolate_polluted(tmp_path, monkeypatch, fail_collect, fail_kind):
    monkeypatch.chdir(tmp_path)
    tests_dir = Path('tests')
    tests_dir.mkdir()
    make_polluted_suite(tests_dir, fail_collect, fail_kind)

    p = subprocess.run([sys.executable, '-m', 'pytest', '--cleanslate', tests_dir], check=False)
    assert p.returncode == pytest.ExitCode.OK


@pytest.mark.parametrize("fail_kind", list(FAILURES.keys()))
def test_pytest_discover_tests(tmp_path, fail_kind, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tests_dir = Path('tests')
    tests_dir.mkdir()
    make_polluted_suite(tests_dir, fail_collect=False, fail_kind=fail_kind)

    p = subprocess.run([sys.executable, '-m', 'pytest', '--cleanslate'], check=False) # no tests_dir here
    assert p.returncode == pytest.ExitCode.OK


@pytest.mark.parametrize("fail_collect", [True, False])
@pytest.mark.parametrize("fail_kind", list(FAILURES.keys()))
def test_unconditionally_failing_test(tmp_path, monkeypatch, fail_collect, fail_kind):
    monkeypatch.chdir(tmp_path)
    tests_dir = Path('tests')
    tests_dir.mkdir()
    make_polluted_suite(tests_dir, fail_collect, fail_kind)

    # _unconditionally_ failing test
    failing = seq2p(tests_dir, 2)
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


def test_isolate_module_yields_collector(tmp_path, monkeypatch):
    # A pytest.Collector.collect()'s return value may include not only pytest.Item,
    # but also pytest.Collector.
    #
    # Here we test for this by including a class within the test module:
    # when the module is being collected, pytest.Module.collect() will include
    # a pytest.Class collector to actually collect items from within the class.

    monkeypatch.chdir(tmp_path)
    tests_dir = Path('tests')
    tests_dir.mkdir()

    test = seq2p(tests_dir, 1)
    test.write_text("""\
class TestClass:
    def test_foo(self):
        assert True
""")

    p = subprocess.run([sys.executable, '-m', 'pytest', '--cleanslate', tests_dir], check=False)
    assert p.returncode == pytest.ExitCode.OK
