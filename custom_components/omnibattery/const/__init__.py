"""Constants for the Omnibattery integration.

Backward-compatible facade. Definitions live in:
  - integration_const.py : integration/feature configuration constants
  - registers_common.py  : shared register infra (maps, timing, bit descriptions, calc sensors)
  - registers_v2.py / _v3.py / _va.py / _vd.py : per-model Modbus register & entity definitions

Everything is re-exported here so existing `from .const import X` imports keep working.
"""
from .integration_const import *  # noqa: F401,F403
from .registers_common import *  # noqa: F401,F403
from .registers_v2 import *  # noqa: F401,F403
from .registers_v3 import *  # noqa: F401,F403
from .registers_va import *  # noqa: F401,F403
from .registers_vd import *  # noqa: F401,F403

# Deliberate anti-curtailment export policy.  The legacy numeric setting remains
# the value consumed by the pricing runtime; the mode tells newer consumers
# whether zero means "self-consumption" or "automatic".
CONF_PREDISCHARGE_EXPORT_MODE = "predischarge_export_mode"
PREDISCHARGE_EXPORT_MODE_SELF_CONSUMPTION = "self_consumption"
PREDISCHARGE_EXPORT_MODE_AUTOMATIC = "automatic"
PREDISCHARGE_EXPORT_MODE_CUSTOM = "custom"
PREDISCHARGE_EXPORT_MODES = (
    PREDISCHARGE_EXPORT_MODE_SELF_CONSUMPTION,
    PREDISCHARGE_EXPORT_MODE_AUTOMATIC,
    PREDISCHARGE_EXPORT_MODE_CUSTOM,
)
DEFAULT_PREDISCHARGE_EXPORT_MODE = PREDISCHARGE_EXPORT_MODE_AUTOMATIC


def normalize_predischarge_export_settings(
    mode: str | None,
    max_export_power_w: object = 0,
) -> tuple[str, float]:
    """Normalize the export policy and preserve the legacy numeric contract.

    Entries created before the selector existed have no mode.  Their old
    numeric setting is authoritative: zero means self-consumption and a
    positive value means a custom deliberate-export limit.  Automatic keeps a
    zero numeric value so consumers that only know the legacy field remain
    safe until they also consume the mode.
    """
    try:
        numeric_power = max(0.0, float(max_export_power_w or 0))
    except (TypeError, ValueError):
        numeric_power = 0.0

    if mode not in PREDISCHARGE_EXPORT_MODES:
        mode = (
            PREDISCHARGE_EXPORT_MODE_CUSTOM
            if numeric_power > 0
            else PREDISCHARGE_EXPORT_MODE_SELF_CONSUMPTION
        )

    if mode != PREDISCHARGE_EXPORT_MODE_CUSTOM:
        numeric_power = 0.0

    return mode, numeric_power
