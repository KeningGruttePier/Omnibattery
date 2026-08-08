"""Product-contract tests for the shared top-cell voltage policy."""

from custom_components.omnibattery.const import (
    NORMAL_BALANCE_PAUSE_CELL_VOLTAGE,
)


def test_normal_balance_pause_stays_at_3_60_v() -> None:
    """The integrated normal taper keeps its established upper stop point."""
    assert NORMAL_BALANCE_PAUSE_CELL_VOLTAGE == 3.60
