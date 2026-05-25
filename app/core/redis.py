import json
from arq.connections import RedisSettings, create_pool, ArqRedis
import os
from dotenv import load_dotenv
load_dotenv()

REDIS_URL = os.getenv("REDIS_URL")

redis_settings = RedisSettings(
    host="3.110.55.133",
    port=16012,
    username=os.getenv("REDIS_USERNAME"),
    password=os.getenv("REDIS_PASSWORD"),
)
async def set_source_status(redis: ArqRedis, source_id: str, status: dict):
    key = f"source:status:{source_id}"
    await redis.set(key, json.dumps(status), ex=3600)
    
    # confirm it was written
    written = await redis.get(key)
    print(f"[REDIS SET] key={key} | written={written}")

async def get_source_status(redis: ArqRedis, source_id: str) -> dict | None:
    key = f"source:status:{source_id}"
    data = await redis.get(key)
    print(f"[DEBUG] key={key}, raw={data}")  # add this temporarily
    if data is None:
        return None
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return json.loads(data) 