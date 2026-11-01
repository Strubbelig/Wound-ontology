"""What each statement the relation check held back clashes with, for the judgement page.

    python -u scripts/relation_clashes_for_review.py OUT.json QUARANTINE.json

Runs the relation check on the store WITHOUT saving anything (the term dict's
save is replaced by a no-op), checks that it holds back exactly what the real
run did (QUARANTINE.json, output/quarantine/*_store_relations.json), and
writes `GateResult.causes`: each cause with its two sides (rule 76).
`scripts/judgement_queue_data.py` reads the latest data/review/relation_clashes_*.json.
"""
import json, sys, time
from pathlib import Path
ROOT = Path.cwd(); sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
from wound_ontology.orchestrator import Orchestrator
from wound_ontology.llm.extraction_adapter import store_to_gate_inputs
out = Path(sys.argv[1]); ref = json.load(open(sys.argv[2]))
p = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
st = p.store; st.terms.save = lambda *a, **k: None
st.reopen = (p.GATE_AUTHOR, "relations")      # ELK's own verdicts set aside, as in the real run (rule 89)
gate = p.reasoner_gate
gate._explain = lambda g, max_expl=5: "(not asked)"
ents, rels, _ = store_to_gate_inputs(st, resolve_conflict=gate.least_common_category)
res = gate.check(ents, rels)
held = sorted((r.subject, r.predicate.value, r.object) for r in res.quarantined_relations)
ref_held = sorted((r["subject"], r["predicate"], r["object"]) for r in ref["relations"])
print(f"[c] {res.summary()}", flush=True)
print(f"[c] same held-back set as the real run: {held == ref_held} ({len(held)} vs {len(ref_held)})", flush=True)
if held != ref_held:
    raise SystemExit("[c] differs from the real run -- not writing")
data = {"made": time.strftime("%Y-%m-%dT%H:%M:%S"), "from": sys.argv[2], "causes": res.causes}
out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
assert json.loads(out.read_text(encoding="utf-8")) == json.loads(json.dumps(data))
from collections import Counter
print(f"[c] written and read back: {out} -- {Counter(c['kind'] for c in res.causes)}", flush=True)
