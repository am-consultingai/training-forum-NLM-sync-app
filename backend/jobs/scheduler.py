import asyncio
from concurrent.futures import ThreadPoolExecutor

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.config import settings
from backend.jobs.job_runner import run_sync

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sync")
_scheduler = AsyncIOScheduler()


async def _trigger_scheduled():
    loop = asyncio.get_running_loop()
    loop.run_in_executor(_executor, lambda: run_sync("scheduler", main_loop=loop))


def init_scheduler():
    _scheduler.add_job(
        _trigger_scheduled,
        "cron",
        hour=settings.sync_schedule_hour,
        minute=settings.sync_schedule_minute,
        id="daily_sync",
        replace_existing=True,
    )
    _scheduler.start()


def shutdown_scheduler():
    _scheduler.shutdown(wait=False)
    _executor.shutdown(wait=False)


def get_executor() -> ThreadPoolExecutor:
    return _executor
