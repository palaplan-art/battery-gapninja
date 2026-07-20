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

# Sheet layout (verified against the live workbook).
HEADER_ROW = 5          # row holding "No. / User / Divison / ..."
FIRST_DATA_ROW = 6
MACHINE_CODE_COL = "G"  # Machine SN:

# app field -> spreadsheet column letter
#
# "install" is a composite field: the sheet's Installation Day column holds
# either a real date or a status word ("Waiting", "Demo"). It maps to
# Machine.install_date when it parses as a date, otherwise Machine.install_status.
FIELD_COLUMNS = {
    "customer": "B",
    "division": "C",
    "contact_person": "D",
    "contact_phone": "E",
    "system": "F",
    "gauge_block_sn": "K",
    "wifi_model": "L",
    "wifi_sn": "M",
    "barcode_scanner_sn": "N",
    "pc_model": "O",
    "pc_sn_tag": "P",
    "remark": "Q",
    "install": "R",
}

INSTALL_FIELD = "install"
EXCEL_EPOCH = date(1899, 12, 30)


def _col_index(letter: str) -> int:
    """'B' -> 1 (zero-based index into a row array starting at column A)."""
    idx = 0
    for ch in letter:
        idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
    return idx - 1


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


def read_excel_machines() -> tuple[dict[str, dict], dict[str, int]]:
    """Return ({machine_code: {field: value}}, {machine_code: sheet_row})."""
    used = graph.read_used_range()
    values = used.get("values", [])
    address = used.get("address", "")
    # usedRange may not start at row 1; derive the offset from its address.
    try:
        start_row = int(address.split("!")[1].split(":")[0].lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ$"))
    except (IndexError, ValueError):
        start_row = 1

    code_idx = _col_index(MACHINE_CODE_COL)
    machines: dict[str, dict] = {}
    rows: dict[str, int] = {}

    for offset, row in enumerate(values):
        sheet_row = start_row + offset
        if sheet_row < FIRST_DATA_ROW:
            continue
        if code_idx >= len(row):
            continue
        code = _norm(row[code_idx]).upper()
        if not code or code == "-":
            continue  # e.g. battery-stock rows have no machine SN

        record: dict = {}
        for field, letter in FIELD_COLUMNS.items():
            i = _col_index(letter)
            raw = row[i] if i < len(row) else ""
            if field == INSTALL_FIELD:
                d = excel_serial_to_date(raw)
                # Either an ISO date, or the status text as-is ("Waiting"/"Demo").
                record[field] = d.isoformat() if d else _norm(raw)
            else:
                record[field] = _norm(raw)
        machines[code] = record
        rows[code] = sheet_row

    return machines, rows


def _app_values(machine: models.Machine) -> dict:
    out = {}
    for field in FIELD_COLUMNS:
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
    excel, rows = read_excel_machines()
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
        app_vals = _app_values(machine)
        base = _baseline(machine)

        for field in FIELD_COLUMNS:
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
            col = FIELD_COLUMNS[entry["field"]]
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
    excel_after, _ = read_excel_machines()
    for code, machine in db_machines.items():
        if code in excel_after:
            merged = _app_values(machine)
            machine.sync_baseline = json.dumps(merged)
    db.commit()

    return {
        "applied_to_app": applied_to_app,
        "applied_to_excel": applied_to_excel,
        "skipped_conflicts": skipped_conflicts,
        "wrote_excel": write_excel,
    }


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
