from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from typing import Optional
import shutil, os, uuid, math
from .auth import get_current_user
from modules.ingestion.connector_manager import ConnectorManager

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.expanduser("~"), "dataops_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTS = {"csv", "xlsx", "xls", "json", "pdf", "docx"}

def sanitize_floats(obj):
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    elif isinstance(obj, dict):
        return {k: sanitize_floats(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_floats(i) for i in obj]
    return obj

@router.post("/")
async def upload_file(file: UploadFile = File(...), user=Depends(get_current_user)):
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")
    dest = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}.{ext}")
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    result = await ConnectorManager(user["tenant_id"]).ingest_file(dest, ext)
    return sanitize_floats({"filename": file.filename, "path": dest, "ext": ext, **result})

@router.post("/register")
async def upload_and_register(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    user=Depends(get_current_user)
):
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")
    dest = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}.{ext}")
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    ingest_result = await ConnectorManager(user["tenant_id"]).ingest_file(dest, ext)
    source_result = await ConnectorManager(user["tenant_id"]).register_source(
        name=name or file.filename,
        source_type=ext.lower(),
        connection_config={"file_path": dest, "original_name": file.filename}
    )
    if "error" in source_result:
        raise HTTPException(status_code=409, detail=source_result["error"])
    return sanitize_floats({
        "filename": file.filename,
        "source_id": source_result["id"],
        "ingest": ingest_result
    })