"""Local-only pytest plugin: run collected tests in reverse order (order-dependence probe)."""


def pytest_collection_modifyitems(session, config, items):
    items.reverse()
