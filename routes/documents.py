"""Document management routes"""
import uuid
import aiofiles
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import FileResponse
from database import db
from auth_utils import get_current_user, require_approved_user
from constants import DOC_TYPES
from database import ROOT_DIR
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter(prefix="/documents", tags=["documents"])

UPLOAD_DIR = ROOT_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


@router.post("/upload/{acid_id}")
async def upload_document(
    acid_id: str, doc_type: str = Form(...), file: UploadFile = File(...),
    current_user=Depends(require_approved_user)
):
    acid_req = (await db.acid_requests.find_one({"_id": ObjectId(acid_id)}) if ObjectId.is_valid(acid_id) else None) or \
               await db.acid_requests.find_one({"acid_number": acid_id})
    if not acid_req:
        raise HTTPException(404, "طلب ACID غير موجود")
    if doc_type not in DOC_TYPES:
        raise HTTPException(400, "نوع المستند غير صحيح")
    actual_id = str(acid_req["_id"])
    ext = Path(file.filename).suffix.lower() if file.filename else ".bin"
    if ext not in ['.pdf', '.jpg', '.jpeg', '.png', '.docx', '.xlsx']:
        raise HTTPException(400, "نوع الملف غير مدعوم (PDF, JPG, PNG, DOCX, XLSX)")
    acid_dir = UPLOAD_DIR / actual_id
    acid_dir.mkdir(parents=True, exist_ok=True)
    file_id = str(uuid.uuid4())
    saved_path = acid_dir / f"{file_id}{ext}"
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "حجم الملف يتجاوز 10 ميجابايت")
    async with aiofiles.open(saved_path, 'wb') as f:
        await f.write(content)
    doc_meta = {
        "file_id": file_id, "acid_id": actual_id,
        "acid_number": acid_req.get("acid_number"),
        "doc_type": doc_type, "doc_type_ar": DOC_TYPES[doc_type]["ar"],
        "doc_type_en": DOC_TYPES[doc_type]["en"],
        "original_filename": file.filename, "saved_path": str(saved_path),
        "file_size": len(content), "content_type": file.content_type,
        "uploaded_by": current_user["_id"],
        "uploaded_by_name": current_user.get("name_ar") or current_user.get("name_en"),
        "uploaded_at": datetime.now(timezone.utc), "is_active": True
    }
    result = await db.documents.insert_one(doc_meta)
    doc_meta["_id"] = str(result.inserted_id)
    doc_meta["uploaded_at"] = doc_meta["uploaded_at"].isoformat()
    return {"message": "تم رفع المستند بنجاح", "document": doc_meta}


@router.get("/file/{file_id}")
async def download_document(file_id: str, current_user=Depends(get_current_user)):
    doc = await db.documents.find_one({"file_id": file_id, "is_active": True})
    if not doc:
        raise HTTPException(404, "المستند غير موجود")
    fp = Path(doc["saved_path"])
    if not fp.exists():
        raise HTTPException(404, "الملف غير موجود")
    return FileResponse(str(fp), media_type=doc.get("content_type", "application/octet-stream"),
                        filename=doc.get("original_filename", file_id))


@router.get("/{acid_id}")
async def list_documents(acid_id: str, current_user=Depends(get_current_user)):
    acid_req = (await db.acid_requests.find_one({"_id": ObjectId(acid_id)}) if ObjectId.is_valid(acid_id) else None) or \
               await db.acid_requests.find_one({"acid_number": acid_id})
    if not acid_req:
        raise HTTPException(404, "طلب ACID غير موجود")
    docs = await db.documents.find({"acid_id": str(acid_req["_id"]), "is_active": True}).sort("uploaded_at", -1).to_list(50)
    result = []
    for d in docs:
        d["_id"] = str(d["_id"])
        if isinstance(d.get("uploaded_at"), datetime):
            d["uploaded_at"] = d["uploaded_at"].isoformat()
        result.append(d)
    return result


@router.delete("/{file_id}")
async def delete_document(file_id: str, current_user=Depends(require_approved_user)):
    doc = await db.documents.find_one({"file_id": file_id})
    if not doc:
        raise HTTPException(404, "المستند غير موجود")
    if doc["uploaded_by"] != current_user["_id"] and current_user["role"] not in ["admin", "acid_reviewer"]:
        raise HTTPException(403, "غير مصرح")
    await db.documents.update_one({"file_id": file_id}, {"$set": {"is_active": False}})
    return {"message": "تم الحذف"}
