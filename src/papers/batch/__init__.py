"""Private resumable archive batch processing."""

from importlib import import_module

__all__ = [
    "CycleStatus",
    "cycle_status",
    "get_cycle_status",
    "run_cycle",
    "run_one_batch",
]


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(name)
    return getattr(import_module(".cycle", __name__), name)
