from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import excel_sync, graph

router = APIRouter(prefix="/api/sync", tags=["sync"])


class ApplyRequest(BaseModel):
    write_excel: bool = False
    conflict_resolution: dict[str, str] = {}
    backup_first: bool = True


@router.get("/status")
def sync_status():
    if not graph.is_configured():
        return {"configured": False, "detail": "Microsoft Graph is not configured."}
    try:
        return {"configured": True, "file": graph.file_info()}
    except graph.GraphError as e:
        raise HTTPException(502, str(e))


@router.get("/preview")
def sync_preview(db: Session = Depends(get_db)):
    """Read-only comparison of the workbook against the app. Writes nothing."""
    if not graph.is_configured():
        raise HTTPException(400, "Microsoft Graph is not configured.")
    try:
        return excel_sync.build_diff(db)
    except graph.GraphError as e:
        raise HTTPException(502, str(e))


@router.post("/apply")
def sync_apply(payload: ApplyRequest, db: Session = Depends(get_db)):
    """Apply the sync. Excel -> app is always safe; app -> Excel only when
    write_excel is true, and a workbook backup is taken first by default."""
    if not graph.is_configured():
        raise HTTPException(400, "Microsoft Graph is not configured.")
    backup = None
    try:
        if payload.write_excel and payload.backup_first:
            backup = excel_sync.backup_workbook()
        result = excel_sync.apply_sync(
            db,
            write_excel=payload.write_excel,
            conflict_resolution=payload.conflict_resolution,
        )
        result["backup"] = backup
        return result
    except graph.GraphError as e:
        raise HTTPException(502, str(e))
