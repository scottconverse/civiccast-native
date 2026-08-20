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

    logger = logging.getLogger("civiccast.native.supervisor")
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate
    try:
        yield
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            if handler not in original_handlers:
                handler.close()
        for handler in original_handlers:
            logger.addHandler(handler)
        logger.setLevel(original_level)
        logger.propagate = original_propagate
