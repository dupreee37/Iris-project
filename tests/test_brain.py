import asyncio

import pytest

from iris.brain import Brain


class Manager:
    def __init__(self):
        self.calls = []
        self.release = asyncio.Event()

    def validate(self, name, arguments):
        return dict(arguments)

    async def execute(self, name, arguments, *, approved=False):
        self.calls.append((name, arguments, approved))
        if name == "slow":
            await self.release.wait()
        return {"ok": True}


async def test_slow_tool_does_not_block_immediate_tool():
    manager = Manager()
    brain = Brain(manager)
    slow = brain.submit("a", "slow-call", "slow", {})
    fast = brain.submit("a", "fast-call", "fast", {})
    await fast.task
    assert fast.status == "completed"
    assert slow.status == "running"
    await brain.close()


async def test_idempotency_and_argument_binding():
    manager = Manager()
    brain = Brain(manager)
    job = brain.submit("a", "one", "fast", {"query": "original"})
    assert brain.submit("a", "one", "fast", {"query": "original"}) is job
    with pytest.raises(ValueError):
        brain.submit("a", "one", "fast", {"query": "changed"})
    await job.task
    assert len(manager.calls) == 1


async def test_approval_cannot_be_duplicated_or_change_payload():
    manager = Manager()
    brain = Brain(manager)
    job = brain.submit("a", "one", "open_url", {"url": "https://example.com"})
    assert job.status == "awaiting_approval" and manager.calls == []
    brain.approve(job)
    with pytest.raises(ValueError):
        brain.approve(job)
    await job.task
    assert manager.calls == [("open_url", {"url": "https://example.com"}, True)]


async def test_cancellation_stays_cancelled():
    manager = Manager()
    brain = Brain(manager)
    job = brain.submit("a", "one", "slow", {})
    await asyncio.sleep(0)
    brain.cancel(job)
    manager.release.set()
    await job.task
    assert job.status == "cancelled"
    assert "error" in job.result


async def test_timeout_and_capacity():
    brain = Brain(Manager(), timeout=0.01, max_active=1)
    job = brain.submit("a", "one", "slow", {})
    with pytest.raises(ValueError):
        brain.submit("a", "two", "fast", {})
    await job.task
    assert job.status == "failed" and "tiempo" in job.result["error"]


async def test_owner_isolation_and_expired_approval():
    brain = Brain(Manager())
    job = brain.submit("a", "one", "open_url", {})
    with pytest.raises(KeyError):
        brain.get("b", job.id)
    job.created -= 121
    assert brain.get("a", job.id).status == "cancelled"
    with pytest.raises(ValueError):
        brain.approve(job)
