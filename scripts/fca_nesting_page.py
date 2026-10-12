"""Review page for the FCA nesting proposals (2026-10-04).

    python scripts/fca_nesting_page.py DATA.json OUT.html

DATA.json from scripts/fca_nesting_proposals.py. Decisions are kept in the
artifact's shared store, collection `nest`, one document per proposal
(`{v: "accept" | "refuse", note, child, parent, when}`).
"""
import json
import sys


def main(data_path: str, out_path: str) -> None:
    rows = json.load(open(data_path, encoding="utf-8"))["rows"]
    payload = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    open(out_path, "w", encoding="utf-8").write(TEMPLATE.replace("__ROWS__", payload))
    print(f"wrote {out_path} ({len(rows)} proposals)")


TEMPLATE = r'''<title>Chronic Wound Nesting</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root{
  --ground:#F3F5F4; --panel:#FFFFFF; --ink:#16211E; --muted:#5A6863; --rule:#D6DDDA; --soft:#EAEFED;
  --accent:#0F6B60; --accent-ink:#FFFFFF;
  --ok:#1D7A46; --ok-bg:#E3F2E8; --warn:#9A6200; --warn-bg:#FBF0DA; --bad:#B3261E; --bad-bg:#FBE6E4;
  --refuse:#6B4E3D;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --ground:#0F1514; --panel:#161E1C; --ink:#E2E9E6; --muted:#93A29C; --rule:#2A3532; --soft:#1C2624;
    --accent:#3CB3A0; --accent-ink:#0F1514;
    --ok:#6FD39A; --ok-bg:#16301F; --warn:#E8B04F; --warn-bg:#33260D; --bad:#F08A80; --bad-bg:#3A1714;
    --refuse:#C9A48C;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --ground:#0F1514; --panel:#161E1C; --ink:#E2E9E6; --muted:#93A29C; --rule:#2A3532; --soft:#1C2624;
  --accent:#3CB3A0; --accent-ink:#0F1514;
  --ok:#6FD39A; --ok-bg:#16301F; --warn:#E8B04F; --warn-bg:#33260D; --bad:#F08A80; --bad-bg:#3A1714;
  --refuse:#C9A48C;
}
body{background:var(--ground);color:var(--ink);font:15px/1.55 var(--sans)}
.wrap{max-width:1000px;margin:0 auto;padding-inline:20px;padding-block:28px 64px;display:flex;flex-direction:column;gap:18px}
h1{font-size:25px;line-height:1.2;margin:0;font-weight:600;text-wrap:balance}
.lede{color:var(--muted);margin:6px 0 0;max-width:72ch}
.bar{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--ground);padding-block:10px;border-bottom:1px solid var(--rule);display:flex;flex-direction:column;gap:8px}
.stats{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--muted)}
.stats b{color:var(--ink);font-family:var(--mono);font-weight:500}
.status{font-size:13px;min-height:20px}
.status.bad{color:var(--bad)} .status.warn{color:var(--warn)}
#list{display:flex;flex-direction:column;gap:10px}
h3.sec{font-size:13px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);font-weight:500;margin:14px 0 0;border-top:1px solid var(--rule);padding-top:12px}
.card{background:var(--panel);border:1px solid var(--rule);border-radius:8px;padding:12px 14px;display:grid;grid-template-columns:1fr auto;gap:10px 16px;align-items:start}
.card.dec-accept{border-left:4px solid var(--accent)} .card.dec-refuse{border-left:4px solid var(--refuse)}
.edge{font-size:16px}
.edge .sub{font-family:var(--mono);color:var(--accent);padding-inline:6px}
.edge b{font-weight:600}
.line{font-size:13px;color:var(--muted);margin-top:4px}
.reading{font-size:13.5px;margin-top:6px}
.chip{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:500;margin-right:6px}
.chip.ok{background:var(--ok-bg);color:var(--ok)} .chip.bad{background:var(--bad-bg);color:var(--bad)} .chip.warn{background:var(--warn-bg);color:var(--warn)}
.acts{display:flex;flex-direction:column;gap:6px;min-width:160px}
.acts .row{display:flex;gap:6px}
.btn{font:inherit;font-size:13px;padding:6px 12px;border-radius:6px;border:1px solid var(--rule);background:var(--panel);color:var(--ink);cursor:pointer}
.btn:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.btn.accept[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.btn.refuse[aria-pressed="true"]{background:var(--refuse);border-color:var(--refuse);color:var(--ground)}
textarea{font:inherit;font-size:12.5px;padding:5px 7px;border:1px solid var(--rule);border-radius:6px;background:var(--panel);color:var(--ink);resize:vertical;min-height:30px;width:100%}
.tree{background:var(--panel);border:1px solid var(--rule);border-radius:8px;padding:12px 14px;font-size:13.5px}
.tree h2{font-size:14px;margin:0 0 6px;font-weight:600}
.tree ul{margin:0;padding-left:18px}
.tree .muted{color:var(--muted)}
.flash{animation:fl .9s ease}
@keyframes fl{from{box-shadow:0 0 0 3px var(--accent)}to{box-shadow:none}}
@media (max-width:640px){.card{grid-template-columns:1fr}.acts{min-width:0}}
@media (prefers-reduced-motion:reduce){.flash{animation:none}}
</style>

<div class="wrap">
  <header>
    <h1>What FCA suggests for Chronic Wound</h1>
    <p class="lede">FCA found classes that share properties; it does not say which class belongs under which. Each card is one subclass edge read off a grouping, with the shared properties, Claude's reading and ELK's verdict for that edge added alone to the current core. All 31 classes of the Chronic Wound subtree sit directly under Chronic Wound today. An accepted edge on a WONT class goes into the addition file, not into WONT itself.</p>
  </header>
  <div class="bar">
    <div class="stats" id="stats"></div>
    <div class="status" id="status" aria-live="polite">Loading decisions…</div>
  </div>
  <div class="tree" id="tree"></div>
  <main id="list"></main>
</div>

<script>
(function () {
  var ROWS = __ROWS__;
  var dec = {}, db = null;
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]; }); }
  function say(m, c) { var el = document.getElementById("status"); el.textContent = m; el.className = "status " + (c || ""); }
  function why(e) { return (e && e.code ? e.code + ": " : "") + (e && e.message ? e.message : String(e)); }
  var CLAUDE = { agree: ["ok", "Claude: agree"], doubt: ["warn", "Claude: doubtful"], disagree: ["bad", "Claude: disagree"] };
  function card(r) {
    var d = dec[r.id] || {}, cl = CLAUDE[r.claude];
    var elk = r.elk === "ok" ? '<span class="chip ok">ELK: consistent</span>' : (r.elk.indexOf("not applicable") === 0 ? '<span class="chip warn">no class to check</span>' : '<span class="chip bad">ELK: ' + esc(r.elk) + '</span>');
    return '<article class="card ' + (d.v ? "dec-" + d.v : "") + '" id="' + r.id + '"><div>' +
      '<div class="edge"><b>' + esc(r.child) + '</b><span class="sub">is a</span><b>' + esc(r.parent) + '</b></div>' +
      '<div class="line">' + esc(r.shared) + '</div>' +
      '<div class="reading"><span class="chip ' + cl[0] + '">' + cl[1] + '</span>' + elk + esc(r.reading) + '</div>' +
      '<div class="line">from ' + esc(r.source) + ' · now under: ' + esc(r.child_parents.join(", ") || "—") + (r.child_curated ? ' · a WONT class: the edge goes into the addition' : '') + '</div>' +
      '</div><div class="acts"><div class="row">' +
      '<button type="button" class="btn accept" data-id="' + r.id + '" data-v="accept" aria-pressed="' + (d.v === "accept") + '">Accept</button>' +
      '<button type="button" class="btn refuse" data-id="' + r.id + '" data-v="refuse" aria-pressed="' + (d.v === "refuse") + '">Refuse</button></div>' +
      '<textarea data-id="' + r.id + '" placeholder="Note (optional)" aria-label="Note on this edge">' + esc(d.note || "") + '</textarea></div></article>';
  }
  function tree() {
    var acc = ROWS.filter(function (r) { return dec[r.id] && dec[r.id].v === "accept" && r.parent_iri; });
    var kids = {}, isChild = {};
    acc.forEach(function (r) { (kids[r.parent] = kids[r.parent] || []).push(r.child); isChild[r.child] = true; });
    var roots = Object.keys(kids).filter(function (p) { return !isChild[p]; });
    function li(n, seen) {
      if (seen[n]) return "<li>" + esc(n) + "</li>";
      seen = Object.assign({}, seen); seen[n] = true;
      var k = kids[n] || [];
      return "<li>" + esc(n) + (k.length ? "<ul>" + k.sort().map(function (c) { return li(c, seen); }).join("") + "</ul>" : "") + "</li>";
    }
    document.getElementById("tree").innerHTML = '<h2>What your accepted edges add</h2>' +
      (roots.length ? "<ul>" + roots.sort().map(function (r) { return li(r, {}); }).join("") + "</ul>" : '<p class="muted" style="margin:0">Nothing accepted yet. Accepted edges appear here as a tree.</p>');
  }
  function render() {
    var groups = [["FCA, Chronic Wound subtree", "Within Chronic Wound (Opus gap-fill, clean columns)"],
                  ["the class names, correcting the Chronic Ulcer grouping", "Following from a correction"],
                  ["FCA, Wound subtree, abstracts only", "Under Chronic Wound (abstracts only)"]];
    document.getElementById("list").innerHTML = groups.map(function (g) {
      var rs = ROWS.filter(function (r) { return r.source === g[0]; });
      return rs.length ? '<h3 class="sec">' + g[1] + '</h3>' + rs.map(card).join("") : "";
    }).join("");
    var a = 0, f = 0; ROWS.forEach(function (r) { var v = dec[r.id] && dec[r.id].v; if (v === "accept") a++; if (v === "refuse") f++; });
    document.getElementById("stats").innerHTML = '<span><b>' + ROWS.length + '</b> proposals</span><span><b>' + a + '</b> accepted</span><span><b>' + f + '</b> refused</span><span><b>' + (ROWS.length - a - f) + '</b> undecided</span>';
    tree();
  }
  var queue = Promise.resolve(), timers = {};
  var byId = {}; ROWS.forEach(function (r) { byId[r.id] = r; });
  function persist(r, what) {
    var d = dec[r.id] || {};
    var body = { v: d.v || null, note: d.note || "", child: r.child, parent: r.parent, child_iri: r.child_iri, parent_iri: r.parent_iri, when: new Date().toISOString() };
    dec[r.id] = body;
    if (!db) { say("Not saved: the shared store is unavailable here. Reload the page to try again.", "bad"); return; }
    say("Saving…", "warn");
    queue = queue.then(function () { return db.doc("nest/" + r.id).set(body); })
      .then(function () { say("Saved — " + what + ".", ""); var el = document.getElementById(r.id); if (el) { el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); } })
      .catch(function (e) { say("Not saved: " + why(e) + ". Your other decisions are safe.", "bad"); });
  }
  document.getElementById("list").addEventListener("click", function (e) {
    try {
      var b = e.target.closest("button[data-v]"); if (!b) return;
      var r = byId[b.dataset.id]; if (!r) return;
      var d = dec[r.id] = JSON.parse(JSON.stringify(dec[r.id] || {}));
      d.v = d.v === b.dataset.v ? null : b.dataset.v;
      render();
      persist(r, (d.v ? (d.v === "accept" ? "accepted " : "refused ") : "withdrew ") + r.child + " is a " + r.parent);
    } catch (err) { say("That click failed: " + why(err) + ". Nothing was saved.", "bad"); }
  });
  document.getElementById("list").addEventListener("input", function (e) {
    var t = e.target; if (t.tagName !== "TEXTAREA") return;
    var r = byId[t.dataset.id]; if (!r) return;
    var d = dec[r.id] = JSON.parse(JSON.stringify(dec[r.id] || {})); d.note = t.value;
    clearTimeout(timers[r.id]); timers[r.id] = setTimeout(function () { persist(r, "note on " + r.child); }, 900);
  });
  render();
  (window.claude && window.claude.use ? window.claude.use("db") : Promise.resolve(null)).then(function (store) {
    db = store;
    if (!db) { say("No shared store here — decisions cannot be saved from this view.", "bad"); return; }
    return load(1).then(function (n) { render(); say(n ? "Picked up " + n + " earlier decision" + (n === 1 ? "" : "s") + "." : "Ready.", ""); });
  }).catch(function (e) { say("Could not read earlier decisions (" + why(e) + "). They are still stored — reload the page.", "bad"); });
  function load(attempt) {
    return db.collection("nest").limit(200).get().then(function (snap) {
      snap.docs.forEach(function (d) { dec[d.id] = JSON.parse(JSON.stringify(d.data())); });
      return snap.size;
    }, function (e) {
      if (attempt < 3) return new Promise(function (r) { setTimeout(r, 600 * attempt); }).then(function () { return load(attempt + 1); });
      throw e;
    });
  }
})();
</script>
'''

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
