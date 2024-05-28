import pytest
from _pytest.pathlib import Path
import typing as T
import json
import sys
from .__version__ import __version__


PYTEST_ARGS = ('-qq', '-p', 'pytest_cleanslate.reduce')
MODULE_LIST_ARG = '--module-list-from'
TEST_LIST_ARG = '--test-list-from'
RESULTS_ARG = '--results-to'


class ReducePlugin:
    def __init__(self, config: pytest.Config) -> None:
        if (modules_file := config.getoption(MODULE_LIST_ARG)):
            with modules_file.open('r') as f:
                self._modules = {Path(line.strip()).resolve() for line in f}
        else:
            self._modules = None

        if (tests_file := config.getoption(TEST_LIST_ARG)):
            with tests_file.open('r') as f:
                self._tests = set(line.strip() for line in f)
        else:
            self._tests = None

        self._results_file = config.getoption(RESULTS_ARG)
        self._collect = []
        self._run = []


    @pytest.hookimpl
    def pytest_ignore_collect(self, collection_path: Path, config: pytest.Config) -> T.Union[None, bool]:
        if self._modules is not None and collection_path.suffix == '.py':
            return collection_path.resolve() not in self._modules


    @pytest.hookimpl
    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if self._results_file and report.nodeid.endswith('.py'):
            self._collect.append({
                'id': report.nodeid,
                'outcome': report.outcome,
                'result': [n.nodeid for n in report.result]
            })


    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(self, items: T.List[pytest.Item], config: pytest.Config) -> T.Union[None, bool]:
        if self._tests is not None:
            selected = []
            deselected = []

            for item in items:
                if item.nodeid in self._tests:
                    selected.append(item)
                else:
                    deselected.append(item)

            if deselected:
                config.hook.pytest_deselected(items=deselected)
                items[:] = selected


    @pytest.hookimpl
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        # to cut down on the log, we only save non-call run reports for failures
        if self._results_file and (report.outcome != 'passed' or report.when == 'call'):
            self._run.append({
                'id': report.nodeid,
                'outcome': report.outcome,
            })


    def write_results(self) -> None:
        if self._results_file:
            with self._results_file.open("w") as f:
                json.dump({
                    'collect': self._collect,
                    'run': self._run
                }, f)


@pytest.hookimpl
def pytest_addoption(parser: pytest.Parser, pluginmanager: pytest.PytestPluginManager) -> None:
    parser.addoption(MODULE_LIST_ARG, type=Path, help="Only collect modules in the given file")
    parser.addoption(TEST_LIST_ARG, type=Path, help="Only run tests whose node IDs are in the given file")
    parser.addoption(RESULTS_ARG, type=Path, help="Write test collection/run results to the given file")


@pytest.hookimpl
def pytest_configure(config: pytest.Config) -> None:
    if config.getoption(MODULE_LIST_ARG) or config.getoption(TEST_LIST_ARG) or \
       config.getoption(RESULTS_ARG):
        config._cleanslate_reduce_plugin = ReducePlugin(config)
        config.pluginmanager.register(config._cleanslate_reduce_plugin)


@pytest.hookimpl
def pytest_unconfigure(config: pytest.Config) -> None:
    if (plugin := getattr(config, "_cleanslate_reduce_plugin", None)):
        plugin.write_results()


class Results:
    """Facilitates access to test results file generated by ReducePlugin."""

    def __init__(self, results_file: Path):
        with results_file.open("r") as f:
            self._results = json.load(f)

        self._outcomes = None

    def get_outcome(self, nodeid: str) -> str:
        if self._outcomes is None:
            self._outcomes = {r['id']: r['outcome'] for r in self._results['collect'] + self._results['run']}

        return self._outcomes[nodeid]

    def get_modules(self) -> T.List[str]:
        return [r['id'] for r in self._results['collect']]

    def get_tests(self) -> T.List[str]:
        return [r['id'] for r in self._results['run']]

    def get_first_failed(self) -> T.Union[None, str]:
        return next(iter(o['id'] for o in self._results['collect'] + self._results['run'] if o['outcome'] == 'failed'), None)

    def get_module(self, testid: str) -> str:
        return testid.split('::')[0]

    def is_module(self, testid: str) -> bool:
        return '::' not in testid


def _run_pytest(tests_path: Path, extra_args=(), *,
                modules: T.List[Path] = None, tests: T.List[str] = None, trace: bool = False) -> dict:
    import tempfile
    import subprocess

    with tempfile.TemporaryDirectory(dir='.') as tmpdir:
        tmpdir = Path(tmpdir)

        results = tmpdir / "results.json"

        if modules:
            modulelist = tmpdir / "modules.txt"
            modulelist.write_text('\n'.join(modules))

        if tests:
            testlist = tmpdir / "tests.txt"
            testlist.write_text('\n'.join(tests))

        command = [
            sys.executable, '-m', 'pytest', *PYTEST_ARGS, *extra_args,
            RESULTS_ARG, results,
            *((MODULE_LIST_ARG, modulelist) if modules else ()),
            *((TEST_LIST_ARG, testlist) if tests else ()),
            tests_path
        ]

        if trace:
            print(f"Running {command}", flush=True)

        p = subprocess.run(command,
                           check=False, **({} if trace else {'stdout': subprocess.DEVNULL}))
        if p.returncode not in (pytest.ExitCode.OK, pytest.ExitCode.TESTS_FAILED,
                                pytest.ExitCode.INTERRUPTED, pytest.ExitCode.NO_TESTS_COLLECTED):
            p.check_returncode()

        return Results(results)


def _bisect_items(items: T.List[str], failing: str, fails: T.Callable[[T.List[str], str], bool]) -> T.List[str]:
    assert failing not in items

    while len(items) > 1:
        print(f"    {len(items)}")
        middle = len(items) // 2

        if fails(items[:middle]+[failing]):
            items = items[:middle]
            continue

        if fails(items[middle:]+[failing]):
            items = items[middle:]
            continue

        # TODO could do the rest of delta debugging here
        break

    if len(items) == 1 and fails([failing]):
        items = []

    print(f"    {len(items)}")
    return items


def _reduce_tests(tests_path: Path, tests: T.List[str], failing_test: str, *, trace=None) -> T.List[str]:
    def fails(test_set: T.List[str]):
        trial = _run_pytest(tests_path, ('-x',), tests=test_set, trace=trace)
        return trial.get_outcome(failing_test) == 'failed'

    return _bisect_items(tests, failing_test, fails)


def _reduce_modules(tests_path: Path, tests: T.List[str], failing_test: str,
                    modules: T.List[str], failing_module: str, *, trace=None) -> T.List[str]:
    def fails(module_set: T.List[str]):
        trial = _run_pytest(tests_path, ('-x',), tests=tests, modules=module_set, trace=trace)
        return trial.get_outcome(failing_test) == 'failed'

    return _bisect_items(modules, failing_module, fails)


def _parse_args():
    import argparse

    bool_action = argparse.BooleanOptionalAction if sys.version_info[:2] >= (3,9) else "store_true"

    ap = argparse.ArgumentParser()
    ap.add_argument('--trace', default=False, action=bool_action, help='show pytest outputs, etc.')
    ap.add_argument('--save-to', type=Path, help='file where to save results (JSON)')
    ap.add_argument('--version', action='version',
                    version=f"%(prog)s v{__version__} (Python {'.'.join(map(str, sys.version_info[:3]))})")
    ap.add_argument('tests_path', type=Path, help='tests file or directory')

    return ap.parse_args()


def main():
    args = _parse_args()

    print("Running tests...", flush=True)
    results = _run_pytest(args.tests_path, ('-x',), trace=args.trace)

    failed = results.get_first_failed()
    if failed is None:
        print("No tests failed!", flush=True)
        if args.save_to:
            with args.save_to.open("w") as f:
                json.dump({
                    'failed': failed,
                    'error': 'No tests failed',
                }, f)
        return 1

    is_module = results.is_module(failed)

    if is_module:
        if args.trace: print()
        print(f"Module \"{failed}\"'s collection failed; trying it by itself...", flush=True)
        failed_module = failed
        solo = _run_pytest(args.tests_path, ('-x',), modules=[failed_module], trace=args.trace)
    else:
        if args.trace: print()
        print(f"Test \"{failed}\" failed; trying it by itself...", flush=True)
        failed_module = results.get_module(failed)

        solo = _run_pytest(args.tests_path, ('-x',), modules=[failed_module], tests=[failed], trace=args.trace)

    if solo.get_outcome(failed) != 'passed':
        print("That also fails by itself!", flush=True)
        if args.save_to:
            with args.save_to.open("w") as f:
                json.dump({
                    'failed': failed,
                    'error': f'{"Module" if is_module else "Test"} also fails by itself',
                }, f)
        return 1

    tests = results.get_tests()
    if not is_module:
        assert tests[-1] == failed
        tests = tests[:-1]

        if args.trace: print()
        print("Trying to reduce test set...", flush=True)
        tests = _reduce_tests(args.tests_path, tests, failed)

    if args.trace: print()
    print("Trying to reduce module set...", flush=True)

    modules = [m for m in results.get_modules() if m != failed_module]
    modules = _reduce_modules(args.tests_path, tests if is_module else tests + [failed], failed, modules, failed_module)

    if args.trace: print()
    print("Reduced failure set:")
    print(f"    modules: {modules}")
    print(f"    tests: {tests}")
    print(flush=True)

    if args.save_to:
        with args.save_to.open("w") as f:
            json.dump({
                'failed': failed,
                'modules': modules,
                'tests': tests,
            }, f)

    return 0

if __name__ == "__main__":
    sys.exit(main())