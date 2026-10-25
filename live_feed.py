"""Shared synthetic IMU feed used by WebSocket telemetry and the recorder."""
from __future__ import annotations

import asyncio
from typing import Callable

from simulator import make_motion

KINDS_CYCLE = ('idle', 'flick_right', 'idle', 'double_twist', 'idle', 'circle')


class SyntheticLiveFeed:
    def __init__(self, period_s: float = 0.02, on_sample: Callable[[dict, str], None] | None = None):
        self.period_s = period_s
        self.on_sample = on_sample
        self._queues: list[asyncio.Queue] = []
        self._index = 0
        self._running = False

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._queues.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._queues:
            self._queues.remove(queue)

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        self._running = True
        while self._running:
            kind = KINDS_CYCLE[self._index % len(KINDS_CYCLE)]
            for sample in make_motion(kind, seed=700 + self._index, n=80):
                if not self._running:
                    return
                if self.on_sample is not None:
                    self.on_sample(sample, kind)
                message = {'kind': 'sample', 'source': 'synthetic', 'motion': kind, 'sample': sample}
                for queue in list(self._queues):
                    if queue.full():
                        try:
                            queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    try:
                        queue.put_nowait(message)
                    except asyncio.QueueFull:
                        pass
                await asyncio.sleep(self.period_s)
            self._index += 1
