from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/batteries", tags=["batteries"])


@router.get("", response_model=list[schemas.BatteryOut])
def list_batteries(
    q: str | None = None,
    machine_code: str | None = None,
    end_user: str | None = None,
    status: models.BatteryStatus | None = None,
    sort: str | None = None,
    db: Session = Depends(get_db),
):
    return crud.search_batteries(
        db, q=q, machine_code=machine_code, end_user=end_user, status=status, sort=sort
    )


@router.post("", response_model=schemas.BatteryOut, status_code=201)
def create_battery(payload: schemas.BatteryCreate, db: Session = Depends(get_db)):
    if payload.serial:
        existing = crud.get_battery_by_serial(db, payload.serial.strip().upper())
        if existing:
            raise HTTPException(400, f"Battery {payload.serial} already exists")
    if payload.machine_code and not crud.get_machine(db, payload.machine_code):
        raise HTTPException(400, f"Machine {payload.machine_code} does not exist")
    return crud.create_battery(db, payload)


@router.get("/{serial}", response_model=schemas.BatteryDetailOut)
def get_battery(serial: str, db: Session = Depends(get_db)):
    battery = crud.get_battery_by_serial(db, serial.strip().upper())
    if not battery:
        raise HTTPException(404, "Battery not found")
    return battery


@router.patch("/{serial}", response_model=schemas.BatteryDetailOut)
def update_battery(
    serial: str, payload: schemas.BatteryUpdate, db: Session = Depends(get_db)
):
    battery = crud.get_battery_by_serial(db, serial.strip().upper())
    if not battery:
        raise HTTPException(404, "Battery not found")
    if payload.machine_code and not crud.get_machine(db, payload.machine_code):
        raise HTTPException(400, f"Machine {payload.machine_code} does not exist")
    return crud.update_battery(db, battery, payload)


@router.get("/{serial}/logs", response_model=list[schemas.BatteryLogOut])
def get_logs(serial: str, db: Session = Depends(get_db)):
    battery = crud.get_battery_by_serial(db, serial.strip().upper())
    if not battery:
        raise HTTPException(404, "Battery not found")
    return battery.logs


@router.post("/{serial}/logs", response_model=schemas.BatteryLogOut, status_code=201)
def add_log(serial: str, payload: schemas.LogCreate, db: Session = Depends(get_db)):
    battery = crud.get_battery_by_serial(db, serial.strip().upper())
    if not battery:
        raise HTTPException(404, "Battery not found")
    return crud.add_manual_log(db, battery, payload)


@router.patch("/{serial}/logs/{log_id}", response_model=schemas.BatteryLogOut)
def update_log(
    serial: str, log_id: int, payload: schemas.LogUpdate, db: Session = Depends(get_db)
):
    battery = crud.get_battery_by_serial(db, serial.strip().upper())
    if not battery:
        raise HTTPException(404, "Battery not found")
    log = crud.get_log(db, battery, log_id)
    if not log:
        raise HTTPException(404, "Log entry not found")
    return crud.update_log(db, log, payload)


@router.delete("/{serial}/logs/{log_id}", status_code=204)
def delete_log(serial: str, log_id: int, db: Session = Depends(get_db)):
    battery = crud.get_battery_by_serial(db, serial.strip().upper())
    if not battery:
        raise HTTPException(404, "Battery not found")
    log = crud.get_log(db, battery, log_id)
    if not log:
        raise HTTPException(404, "Log entry not found")
    crud.delete_log(db, log)


# ---------------- Test records ----------------
@router.get("/{serial}/tests", response_model=list[schemas.BatteryTestOut])
def get_tests(serial: str, db: Session = Depends(get_db)):
    battery = crud.get_battery_by_serial(db, serial.strip().upper())
    if not battery:
        raise HTTPException(404, "Battery not found")
    return battery.tests


@router.post("/{serial}/tests", response_model=schemas.BatteryTestOut, status_code=201)
def add_test(
    serial: str, payload: schemas.BatteryTestCreate, db: Session = Depends(get_db)
):
    battery = crud.get_battery_by_serial(db, serial.strip().upper())
    if not battery:
        raise HTTPException(404, "Battery not found")
    return crud.add_test(db, battery, payload)


@router.patch("/{serial}/tests/{test_id}", response_model=schemas.BatteryTestOut)
def update_test(
    serial: str,
    test_id: int,
    payload: schemas.BatteryTestUpdate,
    db: Session = Depends(get_db),
):
    battery = crud.get_battery_by_serial(db, serial.strip().upper())
    if not battery:
        raise HTTPException(404, "Battery not found")
    test = crud.get_test(db, battery, test_id)
    if not test:
        raise HTTPException(404, "Test record not found")
    return crud.update_test(db, test, payload)


@router.delete("/{serial}/tests/{test_id}", status_code=204)
def delete_test(serial: str, test_id: int, db: Session = Depends(get_db)):
    battery = crud.get_battery_by_serial(db, serial.strip().upper())
    if not battery:
        raise HTTPException(404, "Battery not found")
    test = crud.get_test(db, battery, test_id)
    if not test:
        raise HTTPException(404, "Test record not found")
    crud.delete_test(db, test)
