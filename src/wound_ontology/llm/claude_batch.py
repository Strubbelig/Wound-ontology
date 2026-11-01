"""Claude Opus 5.5 as a reader inside the pipeline, through OpenRouter's batch API.

Curator, 2026-10-29: the readings Claude did in Claude Code sessions --
placements row by row, the instance readings of the relations, the review of
the `same` answers, the relation decisions -- "were only quick and easy, but
not right". The rows carried labels only, and a row Claude did not list stood
as answered. Here every reading is a program: a fixed prompt in code (so
Anhang D prints it), one explicit answer per row in a schema the model must
keep, and every answer stored on disk exactly as it came back.

Access is OpenRouter, as for DeepSeek (the curator's choice), through its
batch endpoint (`/api/v1/batches`, half the sync price; most batches finish in
minutes, all within 24 h). The request body is Anthropic's Messages body
(`endpoint: /v1/messages`): adaptive thinking, an effort level, and
`output_config.format`, a JSON schema the answer is constrained to. Claude
Opus 5.5 takes no temperature. Tested 2026-10-29: thinking blocks come back,
the text is schema-valid JSON, and the batch reports the model snapshot
(`anthropic/claude-opus-5.5-20260921`).

Nothing fails quietly: a request that ends for any reason but `end_turn`
(the token cap, a refusal), an answer that is not valid JSON, a request that
never came back -- each is an error, named in `failures()`.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

MODEL = "anthropic/claude-opus-5.5"
ENDPOINT = "/v1/messages"
URL = "https://openrouter.ai/api/v1/batches"
#: Requests per batch. OpenRouter documents a per-batch cap without a number;
#: a batch over it is refused with 413, which `submit` raises.
PER_BATCH = 200
TERMINAL = ("completed", "failed", "expired", "cancelled")


def request_body(prompt: str, schema: dict, *, effort: str = "high", max_tokens: int = 12_000) -> dict:
    """The Messages body of one request: the prompt as the user turn, adaptive
    thinking, the effort level, and the answer constrained to `schema`."""
    return {"max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}}}


@dataclass
class Answer:
    custom_id: str
    answer: dict | None
    error: str | None
    model: str | None
    usage: dict


class BatchRun:
    """One reading's requests, in as many batches as it takes, resumable.

    `run_dir` holds `state.json` (which custom ids went into which batch) and
    one `<batch id>.json` per finished batch -- the raw answer, never edited.
    A second `submit` sends only the ids not sent yet; `wait` picks up batches
    still running; `answers` reads what is on disk.
    """

    def __init__(self, run_dir: Path, *, api_key: str | None = None):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.dir / "state.json"
        self.state = json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.exists() \
            else {"model": MODEL, "endpoint": ENDPOINT, "batches": []}
        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("no OPENROUTER_API_KEY: Claude cannot be asked")
        self._h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _save(self) -> None:
        self.state_path.write_text(json.dumps(self.state, indent=1), encoding="utf-8")

    def sent(self) -> set[str]:
        return {c for b in self.state["batches"] for c in b["custom_ids"]}

    def submit(self, requests: list[tuple[str, dict]]) -> int:
        """Send `(custom_id, body)` pairs not sent before; returns how many were sent."""
        ids = [c for c, _ in requests]
        if len(ids) != len(set(ids)):
            raise ValueError("custom ids repeat within one reading")
        todo = [(c, b) for c, b in requests if c not in self.sent()]
        for i in range(0, len(todo), PER_BATCH):
            chunk = todo[i:i + PER_BATCH]
            body = {"endpoint": ENDPOINT, "model": MODEL,
                    "requests": [{"custom_id": c, "body": b} for c, b in chunk]}
            while True:
                r = httpx.post(URL, headers=self._h, json=body, timeout=120)
                # OpenRouter checks the balance against a worst case (every
                # request at its token cap). While batches of this run are still
                # out, their hold comes back when they finish: wait for them and
                # send again. With none out, the balance is simply too low.
                running = [b for b in self.state["batches"] if b["status"] not in TERMINAL]
                if r.status_code == 402 and running:
                    print(f"[claude] balance too low for the next batch ({r.json().get('error', {}).get('message', '')[:120]}); "
                          f"waiting for {len(running)} running batch(es)", flush=True)
                    self.wait(poll=60, until_one_finishes=True)
                    continue
                break
            if r.status_code != 202:
                raise RuntimeError(f"batch refused ({r.status_code}): {r.text[:300]}")
            j = r.json()
            # what was asked, beside what came back (from 2026-10-29, after the
            # first readings: those are rebuilt from the code and the data)
            (self.dir / f"{j['id']}.requests.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
            self.state["batches"].append({"id": j["id"], "status": j["status"], "model": j.get("model"),
                                          "sent_at": time.time(), "custom_ids": [c for c, _ in chunk]})
            self._save()
            print(f"[claude] batch {j['id']}: {len(chunk)} request(s) sent ({j.get('model')})", flush=True)
        return len(todo)

    def wait(self, *, poll: float = 30.0, timeout: float = 26 * 3600, until_one_finishes: bool = False) -> None:
        """Poll every batch not yet finished; store each finished one as it came back.
        `until_one_finishes`: return as soon as one more batch has finished."""
        start = time.time()
        done_before = sum(1 for b in self.state["batches"] if b["status"] in TERMINAL)
        while True:
            if until_one_finishes and sum(1 for b in self.state["batches"] if b["status"] in TERMINAL) > done_before:
                return
            open_ = [b for b in self.state["batches"] if b["status"] not in TERMINAL
                     or not (self.dir / f"{b['id']}.json").exists()]
            if not open_:
                return
            for b in open_:
                try:
                    r = httpx.get(f"{URL}/{b['id']}", headers=self._h, timeout=120)
                except httpx.TransportError as e:           # the network, not the batch
                    print(f"[claude] batch {b['id']}: {type(e).__name__}, asked again next round", flush=True)
                    continue
                # A batch is not always found the moment it is created (404 seen
                # 2026-10-29 seconds after a 202), and the service can hiccup:
                # both are asked again; anything else, or a 404 that lasts, is raised.
                sent = b.get("sent_at") or float(b["id"].split("-")[1])   # the id carries its creation time
                young = time.time() - sent < 600
                if (r.status_code == 404 and young) or r.status_code >= 500:
                    print(f"[claude] batch {b['id']}: {r.status_code}, asked again next round", flush=True)
                    continue
                r.raise_for_status()
                j = r.json()
                b["status"] = j["status"]
                if j["status"] in TERMINAL:
                    (self.dir / f"{b['id']}.json").write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
                    print(f"[claude] batch {b['id']}: {j['status']}, {j.get('request_counts')}, "
                          f"cost {((j.get('usage') or {}).get('cost'))}", flush=True)
            self._save()
            if time.time() - start > timeout:
                raise TimeoutError(f"{len(open_)} batch(es) still running after {timeout / 3600:.0f} h")
            if any(b["status"] not in TERMINAL or not (self.dir / f"{b['id']}.json").exists()
                   for b in self.state["batches"]):
                time.sleep(poll)

    def answers(self) -> dict[str, Answer]:
        """Every request sent, with its parsed answer or the reason there is none."""
        out: dict[str, Answer] = {}
        for b in self.state["batches"]:
            f = self.dir / f"{b['id']}.json"
            raw = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
            snap = raw.get("model") or b.get("model")
            got = {x["custom_id"]: x for x in raw.get("results") or []}
            for c in b["custom_ids"]:
                x = got.get(c)
                if x is None:
                    out[c] = Answer(c, None, f"no result (batch {raw.get('status', 'not finished')})", snap, {})
                    continue
                if x.get("error"):
                    out[c] = Answer(c, None, f"error: {json.dumps(x['error'])[:300]}", snap, {})
                    continue
                body = (x.get("response") or {}).get("body") or {}
                usage = body.get("usage") or {}
                if body.get("stop_reason") != "end_turn":
                    out[c] = Answer(c, None, f"stopped: {body.get('stop_reason')}", snap, usage)
                    continue
                text = "".join(blk.get("text", "") for blk in body.get("content") or [] if blk.get("type") == "text")
                try:
                    out[c] = Answer(c, json.loads(text), None, snap, usage)
                except json.JSONDecodeError as e:
                    print(f"[claude] {c}: the answer is not JSON ({e}); recorded as an error", flush=True)
                    out[c] = Answer(c, None, f"not JSON: {e}", snap, usage)
        return out

    def cost(self) -> float:
        tot = 0.0
        for b in self.state["batches"]:
            f = self.dir / f"{b['id']}.json"
            if f.exists():
                tot += float(((json.loads(f.read_text(encoding="utf-8")).get("usage") or {}).get("cost")) or 0)
        return tot

    def snapshots(self) -> set[str]:
        return {b.get("model") for b in self.state["batches"] if b.get("model")}
