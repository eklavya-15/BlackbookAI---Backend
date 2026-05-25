# poll.py
import httpx, asyncio, json

SOURCE_ID = "40b7f417-efc7-5db5-b046-a25fdb623a61"

async def poll():
    async with httpx.AsyncClient() as client:
        while True:
            r = await client.get(f"http://localhost:8000/source/{SOURCE_ID}/status")
            data = r.json()
            print(json.dumps(data, indent=2))
            if data.get("status") in ("completed", "failed"):
                print("Done.")
                break
            await asyncio.sleep(2)

asyncio.run(poll())