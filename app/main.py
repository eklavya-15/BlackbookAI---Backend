import asyncio
from arq.worker import Worker
from fastapi import FastAPI
from arq import create_pool
from app.api.routes import source, chat
from app.workers.ingestion_worker import WorkerSettings
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.core.qdrant import delete_all_collections, client
from fastapi.middleware.cors import CORSMiddleware


async def start_worker():
    worker = Worker(
        functions=WorkerSettings.functions,
        redis_settings=WorkerSettings.redis_settings
    )
    await worker.async_run()

@asynccontextmanager
async def lifespan(app: FastAPI):

    # Create ARQ pool
    app.state.arq_pool = await create_pool(
        WorkerSettings.redis_settings
    )
    # start worker in background
    worker_task = asyncio.create_task(start_worker())

    
    # Scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        delete_all_collections,
        trigger="cron",
        hour=0,
        minute=0,
        args=[client]
    )
    scheduler.start()

    yield

    # Cleanup
    worker_task.cancel()
    scheduler.shutdown()


    # Close ARQ pool
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