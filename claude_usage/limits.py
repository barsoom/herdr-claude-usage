"""Usage payload -> {label: percent used}."""

SESSION_LABEL = "5h"
WEEKLY_LABEL = "1w"
FABLE_LABEL = "Fable"

_KIND_LABELS = {"session": SESSION_LABEL, "weekly_all": WEEKLY_LABEL}
# Pre-`limits[]` payloads. Kept because a token can outlive an API shape.
_LEGACY_FIELDS = {
    "five_hour": SESSION_LABEL,
    "seven_day": WEEKLY_LABEL,
    "seven_day_overage_included": FABLE_LABEL,
}


def _percent(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(round(value))


def _from_rows(rows):
    out = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        percent = _percent(row.get("percent"))
        if percent is None:
            continue
        kind = row.get("kind")
        if kind == "weekly_scoped":
            scope = row.get("scope") or {}
            model = scope.get("model") if isinstance(scope, dict) else None
            name = model.get("display_name") if isinstance(model, dict) else None
            if isinstance(name, str) and name.strip():
                out[name.strip()] = percent
            continue
        label = _KIND_LABELS.get(kind)
        if label:
            out[label] = percent
    return out


def _from_legacy(usage):
    out = {}
    for field, label in _LEGACY_FIELDS.items():
        window = usage.get(field)
        if not isinstance(window, dict):
            continue
        percent = _percent(window.get("utilization"))
        if percent is not None:
            out[label] = percent
    return out


def extract(usage):
    rows = usage.get("limits")
    if isinstance(rows, list):
        return _from_rows(rows)
    return _from_legacy(usage)
