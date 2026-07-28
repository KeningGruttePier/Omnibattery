"""Product-contract tests for the shared top-cell voltage policy."""

from custom_components.omnibattery.const import (
    ACTIVE_BALANCE_CHARGE_STOP_CELL_VOLTAGE,
    NORMAL_BALANCE_PAUSE_CELL_VOLTAGE,
)


def test_normal_and_active_balance_stop_at_3_60_v() -> None:
    """Normal taper and Active Cell Balance use the same upper stop point."""
    assert NORMAL_BALANCE_PAUSE_CELL_VOLTAGE == 3.60
    assert ACTIVE_BALANCE_CHARGE_STOP_CELL_VOLTAGE == 3.60
