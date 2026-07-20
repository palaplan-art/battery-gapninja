"""Two-way sync between the app's Machine records and the SharePoint workbook
sheet "Gap Ninja Controll list".

Conflict handling uses a three-way merge against a per-machine baseline stored
when the last sync ran:

    changed in Excel only -> take Excel
    changed in app only   -> take app (written back to Excel)
    changed on both sides -> reported as a conflict, never auto-overwritten
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .. import models
from . import graph

# Column positions are resolved from the sheet's own header row rather than
# hardcoded, so inserting/moving a column in the workbook cannot silently make
# the sync read or write the wrong cells.
MACHINE_CODE_HEADER = "Machine SN:"

# app field -> exact header label in the sheet
FIELD_HEADERS = {
    "customer": "User",
    "division": "Divison",          # (sheet's own spelling)
    "contact_person": "Contract Person",
    "contact_phone": "Customer Tel.",
    "system": "System",
    "gauge_block_sn": "S/N",        # under "Gauge Block Info."
    "wifi_model": "Model",          # under "Meash Wi-Fi Info."
    "wifi_ip": "IP",
    "wifi_sn": "S/N:",
    "barcode_scanner_sn": "S/N.",   # under "Barcode Scanner"
    "pc_model": "Model.",           # under "PC Info."
    "pc_sn_tag": "S/N Tag",
    "remark": "Remark",
    "install": "Installation Day",
}

# Fields the sheet must expose for a sync to be considered safe.
REQUIRED_FIELDS = {"customer", "division", "remark", "install"}

# Optional fields — absent columns are simply skipped.
OPTIONAL_FIELDS = {"wifi_ip"}

INSTALL_FIELD = "install"
EXCEL_EPOCH = date(1899, 12, 30)


class LayoutError(RuntimeError):
    """Raised when the sheet's header row cannot be understood."""


def _col_letter(index: int) -> str:
    """0 -> 'A', 25 -> 'Z', 26 -> 'AA' (index is relative to column A)."""
    letters = ""
    n = index + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def resolve_layout(values: list, start_row: int) -> dict:
    """Locate the header row and map each app field to its column index.

    Returns {"header_row", "first_data_row", "code_index", "columns": {field: idx}}.
    """
    header_offset = None
    for offset, row in enumerate(values):
        if any(_norm(c) == MACHINE_CODE_HEADER for c in row):
            header_offset = offset
            break
    if header_offset is None:
        raise LayoutError(
            f"Could not find the header row (no '{MACHINE_CODE_HEADER}' cell). "
            "The sheet layout may have changed — sync aborted for safety."
        )

    header = [_norm(c) for c in values[header_offset]]
    label_to_index = {}
    for i, label in enumerate(header):
        if label and label not in label_to_index:
            label_to_index[label] = i

    columns = {}
    missing = []
    for field, label in FIELD_HEADERS.items():
        if label in label_to_index:
            columns[field] = label_to_index[label]
        elif field not in OPTIONAL_FIELDS:
            missing.append(f"{field} ('{label}')")

    required_missing = [m for m in missing if m.split(" ")[0] in REQUIRED_FIELDS]
    if required_missing:
        raise LayoutError(
            "These expected columns were not found in the sheet: "
            + ", ".join(required_missing)
            + ". Sync aborted so nothing is written to the wrong column."
        )

    return {
        "header_row": start_row + header_offset,
        "first_data_row": start_row + header_offset + 1,
        "code_index": label_to_index[MACHINE_CODE_HEADER],
        "columns": columns,
    }


def excel_serial_to_date(value) -> date | None:
    try:
        return EXCEL_EPOCH + timedelta(days=int(float(value)))
    except (TypeError, ValueError):
        return None


def date_to_excel_serial(d: date) -> int:
    return (d - EXCEL_EPOCH).days


def _norm(value) -> str:
    """Normalise a value for comparison: trimmed string, '' for empty."""
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value).strip()


def read_excel_machines() -> tuple[dict[str, dict], dict[str, int], dict]:
    """Return ({code: {field: value}}, {code: sheet_row}, layout)."""
    used = graph.read_used_range()
    values = used.get("values", [])
    address = used.get("address", "")
    # usedRange may not start at row 1; derive the offset from its address.
    try:
        start_row = int(
            address.split("!")[1].split(":")[0].lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ$")
        )
    except (IndexError, ValueError):
        start_row = 1

    layout = resolve_layout(values, start_row)
    code_idx = layout["code_index"]
    columns = layout["columns"]

    machines: dict[str, dict] = {}
    rows: dict[str, int] = {}

    for offset, row in enumerate(values):
        sheet_row = start_row + offset
        if sheet_row < layout["first_data_row"]:
            continue
        if code_idx >= len(row):
            continue
        code = _norm(row[code_idx]).upper()
        if not code or code == "-":
            continue  # e.g. battery-stock rows have no machine SN

        record: dict = {}
        for field, i in columns.items():
            raw = row[i] if i < len(row) else ""
            if field == INSTALL_FIELD:
                d = excel_serial_to_date(raw)
                # Either an ISO date, or the status text as-is ("Waiting"/"Demo").
                record[field] = d.isoformat() if d else _norm(raw)
            else:
                record[field] = _norm(raw)
        machines[code] = record
        rows[code] = sheet_row

    return machines, rows, layout


def _app_values(machine: models.Machine, fields=None) -> dict:
    out = {}
    for field in (fields or FIELD_HEADERS):
        if field == INSTALL_FIELD:
            # A real date wins; otherwise fall back to the status word.
            if machine.install_date:
                out[field] = machine.install_date.isoformat()
            else:
                out[field] = _norm(machine.install_status)
        else:
            out[field] = _norm(getattr(machine, field, None))
    return out


def _baseline(machine: models.Machine) -> dict:
    raw = getattr(machine, "sync_baseline", None)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def build_diff(db: Session) -> dict:
    """Compare Excel vs app against the stored baseline. Read-only."""
    excel, rows, layout = read_excel_machines()
    fields = list(layout["columns"].keys())
    db_machines = {m.code.upper(): m for m in db.query(models.Machine).all()}

    to_app: list[dict] = []       # apply Excel -> app
    to_excel: list[dict] = []     # apply app -> Excel
    conflicts: list[dict] = []    # both sides changed
    only_in_excel: list[str] = []
    only_in_app: list[str] = []

    for code, ex in excel.items():
        machine = db_machines.get(code)
        if machine is None:
            only_in_excel.append(code)
            continue
        app_vals = _app_values(machine, fields)
        base = _baseline(machine)

        for field in fields:
            ex_val = ex.get(field, "")
            app_val = app_vals.get(field, "")
            base_val = base.get(field, None)

            if ex_val == app_val:
                continue

            excel_changed = base_val is None or ex_val != base_val
            app_changed = base_val is None or app_val != base_val

            entry = {
                "code": code,
                "field": field,
                "excel": ex_val,
                "app": app_val,
                "baseline": base_val,
                "row": rows.get(code),
            }
            if excel_changed and app_changed:
                conflicts.append(entry)
            elif excel_changed:
                to_app.append(entry)
            elif app_changed:
                to_excel.append(entry)

    for code in db_machines:
        if code not in excel:
            only_in_app.append(code)

    return {
        "to_app": to_app,
        "to_excel": to_excel,
        "conflicts": conflicts,
        "only_in_excel": sorted(only_in_excel),
        "only_in_app": sorted(only_in_app),
        "excel_machine_count": len(excel),
        "app_machine_count": len(db_machines),
    }


def _set_app_field(machine: models.Machine, field: str, value: str) -> None:
    if field == INSTALL_FIELD:
        try:
            machine.install_date = date.fromisoformat(value) if value else None
            machine.install_status = None
        except ValueError:
            machine.install_date = None
            machine.install_status = value or None
    else:
        setattr(machine, field, value or None)


def apply_sync(
    db: Session,
    write_excel: bool,
    conflict_resolution: dict | None = None,
) -> dict:
    """Apply the diff. Excel->app is always safe; app->Excel only when
    write_excel is True. conflict_resolution maps "CODE.field" -> "app"|"excel".
    """
    conflict_resolution = conflict_resolution or {}
    diff = build_diff(db)
    _, _, layout = read_excel_machines()
    columns = layout["columns"]
    db_machines = {m.code.upper(): m for m in db.query(models.Machine).all()}

    applied_to_app = 0
    applied_to_excel = 0
    skipped_conflicts = 0

    # 1) Excel -> app
    for entry in diff["to_app"]:
        machine = db_machines.get(entry["code"])
        if machine:
            _set_app_field(machine, entry["field"], entry["excel"])
            applied_to_app += 1

    # 2) Conflicts, only where the user picked a side
    pending_excel_writes: list[dict] = []
    for entry in diff["conflicts"]:
        key = f"{entry['code']}.{entry['field']}"
        choice = conflict_resolution.get(key)
        machine = db_machines.get(entry["code"])
        if choice == "excel" and machine:
            _set_app_field(machine, entry["field"], entry["excel"])
            applied_to_app += 1
        elif choice == "app":
            pending_excel_writes.append(entry)
        else:
            skipped_conflicts += 1

    # 3) app -> Excel
    if write_excel:
        for entry in list(diff["to_excel"]) + pending_excel_writes:
            row = entry.get("row")
            if not row:
                continue
            if entry["field"] not in columns:
                continue
            col = _col_letter(columns[entry["field"]])
            value = entry["app"]
            if entry["field"] == INSTALL_FIELD and value:
                # Write a real date back as an Excel serial; leave status text alone.
                try:
                    value = date_to_excel_serial(date.fromisoformat(value))
                except ValueError:
                    pass
            graph.write_cell(f"{col}{row}", value if value != "" else "")
            applied_to_excel += 1

    db.commit()

    # 4) Refresh the baseline so the next run can tell which side changed.
    excel_after, _, layout_after = read_excel_machines()
    after_fields = list(layout_after["columns"].keys())
    for code, machine in db_machines.items():
        if code in excel_after:
            machine.sync_baseline = json.dumps(_app_values(machine, after_fields))
    db.commit()

    return {
        "applied_to_app": applied_to_app,
        "applied_to_excel": applied_to_excel,
        "skipped_conflicts": skipped_conflicts,
        "wrote_excel": write_excel,
    }


def push_machine(
    db: Session, machine: models.Machine, force_fields: list[str] | None = None
) -> dict:
    """Write one machine's app-side values straight back into the sheet.

    Fields in `force_fields` are the ones the user just edited in the app, so
    their values are written unconditionally — pressing Save must land in Excel
    without a second confirmation. Every other differing field is only written
    when the sheet still matches the stored baseline; otherwise it is left as a
    conflict for the Sync page to resolve.
    """
    excel, rows, layout = read_excel_machines()
    columns = layout["columns"]
    fields = list(columns.keys())
    code = machine.code.upper()
    if code not in excel:
        return {"written": 0, "conflicts": [], "reason": "machine not in sheet"}

    row = rows[code]
    ex = excel[code]
    app_vals = _app_values(machine, fields)
    base = _baseline(machine)
    never_synced = not base

    force = set(force_fields or [])
    written, conflicts = 0, []
    for field in fields:
        app_val = app_vals.get(field, "")
        ex_val = ex.get(field, "")
        base_val = base.get(field, None)
        if app_val == ex_val:
            continue
        if field not in force:
            # Untouched fields only sync when it is provably safe.
            if never_synced and ex_val != "":
                # No baseline yet: we cannot tell which side is newer, so never
                # overwrite a non-empty Excel cell — surface it on the Sync page.
                conflicts.append(field)
                continue
            if base_val is not None and ex_val != base_val:
                conflicts.append(field)  # Excel changed too — leave for manual review
                continue
        value = app_val
        if field == INSTALL_FIELD and value:
            try:
                value = date_to_excel_serial(date.fromisoformat(value))
            except ValueError:
                pass
        graph.write_cell(f"{_col_letter(columns[field])}{row}", value if value != "" else "")
        written += 1

    if written:
        machine.sync_baseline = json.dumps(_app_values(machine, fields))
        db.commit()
    return {"written": written, "conflicts": conflicts}


def backup_workbook() -> dict:
    """Download the workbook and upload a timestamped copy beside it."""
    content = graph.download_bytes()
    info = graph.file_info()
    name = info.get("name") or "workbook.xlsm"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if name.lower().endswith(".xlsm"):
        backup_name = f"{name[:-5]}_backup_{stamp}.xlsm"
    else:
        backup_name = f"{name}_backup_{stamp}"
    result = graph.upload_backup(content, backup_name)
    return {"backup_name": result.get("name"), "size": len(content)}
