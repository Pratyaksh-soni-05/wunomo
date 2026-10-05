"""Blueprint §11 (Outputs) -- backend only this pass. See
services/output_service.py's module docstring for the storage/trust-score/
provenance design, and models/all_models.py's Output docstring for why
this table has no rows from any real tool yet.

Read endpoints only (list/get/provenance/download) -- any authenticated
tenant member, same gate GET /pipelines/ and GET /tasks/ already use for
read access within a tenant (no outputs.* permission tier exists, and
none is added here: nothing about viewing an already-produced file is a
privileged action the way editing agent scope or hiring is). Writing an
Output happens through OutputService.create_output() directly, called by
a future file-producing tool -- not an HTTP endpoint in this pass, since
nothing exists yet to call it from outside the backend process.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .auth import get_current_user
from modules.ingestion.connector_manager import UPLOAD_DIR
from services.output_service import OutputService

router = APIRouter()


def _resolve_output_file_path(storage_ref: str) -> Path | None:
    """Same real check modules/ingestion/connector_manager.py's own
    _resolve_uploaded_file_path() enforces, reimplemented locally rather
    than importing that underscore-prefixed (module-private-by-
    convention) helper across a module boundary -- storage_ref is never
    user-supplied at this endpoint (only the opaque output_id is,
    resolved server-side first), so this is defense in depth against a
    hypothetical corrupted row, not the primary access control (that's
    RLS, scoping the row lookup itself to this tenant)."""
    resolved = Path(storage_ref).resolve()
    upload_root = Path(UPLOAD_DIR).resolve()
    if not resolved.is_relative_to(upload_root):
        return None
    return resolved


@router.get("/")
async def list_outputs(project_id: str | None = None, user=Depends(get_current_user)):
    outputs = await OutputService(user["tenant_id"]).list_outputs(project_id=project_id)
    return {"outputs": outputs, "count": len(outputs)}


@router.get("/{output_id}")
async def get_output(output_id: str, user=Depends(get_current_user)):
    output = await OutputService(user["tenant_id"]).get_output(output_id)
    if output is None:
        raise HTTPException(status_code=404, detail="Output not found.")
    return output


@router.get("/{output_id}/provenance")
async def get_output_provenance(output_id: str, user=Depends(get_current_user)):
    provenance = await OutputService(user["tenant_id"]).get_provenance(output_id)
    if provenance is None:
        raise HTTPException(status_code=404, detail="Output not found.")
    return provenance


@router.get("/{output_id}/download")
async def download_output(output_id: str, user=Depends(get_current_user)):
    output = await OutputService(user["tenant_id"]).get_output_row(output_id)
    if output is None:
        raise HTTPException(status_code=404, detail="Output not found.")
    real_path = _resolve_output_file_path(output.storage_ref)
    if real_path is None or not real_path.is_file():
        raise HTTPException(status_code=404, detail="The underlying file is no longer available.")
    return FileResponse(path=str(real_path), filename=output.filename, media_type=output.content_type)
