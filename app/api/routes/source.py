import os, uuid
from fastapi import APIRouter, UploadFile, File, Header, Request, HTTPException
from app.schemas.source import TextSourceRequest, URLSourceRequest
from app.core.redis import get_source_status

router = APIRouter()

@router.get("/")
async def read_root():
    return {"message": "Hello World"}

@router.post("/pdf")
async def upload_pdf(request:Request, file: UploadFile = File(...), x_user_id: str = Header(...)):
   
    if file.content_type != "application/pdf":
        return {"error": "Invalid file type. Only PDF files are allowed."}
    
    source_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, file.filename))
    
    # Save the file to the uploads directory
    os.makedirs("uploads", exist_ok=True)
    file_path = f"uploads/{source_id}.pdf"
    with open(file_path, "wb") as f:
        f.write(await file.read())

    pool = request.app.state.arq_pool
    await pool.enqueue_job(
        "ingest_source_pdf",
        source_path=file_path,
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

    # enqueue_ingestion(source_id, text, x_user_id)
    pool = request.app.state.arq_pool
    await pool.enqueue_job(
        "ingest_source_text",
        user_id=x_user_id,
        source_id=source_id,
        text=text,
        source_title=source_title
    )

    return {"text": text[:100], "userId": x_user_id, "sourceId": source_id}

@router.get("/{source_id}/status")
async def source_status(request: Request, source_id: str):
    redis = request.app.state.arq_pool
    status = await get_source_status(redis, source_id)

    if not status:
        print(f"Status for source {source_id} not found in Redis.")
        raise HTTPException(status_code=404, detail="Status not found")
    print(f"Status for source {source_id}: {status}")
    return status
