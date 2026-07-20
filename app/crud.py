import re
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import models, schemas


def _touch(battery: models.Battery) -> None:
    """Mark a battery as just changed (drives the 'Recently updated' sort)."""
    battery.updated_at = datetime.now()

SERIAL_PREFIX = "GNB-"
SERIAL_DIGITS = 4


def normalize_query(q: str) -> str:
    """Turn '1', '0001', 'gnb-0001' etc into the padded suffix digits."""
    digits = re.sub(r"\D", "", q)
    return digits


def next_serial(db: Session) -> str:
    last = (
        db.query(models.Battery)
        .filter(models.Battery.serial.like(f"{SERIAL_PREFIX}%"))
        .order_by(models.Battery.serial.desc())
        .first()
    )
    if not last:
        n = 1
    else:
        try:
            n = int(last.serial.replace(SERIAL_PREFIX, "")) + 1
        except ValueError:
            n = 1
    return f"{SERIAL_PREFIX}{str(n).zfill(SERIAL_DIGITS)}"


def search_batteries(
    db: Session,
    q: str | None = None,
    machine_code: str | None = None,
    end_user: str | None = None,
    status: models.BatteryStatus | None = None,
    sort: str | None = None,
) -> list[models.Battery]:
    query = db.query(models.Battery)

    if q:
        digits = normalize_query(q)
        exact_serial = None
        if digits:
            exact_serial = f"{SERIAL_PREFIX}{digits.zfill(SERIAL_DIGITS)}"
        exact_match = None
        if exact_serial:
            exact_match = (
                db.query(models.Battery)
                .filter(models.Battery.serial == exact_serial)
                .first()
            )
        if exact_match:
            return [exact_match]

        like = f"%{q.strip()}%"
        conditions = [
            models.Battery.serial.ilike(like),
            models.Battery.machine_code.ilike(like),
            models.Battery.end_user.ilike(like),
        ]
        if digits:
            conditions.append(models.Battery.serial.ilike(f"%{digits}%"))
        query = query.filter(or_(*conditions))

    if machine_code:
        query = query.filter(models.Battery.machine_code == machine_code)
    if end_user:
        query = query.filter(models.Battery.end_user == end_user)
    if status:
        query = query.filter(models.Battery.status == status)

    results = query.order_by(models.Battery.serial.asc()).all()

    if sort == "recent":
        # Most recently changed first; never-changed rows fall to the bottom.
        results.sort(
            key=lambda b: (b.updated_at is None, -(b.updated_at or b.created_at).timestamp()
                           if (b.updated_at or b.created_at) else 0)
        )
    return results


def get_battery_by_serial(db: Session, serial: str) -> models.Battery | None:
    return db.query(models.Battery).filter(models.Battery.serial == serial).first()


def _add_log(
    db: Session,
    battery: models.Battery,
    action_type: models.ActionType,
    description: str,
    field: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
) -> models.BatteryLog:
    log = models.BatteryLog(
        battery_id=battery.id,
        action_type=action_type,
        field=field,
        old_value=old_value,
        new_value=new_value,
        description=description,
    )
    db.add(log)
    return log


def create_battery(db: Session, payload: schemas.BatteryCreate) -> models.Battery:
    serial = payload.serial.strip().upper() if payload.serial else next_serial(db)

    battery = models.Battery(
        serial=serial,
        machine_code=payload.machine_code,
        end_user=payload.end_user,
        commission_date=payload.commission_date,
        last_capacity_mah=payload.last_capacity_mah,
        notes=payload.notes,
    )
    db.add(battery)
    db.flush()

    parts = [f"Battery {serial} created"]
    if payload.machine_code:
        parts.append(f"assigned to machine {payload.machine_code}")
    if payload.end_user:
        parts.append(f"for end-user {payload.end_user}")
    if payload.last_capacity_mah:
        parts.append(f"capacity {payload.last_capacity_mah} mAh")

    _add_log(
        db,
        battery,
        models.ActionType.created,
        description=", ".join(parts) + ".",
    )
    db.commit()
    db.refresh(battery)
    return battery


FIELD_LABELS = {
    "machine_code": ("Machine", models.ActionType.machine_change),
    "end_user": ("End-user", models.ActionType.end_user_change),
    "status": ("Status", models.ActionType.status_change),
    "commission_date": ("Commission date", models.ActionType.note),
    "notes": ("Notes", models.ActionType.note),
}


def update_battery(
    db: Session, battery: models.Battery, payload: schemas.BatteryUpdate
) -> models.Battery:
    data = payload.model_dump(exclude_unset=True)

    cell_replacement_date = data.pop("last_cell_replacement_date", None)
    capacity_mah = data.pop("last_capacity_mah", None)

    for field, new_value in data.items():
        old_value = getattr(battery, field)
        old_value = old_value.value if hasattr(old_value, "value") else old_value
        cmp_new = new_value.value if hasattr(new_value, "value") else new_value
        if cmp_new == old_value:
            continue

        label, action_type = FIELD_LABELS.get(field, (field, models.ActionType.note))
        old_display = old_value if old_value not in (None, "") else "(none)"
        new_display = cmp_new if cmp_new not in (None, "") else "(none)"

        setattr(battery, field, new_value)
        _add_log(
            db,
            battery,
            action_type,
            field=field,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(cmp_new) if cmp_new is not None else None,
            description=f"{label} changed from {old_display} to {new_display}.",
        )

    if cell_replacement_date is not None:
        old_value = battery.last_cell_replacement_date
        if old_value != cell_replacement_date:
            battery.last_cell_replacement_date = cell_replacement_date
            old_display = old_value.isoformat() if old_value else "(none)"
            _add_log(
                db,
                battery,
                models.ActionType.cell_replacement,
                field="last_cell_replacement_date",
                old_value=old_value.isoformat() if old_value else None,
                new_value=cell_replacement_date.isoformat(),
                description=(
                    f"Cell replacement logged: {old_display} -> "
                    f"{cell_replacement_date.isoformat()}."
                ),
            )

    if capacity_mah is not None:
        old_value = battery.last_capacity_mah
        if old_value != capacity_mah:
            battery.last_capacity_mah = capacity_mah
            health = round(min(100.0, capacity_mah / schemas.HEALTH_MAX_MAH * 100), 1)
            old_display = f"{old_value} mAh" if old_value is not None else "(none)"
            _add_log(
                db,
                battery,
                models.ActionType.capacity_check,
                field="last_capacity_mah",
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(capacity_mah),
                description=(
                    f"Capacity recorded: {old_display} -> {capacity_mah} mAh "
                    f"({health}% health)."
                ),
            )

    _touch(battery)
    db.commit()
    db.refresh(battery)
    return battery


def add_manual_log(
    db: Session, battery: models.Battery, payload: schemas.LogCreate
) -> models.BatteryLog:
    log = _add_log(
        db,
        battery,
        models.ActionType.note,
        description=payload.description,
    )
    _touch(battery)
    db.commit()
    db.refresh(log)
    return log


def get_log(db: Session, battery: models.Battery, log_id: int) -> models.BatteryLog | None:
    return (
        db.query(models.BatteryLog)
        .filter(models.BatteryLog.id == log_id, models.BatteryLog.battery_id == battery.id)
        .first()
    )


def update_log(
    db: Session, log: models.BatteryLog, payload: schemas.LogUpdate
) -> models.BatteryLog:
    log.description = payload.description
    if log.battery:
        _touch(log.battery)
    db.commit()
    db.refresh(log)
    return log


def delete_log(db: Session, log: models.BatteryLog) -> None:
    if log.battery:
        _touch(log.battery)
    db.delete(log)
    db.commit()


# ---------------- Battery test records ----------------
def add_test(
    db: Session, battery: models.Battery, payload: schemas.BatteryTestCreate
) -> models.BatteryTest:
    test = models.BatteryTest(battery_id=battery.id, **payload.model_dump())
    db.add(test)
    # Keep the battery's headline capacity/health in sync with the latest reading.
    if payload.capacity_after_charge_mah:
        battery.last_capacity_mah = payload.capacity_after_charge_mah
    _touch(battery)
    db.commit()
    db.refresh(test)
    return test


def get_test(db: Session, battery: models.Battery, test_id: int) -> models.BatteryTest | None:
    return (
        db.query(models.BatteryTest)
        .filter(
            models.BatteryTest.id == test_id,
            models.BatteryTest.battery_id == battery.id,
        )
        .first()
    )


def update_test(
    db: Session, test: models.BatteryTest, payload: schemas.BatteryTestUpdate
) -> models.BatteryTest:
    for field, value in payload.model_dump().items():
        setattr(test, field, value)
    if payload.capacity_after_charge_mah:
        test.battery.last_capacity_mah = payload.capacity_after_charge_mah
    if test.battery:
        _touch(test.battery)
    db.commit()
    db.refresh(test)
    return test


def delete_test(db: Session, test: models.BatteryTest) -> None:
    if test.battery:
        _touch(test.battery)
    db.delete(test)
    db.commit()


def list_machines(db: Session) -> list[models.Machine]:
    return db.query(models.Machine).order_by(models.Machine.code.asc()).all()


def get_machine(db: Session, code: str) -> models.Machine | None:
    return db.query(models.Machine).filter(models.Machine.code == code).first()


def create_machine(db: Session, payload: schemas.MachineCreate) -> models.Machine:
    data = payload.model_dump()
    data["code"] = data["code"].strip().upper()
    machine = models.Machine(**data)
    db.add(machine)
    db.commit()
    db.refresh(machine)
    return machine


def update_machine(
    db: Session, machine: models.Machine, payload: schemas.MachineUpdate
) -> models.Machine:
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(machine, field, value)
    db.commit()
    db.refresh(machine)
    return machine


def machine_batteries(db: Session, machine: models.Machine) -> list[models.Battery]:
    return (
        db.query(models.Battery)
        .filter(models.Battery.machine_code == machine.code)
        .order_by(models.Battery.serial.asc())
        .all()
    )


def add_machine_log(
    db: Session, machine: models.Machine, payload: schemas.LogCreate
) -> models.MachineLog:
    log = models.MachineLog(machine_id=machine.id, description=payload.description)
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def get_machine_log(
    db: Session, machine: models.Machine, log_id: int
) -> models.MachineLog | None:
    return (
        db.query(models.MachineLog)
        .filter(
            models.MachineLog.id == log_id,
            models.MachineLog.machine_id == machine.id,
        )
        .first()
    )


def update_machine_log(
    db: Session, log: models.MachineLog, payload: schemas.LogUpdate
) -> models.MachineLog:
    log.description = payload.description
    db.commit()
    db.refresh(log)
    return log


def delete_machine_log(db: Session, log: models.MachineLog) -> None:
    db.delete(log)
    db.commit()


PRIORITY_END_USER = "TBTS"


def list_end_users(db: Session) -> list[str]:
    """Distinct non-empty end-users, with TBTS-first then alphabetical."""
    rows = (
        db.query(models.Battery.end_user)
        .filter(models.Battery.end_user.isnot(None), models.Battery.end_user != "")
        .distinct()
        .all()
    )
    values = sorted({r[0].strip() for r in rows if r[0] and r[0].strip()})
    priority = [v for v in values if v.upper().startswith(PRIORITY_END_USER)]
    others = [v for v in values if not v.upper().startswith(PRIORITY_END_USER)]
    return priority + others


def dashboard_summary(db: Session) -> dict:
    batteries = db.query(models.Battery).all()
    total = len(batteries)
    active = sum(1 for b in batteries if b.status == models.BatteryStatus.active)
    maintenance = sum(1 for b in batteries if b.status == models.BatteryStatus.maintenance)
    retired = sum(1 for b in batteries if b.status == models.BatteryStatus.retired)

    return {
        "total": total,
        "active": active,
        "maintenance": maintenance,
        "retired": retired,
        "end_users": list_end_users(db),
    }
