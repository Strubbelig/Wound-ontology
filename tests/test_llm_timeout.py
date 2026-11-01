"""A stalled request must fail, not hang.

On 2026-09-26 the term-mapping build stopped for 3h40m after two
timeout-and-retry cycles: no open sockets, no timers, 2.5 seconds of CPU in
two hours, the event loop parked in kqueue forever. `asyncio.wait_for` does
not abort a request — it CANCELS it and then awaits the cancellation
finishing, so if the HTTP client's teardown never finishes, `wait_for` hangs
*after* its own timeout has fired. Nothing wrapped around it can help: the
await that never returns is inside the timeout mechanism itself.

The budget therefore goes to the transport, which enforces it without
cancelling anything, and `wait_for` stays only as a backstop.
"""

import asyncio

import httpx
import pytest

from wound_ontology.llm.llm_client import LLMClient


@pytest.fixture
def client():
    return LLMClient(api_key="test-key")


def test_the_transport_carries_a_timeout_of_its_own(client):
    assert isinstance(client._client.timeout, httpx.Timeout)
    assert client._client.timeout.read is not None


def test_the_pool_cannot_be_waited_on_forever(client):
    """The hang opened no socket at all, which is what waiting for a free
    connection looks like: a cancelled request can leave its slot in the pool
    un-returned, and without this the next call waits for it forever."""
    assert client._client.timeout.pool is not None


def test_connecting_has_a_shorter_leash_than_reading(client):
    """A model thinking for four minutes is normal; a TCP connect taking four
    minutes is a dead endpoint."""
    assert client._client.timeout.connect < client._client.timeout.read


def test_the_sdk_does_not_retry_behind_our_retry(client):
    """The SDK retries twice by default, inside our own budget — which both
    multiplies the wall time and makes `[LLM] Retry 1` a lie about how many
    attempts were made."""
    assert client._client.max_retries == 0


def test_the_per_call_budget_reaches_the_request(client, monkeypatch):
    """Each call site passes its own budget (240s, 360s). It has to arrive at
    the request, or the transport enforces the default instead."""
    seen = {}

    async def _create(**kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop here — the kwargs are what this test is about")

    monkeypatch.setattr(client._client.chat.completions, "create", _create)
    with pytest.raises(RuntimeError):
        asyncio.run(client._call_json("prompt", _Schema, timeout=360))
    assert seen.get("timeout") == 360


def test_the_backstop_leaves_the_transport_room_to_fire_first(client, monkeypatch):
    """If `wait_for` fired at the same moment as the transport it would race,
    and the cancellation path is the one that hangs. The transport has to get
    there first, so the backstop is given slack — it should only ever fire
    when the transport did not fire at all, which is a defect, not a timeout.
    """
    import wound_ontology.llm.llm_client as mod

    seen = {}
    real_wait_for = asyncio.wait_for

    async def _spy(aw, timeout):
        seen["backstop"] = timeout
        return await real_wait_for(aw, timeout=timeout)

    async def _create(**kwargs):
        seen["transport"] = kwargs["timeout"]
        raise RuntimeError("stop here")

    monkeypatch.setattr(mod.asyncio, "wait_for", _spy)
    monkeypatch.setattr(client._client.chat.completions, "create", _create)
    with pytest.raises(RuntimeError):
        asyncio.run(client._call_json("prompt", _Schema, timeout=240))

    assert seen["transport"] == 240
    assert seen["backstop"] > seen["transport"], (
        "the backstop must not race the transport it is backing up")


class _Schema:
    @staticmethod
    def model_json_schema():
        return {"type": "object"}

    @staticmethod
    def model_validate_json(raw):
        return raw
