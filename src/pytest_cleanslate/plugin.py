import pytest
from pathlib import Path


class CleanSlateItem(pytest.Item):
    """Item that stands for a Module until it can be collected from its forked subprocess"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def runtest(self):
        raise RuntimeError("This should never execute")

    def collect_and_run(self):
        # adapted from pytest-forked
        import marshal
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

            self.session.items = list(collect_items(module))

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

            return marshal.dumps([self.config.hook.pytest_report_to_serializable(config=self.config, report=r) for r in reports])

        ff = py.process.ForkedFunc(runforked)
        result = ff.waitfinish()

        if result.retval is None:
            return [ptf.report_process_crash(self, result)]

        return [self.config.hook.pytest_report_from_serializable(config=self.config, data=r) for r in marshal.loads(result.retval)]


class CleanSlateCollector(pytest.File, pytest.Collector):
    def __init__(self, *, plugin, **kwargs):
        super().__init__(**kwargs)
        self.plugin = plugin

    def collect(self):
        yield CleanSlateItem.from_parent(parent=self, name=self.name)


class CleanSlatePlugin:
    """Pytest plugin to isolate test collection, so that if a test's collection pollutes the in-memory
       state, it doesn't affect the execution of other tests."""


    @pytest.hookimpl(tryfirst=True)
    def pytest_pycollect_makemodule(self, module_path: Path, parent):
        return CleanSlateCollector.from_parent(parent, path=module_path, plugin=self)


    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_protocol(self, item: pytest.Item, nextitem: pytest.Item):
        import pytest_forked as ptf # FIXME pytest-forked is unmaintained

        ihook = item.ihook
        ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
        if isinstance(item, CleanSlateItem):
            reports = item.collect_and_run()
        else:
            # note any side effects, such as setting session.shouldstop, are lost...
            reports = ptf.forked_run_report(item)

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
