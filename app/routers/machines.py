from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db

router = APIRouter(prefix="/api/machines", tags=["machines"])


@router.get("", response_model=list[schemas.MachineOut])
def list_machines(db: Session = Depends(get_db)):
    return crud.list_machines(db)


@router.post("", response_model=schemas.MachineOut, status_code=201)
def create_machine(payload: schemas.MachineCreate, db: Session = Depends(get_db)):
    if crud.get_machine(db, payload.code.strip().upper()):
        raise HTTPException(400, f"Machine {payload.code} already exists")
    return crud.create_machine(db, payload)


@router.patch("/{code}", response_model=schemas.MachineOut)
def update_machine(code: str, payload: schemas.MachineUpdate, db: Session = Depends(get_db)):
    machine = crud.get_machine(db, code.strip().upper())
    if not machine:
        raise HTTPException(404, "Machine not found")
    return crud.update_machine(db, machine, payload)
