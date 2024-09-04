import pytest
from pathlib import Path


# py.process.ForkedFunc does os.close(1) and os.close(2) just before
# the exit of the child process... but if the function called also
# closes those files, an OSError results.  Here we ignore those...
# Really we need to move away from 'py'...
import os
import errno
class IgnoreOsCloseErrors:
    def __enter__(self):
        self.original_os_close = os.close

        def ignoring_close(fd):
            try:
                self.original_os_close(fd)
            except OSError as e:
                if fd not in (1, 2) or e.errno != errno.EBADF:
                    raise

        os.close = ignoring_close

    def __exit__(self, exc_type, exc_value, traceback):
        os.close = self.original_os_close


class CleanSlateItem(pytest.Item):
    """Item that stands for a Module until it can be collected from its forked subprocess"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def runtest(self):
        raise RuntimeError("This should never execute")

    def collect_and_run(self):
        # adapted from pytest-forked
        import pickle
        import _pytest
        import pytest_forked as ptf # FIXME pytest-forked is unmaintained
        import py                   # FIXME py is maintenance only

        def runforked():
            # Use 'parent' as it would have been in pytest_pycollect_makemodule, so that our
            # nodes aren't included in the chain, as they might confuse other plugins (such as 'mark')
            module = pytest.Module.from_parent(parent=self.parent.parent, path=self.path)

            def collect_items(collector):
                for it in collector.collect():
                    if isinstance(it, pytest.Collector):
                        yield from collect_items(it)
                    else:
                        yield it

            try:
                self.session.items = list(collect_items(module))
            except BaseException:
                excinfo = pytest.ExceptionInfo.from_current()
                return pickle.dumps([pytest.CollectReport(
                            nodeid=self.nodeid,
                            outcome='failed',
                            result=None,
                            longrepr=self._repr_failure_py(excinfo, "short"))
                ])

            pm = self.config.pluginmanager
            caller = pm.subset_hook_caller('pytest_collection_modifyitems', remove_plugins=[self.parent.plugin])
            caller(session=self.session, config=self.config, items=self.session.items)

            reports = list()
            class ReportSaver:
                @pytest.hookimpl
                def pytest_runtest_logreport(self, report):
                    reports.append(report)

            pm.register(ReportSaver())

            try:
                self.ihook.pytest_runtestloop(session=self.session)
            except (pytest.Session.Interrupted, pytest.Session.Failed):
                pass
            except BaseException as e:
                return pickle.dumps(e)

            return pickle.dumps(reports)

        with IgnoreOsCloseErrors():
            ff = py.process.ForkedFunc(runforked)
        result = ff.waitfinish()

        if result.retval is None:
            return [ptf.report_process_crash(self, result)]

        retval = pickle.loads(result.retval)
        if isinstance(retval, BaseException):
            raise retval

        return retval


class CleanSlateCollector(pytest.File, pytest.Collector):
    def __init__(self, *, plugin, **kwargs):
        super().__init__(**kwargs)
        self.plugin = plugin

    def collect(self):
        yield CleanSlateItem.from_parent(parent=self, name=self.name)


def run_item_forked(item):
    import _pytest.runner
    import pytest_forked as ptf # FIXME pytest-forked is unmaintained
    import py                   # FIXME py is maintenance only
    import pickle

    def runforked():
        try:
            return pickle.dumps(_pytest.runner.runtestprotocol(item, log=False))
        except BaseException as e:
            return pickle.dumps(e)

    ff = py.process.ForkedFunc(runforked)
    result = ff.waitfinish()

    if result.retval is None:
        return [ptf.report_process_crash(item, result)]

    retval = pickle.loads(result.retval)

    if isinstance(retval, BaseException):
        raise retval

    return retval


class CleanSlatePlugin:
    """Pytest plugin to isolate test collection, so that if a test's collection pollutes the in-memory
       state, it doesn't affect the execution of other tests."""


    @pytest.hookimpl(tryfirst=True)
    def pytest_pycollect_makemodule(self, module_path: Path, parent):
        return CleanSlateCollector.from_parent(parent, path=module_path, plugin=self)


    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_protocol(self, item: pytest.Item, nextitem: pytest.Item):
        ihook = item.ihook
        ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
        if isinstance(item, CleanSlateItem):
            reports = item.collect_and_run()
        else:
            # note any side effects, such as setting session.shouldstop, are lost...
            reports = run_item_forked(item)

        if (reports and isinstance(reports[0], pytest.CollectReport) and reports[0].outcome == 'failed'
            and not item.config.option.continue_on_collection_errors):
            item.session.shouldstop = 'collection error'

        for rep in reports:
            ihook.pytest_runtest_logreport(report=rep)

        ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
        return True


    @pytest.hookimpl(tryfirst=True, hookwrapper=True)
    def pytest_collection_modifyitems(self, session, config, items):
        # Since we're deferring collection to CleanSlateItem, we won't have
        # functions and other relevant items in 'items', possibly leading to
        # our CleanSlateItems being deselected.
        # There doesn't seem to be a way to prevent other plugins from modifying
        # the list, so we save it, let them run, and restore it.
        initial_items = list(items) # TODO save them using pytest_deselected() instead?
        yield
        items[:] = initial_items


def pytest_addoption(parser: pytest.Parser, pluginmanager: pytest.PytestPluginManager) -> None:
    g = parser.getgroup('cleanslate')
    g.addoption("--cleanslate", action="store_true",
                help="Isolate test module collection and test execution using sys.fork()")


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("--cleanslate"):
        config.pluginmanager.register(CleanSlatePlugin(), "cleanslate_plugin")
