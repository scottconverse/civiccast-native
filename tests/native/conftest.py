# SPDX-License-Identifier: Apache-2.0
"""Native-suite fixtures that keep process-global logging state isolated."""

from __future__ import annotations

import logging

import pytest


@pytest.fixture(autouse=True)
def _restore_supervisor_logger_state() -> None:
    """Undo ``configure_logging`` mutations before another native test runs.

    Native service tests deliberately configure the production supervisor logger,
    which owns handlers and disables propagation.  Those are process-global
    logging mutations; retaining them makes later ``caplog`` assertions depend
    on test order.
    """

    loggers = [
        logging.getLogger("civiccast.native.supervisor"),
        # configure_logging also wires the package-root logger (so library
        # records in the supervisor process reach supervisor.log); restore it
        # the same way or caplog assertions elsewhere become order-dependent.
        logging.getLogger("civiccast"),
    ]
    originals = [(lg, list(lg.handlers), lg.level, lg.propagate) for lg in loggers]
    try:
        yield
    finally:
        closed: set[int] = set()
        for lg, original_handlers, original_level, original_propagate in originals:
            for handler in list(lg.handlers):
                lg.removeHandler(handler)
                if handler not in original_handlers and id(handler) not in closed:
                    closed.add(id(handler))
                    handler.close()
            for handler in original_handlers:
                lg.addHandler(handler)
            lg.setLevel(original_level)
            lg.propagate = original_propagate
