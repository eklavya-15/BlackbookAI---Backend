import asyncio
from arq.worker import Worker
from fastapi import FastAPI
from arq import create_pool
from app.api.routes import source, chat
from app.workers.ingestion_worker import WorkerSettings
from contextlib import asynccontextmanager
from app.core.qdrant import delete_all_collections, client
from fastapi.middleware.cors import CORSMiddleware


async def start_worker():
    print("worker starting")
    worker = Worker(
        functions=WorkerSettings.functions,
        redis_settings=WorkerSettings.redis_settings,
        max_jobs=1,
        job_timeout=300
    )
    try:
        await worker.async_run()
    except asyncio.CancelledError:
        print("worker cancelled cleanly")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create pool first, confirm Redis is up

    s = WorkerSettings.redis_settings
    print(f"Connecting to Redis: {s.host}:{s.port} | user={s.username} | pass={'set' if s.password else 'NOT SET'}")
    app.state.arq_pool = await create_pool(WorkerSettings.redis_settings)
    print("Redis pool ready")

    async def start_worker_delayed():
        await asyncio.sleep(1)  # let startup finish first
        await start_worker()

    worker_task = asyncio.create_task(start_worker_delayed())

    yield

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass  # expected on shutdown

    await app.state.arq_pool.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(source.router, prefix="/source")
app.include_router(chat.router, prefix="/chat")