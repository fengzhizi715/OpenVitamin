import asyncio
from contextlib import asynccontextmanager


class AsyncRWLock:
    """
    Minimal asyncio RW lock with writer preference.
    Readers can proceed concurrently; writers wait for all readers to finish.
    When a writer is waiting, new readers are blocked.
    """

    def __init__(self) -> None:
        self._readers = 0
        self._writer = False
        self._write_waiters = 0
        self._cond = asyncio.Condition()

    async def acquire_read(self) -> None:
        async with self._cond:
            while self._writer or self._write_waiters > 0:
                await self._cond.wait()
            self._readers += 1

    async def release_read(self) -> None:
        async with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    async def acquire_write(self) -> None:
        async with self._cond:
            self._write_waiters += 1
            try:
                while self._writer or self._readers > 0:
                    await self._cond.wait()
                self._writer = True
            finally:
                self._write_waiters -= 1

    async def release_write(self) -> None:
        async with self._cond:
            self._writer = False
            self._cond.notify_all()

    @asynccontextmanager
    async def read_lock(self):
        await self.acquire_read()
        try:
            yield
        finally:
            await self.release_read()

    @asynccontextmanager
    async def write_lock(self):
        await self.acquire_write()
        try:
            yield
        finally:
            await self.release_write()
