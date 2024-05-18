import pytest


class CleanSlateItem(pytest.Item):
    """Item that stands for a Module until it can be collected from its forked subprocess"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def runtest(self):
        raise RuntimeError("This should never execute")

    def run_forked(self, cleanslate_plugin):
        # adapted from pytest-forked
        import marshal
        import _pytest
        import pytest_forked as ptf # FIXME pytest-forked is unmaintained
        import py                   # FIXME py is maintenance only

        ihook = self.ihook
        ihook.pytest_runtest_logstart(nodeid=self.nodeid, location=self.location)

        def runforked():
            # Use 'parent' as it would have been in pytest_pycollect_makemodule, so that our
            # nodes aren't included in the chain, as they might confuse other plugins (such as 'mark')
            module = pytest.Module.from_parent(parent=self.parent.parent, path=self.path)
            reports = list()

            def collect_items(collector):
                for it in collector.collect():
                    if isinstance(it, pytest.Collector):
                        yield from collect_items(it)
                    else:
                        yield it

            items = list(collect_items(module))

            caller = self.config.pluginmanager.subset_hook_caller('pytest_collection_modifyitems',
                                                                  remove_plugins=[cleanslate_plugin])
            caller(session=self.session, config=self.config, items=items)

            for it in items:
                reports.extend(ptf.forked_run_report(it))

            return marshal.dumps([self.config.hook.pytest_report_to_serializable(config=self.config, report=r) for r in reports])

        ff = py.process.ForkedFunc(runforked)
        result = ff.waitfinish()

        if result.retval is not None:
            reports = [self.config.hook.pytest_report_from_serializable(config=self.config, data=r) for r in marshal.loads(result.retval)]
        else:
            reports = [ptf.report_process_crash(self, result)]

        for r in reports:
            ihook.pytest_runtest_logreport(report=r)

        ihook.pytest_runtest_logfinish(nodeid=self.nodeid, location=self.location)


class CleanSlateCollector(pytest.File, pytest.Collector):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def collect(self):
        yield CleanSlateItem.from_parent(parent=self, name=self.name)


class CleanSlatePlugin:
    """Pytest plugin to isolate test collection, so that if a test's collection pollutes the in-memory
       state, it doesn't affect the execution of other tests."""


    @pytest.hookimpl(tryfirst=True)
    def pytest_pycollect_makemodule(self, module_path: pytest.Path, parent):
        return CleanSlateCollector.from_parent(parent, path=module_path)


    @pytest.hookimpl(tryfirst=True)
    def pytest_runtestloop(self, session: pytest.Session):
        for item in session.items:
            item.run_forked(self)
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
