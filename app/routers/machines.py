import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import SessionLocal, get_db
from ..services import excel_sync, graph

logger = logging.getLogger("battery.machines")

router = APIRouter(prefix="/api/machines", tags=["machines"])


def _push_machine_to_excel(code: str, force_fields: list[str] | None = None) -> None:
    """Background task: mirror a machine's fields into the SharePoint workbook.

    Runs after the HTTP response is sent so saving a machine stays instant even
    though the Graph round-trip takes a few seconds. `force_fields` are the
    fields the user just edited — those always land in Excel. Failures only
    log — the Sync page can always reconcile later."""
    db = SessionLocal()
    try:
        machine = crud.get_machine(db, code)
        if machine:
            result = excel_sync.push_machine(db, machine, force_fields=force_fields)
            logger.info("Excel push for %s: %s", code, result)
    except (graph.GraphError, excel_sync.LayoutError) as e:
        logger.warning("Excel push skipped for %s: %s", code, e)
    except Exception:
        logger.exception("Excel push failed for %s", code)
    finally:
        db.close()


# Model fields whose edits map to a sheet column. install_date/install_status
# share the sheet's single "Installation Day" column.
_SYNCED_MODEL_FIELDS = set(excel_sync.FIELD_HEADERS) - {"install"}
_INSTALL_MODEL_FIELDS = {"install_date", "install_status"}


@router.get("", response_model=list[schemas.MachineOut])
def list_machines(db: Session = Depends(get_db)):
    return crud.list_machines(db)


@router.post("", response_model=schemas.MachineOut, status_code=201)
def create_machine(payload: schemas.MachineCreate, db: Session = Depends(get_db)):
    if crud.get_machine(db, payload.code.strip().upper()):
        raise HTTPException(400, f"Machine {payload.code} already exists")
    return crud.create_machine(db, payload)


@router.get("/{code}", response_model=schemas.MachineDetailOut)
def get_machine(code: str, db: Session = Depends(get_db)):
    machine = crud.get_machine(db, code.strip().upper())
    if not machine:
        raise HTTPException(404, "Machine not found")
    out = schemas.MachineDetailOut.model_validate(machine)
    out.batteries = [
        schemas.BatteryOut.model_validate(b) for b in crud.machine_batteries(db, machine)
    ]
    return out


@router.patch("/{code}", response_model=schemas.MachineOut)
def update_machine(
    code: str,
    payload: schemas.MachineUpdate,
    background_tasks: BackgroundTasks,
    push_to_excel: bool = True,
    db: Session = Depends(get_db),
):
    machine = crud.get_machine(db, code.strip().upper())
    if not machine:
        raise HTTPException(404, "Machine not found")

    # Which sheet-backed fields did this save actually change? Those are the
    # user's explicit edits and must reach Excel without further confirmation.
    force_fields: set[str] = set()
    for field, new_value in payload.model_dump(exclude_unset=True).items():
        if getattr(machine, field, None) == new_value:
            continue
        if field in _SYNCED_MODEL_FIELDS:
            force_fields.add(field)
        elif field in _INSTALL_MODEL_FIELDS:
            force_fields.add("install")

    machine = crud.update_machine(db, machine, payload)

    # Mirror the edit into the SharePoint workbook after the response is sent,
    # so the save itself returns immediately.
    if push_to_excel and graph.is_configured():
        background_tasks.add_task(
            _push_machine_to_excel, machine.code, sorted(force_fields)
        )
    return machine


# ---------------- Machine notes / logs ----------------
@router.post("/{code}/logs", response_model=schemas.MachineLogOut, status_code=201)
def add_machine_log(code: str, payload: schemas.LogCreate, db: Session = Depends(get_db)):
    machine = crud.get_machine(db, code.strip().upper())
    if not machine:
        raise HTTPException(404, "Machine not found")
    return crud.add_machine_log(db, machine, payload)


@router.patch("/{code}/logs/{log_id}", response_model=schemas.MachineLogOut)
def update_machine_log(
    code: str, log_id: int, payload: schemas.LogUpdate, db: Session = Depends(get_db)
):
    machine = crud.get_machine(db, code.strip().upper())
    if not machine:
        raise HTTPException(404, "Machine not found")
    log = crud.get_machine_log(db, machine, log_id)
    if not log:
        raise HTTPException(404, "Log entry not found")
    return crud.update_machine_log(db, log, payload)


@router.delete("/{code}/logs/{log_id}", status_code=204)
def delete_machine_log(code: str, log_id: int, db: Session = Depends(get_db)):
    machine = crud.get_machine(db, code.strip().upper())
    if not machine:
        raise HTTPException(404, "Machine not found")
    log = crud.get_machine_log(db, machine, log_id)
    if not log:
        raise HTTPException(404, "Log entry not found")
    crud.delete_machine_log(db, log)
