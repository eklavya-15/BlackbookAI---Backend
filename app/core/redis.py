import json
from arq.connections import RedisSettings, create_pool, ArqRedis
import os
from dotenv import load_dotenv
load_dotenv()

redis_settings = RedisSettings(
    host=os.getenv("REDIS_HOST"),   
    port=int(os.getenv("REDIS_PORT")),
    username=os.getenv("REDIS_USERNAME"),
    password=os.getenv("REDIS_PASSWORD"),
    ssl=False,
    conn_timeout=60
)
async def set_source_status(redis: ArqRedis, source_id: str, status: dict):
    key = f"source:status:{source_id}"
    await redis.set(key, json.dumps(status), ex=3600)
    
    # confirm it was written
    written = await redis.get(key)
    print(f"[REDIS SET] key={key} | written=TRUE")

async def get_source_status(redis: ArqRedis, source_id: str) -> dict | None:
    key = f"source:status:{source_id}"
    data = await redis.get(key)
    print(f"[DEBUG] key={key}, raw={data}")  # add this temporarily
    if data is None:
        return None
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return json.loads(data) 