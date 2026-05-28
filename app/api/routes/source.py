import io
import os, uuid
from fastapi import APIRouter, UploadFile, File, Header, Request, HTTPException
from app.schemas.source import TextSourceRequest, URLSourceRequest
from app.core.redis import get_source_status
from app.core.r2 import s3

router = APIRouter()

@router.get("/")
async def read_root():
    return {"message": "Hello World"}

@router.post("/pdf")
async def upload_pdf(request:Request, file: UploadFile = File(...), x_user_id: str = Header(...)):
   
    if file.content_type != "application/pdf":
        return {"error": "Invalid file type. Only PDF files are allowed."}
    
    source_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, file.filename))
    
    # Upload to R2
    r2_key = f"uploads/{source_id}.pdf"
    file_bytes = await file.read()
    s3.upload_fileobj(io.BytesIO(file_bytes), os.getenv("R2_BUCKET_NAME"), r2_key)

    pool = request.app.state.arq_pool
    await pool.enqueue_job(
        "ingest_source_pdf",
        r2_key=r2_key,
        source_name=file.filename,
        user_id=x_user_id,
        source_id=source_id
    )

    return {"fileName": file.filename,"userId": x_user_id, "sourceId": source_id}

@router.post("/url")
async def upload_url(request: Request, payload: URLSourceRequest, x_user_id: str = Header(...)):
    url = payload.url
    source_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, url))
    
    # enqueue_ingestion(source_id, url, x_user_id)
    pool = request.app.state.arq_pool
    await pool.enqueue_job(
        "ingest_source_url",
        user_id=x_user_id,
        source_id=source_id,
        url=url
    )

    return {"url": url, "userId": x_user_id, "sourceId": source_id}

@router.post("/text")
async def upload_text(request: Request, payload: TextSourceRequest, x_user_id: str = Header(...)):
 
    if payload.type != "text":
        return {"error": "Invalid content type. Only text content is allowed."}

    text = payload.text
    source_title = payload.sourceTitle
    source_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, text[:100]))

    pool = request.app.state.arq_pool
    await pool.enqueue_job(
        "ingest_source_text",
        user_id=x_user_id,
        source_id=source_id,
        text=text,
        source_title=source_title
    )

    return {"text": text[:50], "userId": x_user_id, "sourceId": source_id}

@router.get("/{source_id}/status")
async def source_status(request: Request, source_id: str):
    redis = request.app.state.arq_pool
    status = await get_source_status(redis, source_id)

    if not status:
        print(f"Status for source {source_id} not found in Redis.")
        raise HTTPException(status_code=404, detail="Status not found")
    print(f"Status for source {source_id}: {status}")
    return status
