import pytest


class CleanSlateItem(pytest.Item):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def runtest(self):
        raise RuntimeError("This should never execute")

    def run_forked(self):
        # adapted from pytest-forked
        import marshal
        import _pytest
        import pytest_forked as ptf # FIXME pytest-forked is unmaintained
        import py                   # FIXME py is maintenance only

        ihook = self.ihook
        ihook.pytest_runtest_logstart(nodeid=self.nodeid, location=self.location)

        def runforked():
            module = pytest.Module.from_parent(parent=self.parent, path=self.path)
            reports = list()

            def collect_and_run(collector):
                for it in collector.collect():
                    if isinstance(it, pytest.Collector):
                        collect_and_run(it)
                    else:
                        reports.extend(ptf.forked_run_report(it))

            collect_and_run(module)

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


class CleanSlateModule(pytest.Module):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def collect(self):
        yield CleanSlateItem.from_parent(parent=self, name="(module)")


class CleanSlatePlugin:
    """Pytest plugin to isolate test collection, so that if a test's collection pollutes the in-memory
       state, it doesn't affect the execution of other tests."""

    @pytest.hookimpl(tryfirst=True)
    def pytest_pycollect_makemodule(self, module_path, parent):
        return CleanSlateModule.from_parent(parent, path=module_path)

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtestloop(self, session):
        for item in session.items:
            item.run_forked()
        return True


def pytest_addoption(parser):
    parser.addoption("--cleanslate", action="store_true",
                     help="Isolate test module collection and test execution using sys.fork")


def pytest_configure(config):
    if config.getoption("--cleanslate"):
        config.pluginmanager.register(CleanSlatePlugin(), "cleanslate_plugin")
