import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from backend.database import get_connection
from backend.jobs.job_runner import subscribe_events, unsubscribe_events

router = APIRouter(prefix="/api/progress", tags=["progress"])


@router.get("/stream")
async def progress_stream(run_id: Optional[int] = None):
    async def generator():
        conn = get_connection()
        query = "SELECT event_type, payload FROM progress_events"
        params: tuple = ()
        if run_id is not None:
            query += " WHERE run_id=? ORDER BY id DESC LIMIT 50"
            params = (run_id,)
        else:
            query += " ORDER BY id DESC LIMIT 50"

        recent = conn.execute(query, params).fetchall()
        conn.close()

        for row in reversed(recent):
            yield f"event: {row['event_type']}\ndata: {row['payload']}\n\n"

        queue = subscribe_events()
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue

                if msg is None:
                    yield "event: run_complete\ndata: {}\n\n"
                    break

                event_type = msg.pop("type", "message")
                yield f"event: {event_type}\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n"
        finally:
            unsubscribe_events(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/events")
def get_recent_events(limit: int = Query(default=200, le=500)):
    conn = get_connection()
    rows = conn.execute(
        """SELECT pe.id, pe.run_id, pe.event_type, pe.payload, pe.created_at
           FROM progress_events pe
           ORDER BY pe.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    events = []
    for row in reversed(rows):
        payload = json.loads(row["payload"])
        events.append({
            "id": row["id"],
            "run_id": row["run_id"],
            "type": row["event_type"],
            "created_at": row["created_at"],
            **payload,
        })
    return events
