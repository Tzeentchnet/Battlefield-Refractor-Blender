IMPORT_MODE_OFF = 'OFF'
IMPORT_MODE_ON = 'ON'
IMPORT_MODE_HIDDEN = 'HIDDEN'

IMPORT_MODE_ITEMS = (
    (IMPORT_MODE_OFF, "Off", "Do not import this optional data", 0),
    (IMPORT_MODE_ON, "On", "Import this data normally", 1),
    (
        IMPORT_MODE_HIDDEN,
        "Hidden",
        "Import this data into a collection with viewport and render visibility disabled",
        2,
    ),
)

IMPORT_MODES = frozenset((IMPORT_MODE_OFF, IMPORT_MODE_ON, IMPORT_MODE_HIDDEN))


def validate_import_mode(mode, setting_name="import mode"):
    if mode not in IMPORT_MODES:
        expected = ", ".join(sorted(IMPORT_MODES))
        raise ValueError(f"Invalid {setting_name} '{mode}', expected one of: {expected}")
    return mode


def should_import_index(index, mode):
    if index < 0:
        raise ValueError("Import index cannot be negative")
    validate_import_mode(mode)
    return index == 0 or mode != IMPORT_MODE_OFF


def should_hide_index(index, mode):
    if index < 0:
        raise ValueError("Import index cannot be negative")
    validate_import_mode(mode)
    return index > 0 and mode == IMPORT_MODE_HIDDEN
