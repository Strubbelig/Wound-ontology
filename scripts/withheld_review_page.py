"""Review page for read relations on existing WONT classes (curator's judgement).

    python scripts/withheld_review_page.py DATA.json OUT.html

DATA.json comes from scripts/withheld_relations_data.py. Decisions are kept in
the artifact's shared store, collection `decision`, one document per relation
(`{v: "add" | "leave", note, subject, predicate, value, when}`); read them back
with ArtifactData before applying anything. Since 2026-10-03 ("most of these
axioms are true for wound, not only pressure ulcer"): quality relations on
wound classes are grouped into clusters, one axiom on Wound each, decided in
collection `lift` (`{v: "wound" | "leave", members: {term: bool}, note}`).
"""
import html
import json
import sys


def main(data_path: str, out_path: str) -> None:
    data = json.load(open(data_path, encoding="utf-8"))
    rows = data["rows"]
    payload = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    clusters = json.dumps(data.get("clusters", []), ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.replace("__ROWS__", payload).replace("__CLUSTERS__", clusters).replace("__N__", str(len(rows)))
    open(out_path, "w", encoding="utf-8").write(page)
    print(f"wrote {out_path} ({len(rows)} relations)")


TEMPLATE = r'''<title>WONT Axiom Review</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root{
  --ground:#F3F5F4; --panel:#FFFFFF; --ink:#16211E; --muted:#5A6863; --rule:#D6DDDA; --soft:#EAEFED;
  --accent:#0F6B60; --accent-ink:#FFFFFF;
  --ok:#1D7A46; --ok-bg:#E3F2E8; --warn:#9A6200; --warn-bg:#FBF0DA; --bad:#B3261E; --bad-bg:#FBE6E4;
  --add:#0F6B60; --leave:#6B4E3D;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --ground:#0F1514; --panel:#161E1C; --ink:#E2E9E6; --muted:#93A29C; --rule:#2A3532; --soft:#1C2624;
    --accent:#3CB3A0; --accent-ink:#0F1514;
    --ok:#6FD39A; --ok-bg:#16301F; --warn:#E8B04F; --warn-bg:#33260D; --bad:#F08A80; --bad-bg:#3A1714;
    --add:#3CB3A0; --leave:#C9A48C;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --ground:#0F1514; --panel:#161E1C; --ink:#E2E9E6; --muted:#93A29C; --rule:#2A3532; --soft:#1C2624;
  --accent:#3CB3A0; --accent-ink:#0F1514;
  --ok:#6FD39A; --ok-bg:#16301F; --warn:#E8B04F; --warn-bg:#33260D; --bad:#F08A80; --bad-bg:#3A1714;
  --add:#3CB3A0; --leave:#C9A48C;
}
body{background:var(--ground);color:var(--ink);font:15px/1.55 var(--sans)}
.wrap{max-width:1080px;margin:0 auto;padding-inline:20px;padding-block:28px 64px;display:flex;flex-direction:column;gap:20px}
h1{font-size:25px;line-height:1.2;margin:0;font-weight:600;text-wrap:balance}
.lede{color:var(--muted);margin:6px 0 0;max-width:72ch}
.bar{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--ground);padding-block:10px;border-bottom:1px solid var(--rule);display:flex;flex-direction:column;gap:10px}
.stats{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:13px;color:var(--muted)}
.stats b{color:var(--ink);font-family:var(--mono);font-weight:500}
.progress{height:6px;background:var(--soft);border-radius:3px;overflow:hidden}
.progress span{display:block;height:100%;background:var(--accent);width:0}
.controls{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center}
.seg{display:flex;flex-wrap:wrap;border:1px solid var(--rule);border-radius:6px;overflow:hidden;background:var(--panel)}
.seg button{font:inherit;font-size:13px;border:0;background:transparent;color:var(--ink);padding:6px 11px;cursor:pointer;border-right:1px solid var(--rule)}
.seg button:last-child{border-right:0}
.seg button[aria-pressed="true"]{background:var(--ink);color:var(--ground)}
input[type=search]{font:inherit;font-size:13px;padding:6px 9px;border:1px solid var(--rule);border-radius:6px;background:var(--panel);color:var(--ink);width:240px;max-width:100%}
.status{font-size:13px;min-height:20px}
.status.bad{color:var(--bad)} .status.warn{color:var(--warn)}
.group{display:flex;flex-direction:column;gap:8px}
.ghead{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 12px;padding-top:6px}
.ghead h2{font-size:17px;margin:0;font-weight:600}
.ghead .iri{font-family:var(--mono);font-size:12px;color:var(--muted)}
details.ax{font-size:13px;color:var(--muted)}
details.ax summary{cursor:pointer}
details.ax ul{margin:6px 0 0;padding-left:18px}
.card{background:var(--panel);border:1px solid var(--rule);border-radius:8px;padding:12px 14px;display:grid;grid-template-columns:1fr auto;gap:10px 16px;align-items:start}
.card.dec-add{border-left:4px solid var(--add)} .card.dec-leave{border-left:4px solid var(--leave)}
.stmt{font-size:15px}
.stmt .pred{font-family:var(--mono);font-size:13px;color:var(--accent);padding-inline:4px}
.stmt .val{font-weight:500}
.meta{display:flex;flex-wrap:wrap;gap:6px 10px;margin-top:6px;font-size:12.5px;color:var(--muted)}
.chip{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:500}
.chip.ok{background:var(--ok-bg);color:var(--ok)} .chip.bad{background:var(--bad-bg);color:var(--bad)} .chip.warn{background:var(--warn-bg);color:var(--warn)}
.res{font-size:12.5px;color:var(--muted);margin-top:4px}
.res code{font-family:var(--mono);font-size:12px}
.pmids a{color:var(--accent);font-family:var(--mono);font-size:12px;margin-right:6px}
.acts{display:flex;flex-direction:column;gap:6px;min-width:150px}
.acts .row{display:flex;gap:6px}
.btn{font:inherit;font-size:13px;padding:6px 12px;border-radius:6px;border:1px solid var(--rule);background:var(--panel);color:var(--ink);cursor:pointer}
.btn:focus-visible,.seg button:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.btn.add[aria-pressed="true"]{background:var(--add);border-color:var(--add);color:var(--accent-ink)}
.btn.leave[aria-pressed="true"]{background:var(--leave);border-color:var(--leave);color:var(--ground)}
textarea{font:inherit;font-size:12.5px;padding:5px 7px;border:1px solid var(--rule);border-radius:6px;background:var(--panel);color:var(--ink);resize:vertical;min-height:30px;width:100%}
.flash{animation:fl .9s ease}
@keyframes fl{from{box-shadow:0 0 0 3px var(--accent)}to{box-shadow:none}}
.empty{color:var(--muted)}
#list{display:flex;flex-direction:column;gap:12px}
h3.sec{font-size:13px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);font-weight:500;margin:18px 0 0;border-top:1px solid var(--rule);padding-top:14px}
.sec-lede{font-size:13.5px;color:var(--muted);margin:0;max-width:75ch}
.cl{background:var(--panel);border:1px solid var(--rule);border-radius:8px;padding:14px;display:grid;grid-template-columns:1fr auto;gap:10px 16px}
.cl.dec-wound{border-left:4px solid var(--add)} .cl.dec-leave{border-left:4px solid var(--leave)}
.cl h4{margin:0;font-size:16px;font-weight:500}
.cl h4 b{font-weight:600}
.cl .why{font-size:13px;color:var(--muted);margin:4px 0 8px}
.terms{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.term{font:inherit;font-size:12.5px;border:1px solid var(--rule);border-radius:14px;padding:2px 10px;background:var(--soft);color:var(--ink);cursor:pointer}
.term[aria-pressed="false"]{text-decoration:line-through;color:var(--muted);background:transparent}
table.carriers{border-collapse:collapse;width:100%;font-size:13px}
table.carriers td{padding:3px 6px;border-top:1px solid var(--rule);vertical-align:top}
table.carriers td.n{color:var(--muted);white-space:nowrap}
.was{font-size:12px;color:var(--muted)}
.btn.wound[aria-pressed="true"]{background:var(--add);border-color:var(--add);color:var(--accent-ink)}
@media (max-width:640px){.cl{grid-template-columns:1fr}}
.foot{font-size:13px;color:var(--muted);max-width:75ch}
@media (max-width:640px){.card{grid-template-columns:1fr}.acts{min-width:0}}
@media (prefers-reduced-motion:reduce){.flash{animation:none}}
</style>

<div class="wrap">
  <header>
    <h1>Relations on existing WONT classes</h1>
    <p class="lede">These relations were read as true of every instance (rule 66), but their subject is a class WONT already curates, so the export left them out. Qualities that hold for every wound come first, grouped so each becomes one axiom on Wound; the rest are decided one by one. An added axiom goes into the addition file; <code>ground_truth_final.owl</code> itself stays as it is. ELK's verdict is for this axiom added alone to WONT and the current core.</p>
  </header>

  <div class="bar">
    <div class="stats" id="stats"></div>
    <div class="progress" aria-hidden="true"><span id="prog"></span></div>
    <div class="controls">
      <div class="seg" role="group" aria-label="Show" id="show"></div>
      <div class="seg" role="group" aria-label="Reasoner" id="elkf"></div>
      <label for="q" style="font-size:13px;color:var(--muted)">Filter <input type="search" id="q" placeholder="class, relation or value"></label>
    </div>
    <div class="status" id="status" aria-live="polite">Loading decisions…</div>
  </div>

  <main id="list"></main>
  <p class="foot">Each relation is stated in the abstracts listed (PMIDs) and was read by Claude as true of every instance of its subject. “Resolves to” shows the class the export would actually use when it differs from the words in the abstracts: a relation can be right as written and still land on the wrong WONT class. Decisions are saved for everyone who opens this page.</p>
</div>

<script>
(function () {
  var ROWS = __ROWS__;
  var CL = __CLUSTERS__;
  var dec = {}, lift = {};
  var db = null;
  var show = "open", elkf = "all";
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]; }); }
  function say(msg, cls) { var el = document.getElementById("status"); el.textContent = msg; el.className = "status " + (cls || ""); }
  function why(e) { return (e && e.code ? e.code + ": " : "") + (e && e.message ? e.message : String(e)); }
  function elkKind(r) { return r.elk === "ok" ? "ok" : (r.elk.indexOf("inconsistent") === 0 ? "inconsistent" : "unsatisfiable"); }
  var openAtStart = {};
  function snapshot() {
    openAtStart = {};
    ROWS.forEach(function (r) { if (!dec[r.id] || !dec[r.id].v) openAtStart[r.id] = true; });
    CL.forEach(function (c) { if (!lift[c.id] || !lift[c.id].v) openAtStart[c.id] = true; });
  }
  function members(c) { var m = (lift[c.id] && lift[c.id].members) || {}; var out = {}; c.terms.forEach(function (t) { out[t] = m[t] !== false; }); return out; }
  function clusterVisible(c) {
    var d = lift[c.id] && lift[c.id].v;
    if (show === "open" && !openAtStart[c.id]) return false;
    if (show === "add" && d !== "wound") return false;
    if (show === "leave" && d !== "leave") return false;
    var q = document.getElementById("q").value.trim().toLowerCase();
    if (q && (c.canonical + " " + c.terms.join(" ")).toLowerCase().indexOf(q) < 0) return false;
    return true;
  }
  function clusterCard(c) {
    var d = lift[c.id] || {}, m = members(c);
    var rows = ROWS.filter(function (r) { return r.cluster === c.id; });
    var carried = rows.filter(function (r) { return m[r.value] !== false && m[c.terms.find(function (t) { return t.toLowerCase() === r.value.toLowerCase(); })] !== false; });
    return '<article class="cl ' + (d.v ? "dec-" + d.v : "") + '" id="' + c.id + '"><div>' +
      '<h4>Every wound has some <b>' + esc(c.canonical) + '</b></h4>' +
      '<div class="why">' + esc(c.why) + ' One axiom on Wound <code>' + esc(c.iri.split("/").pop()) + '</code>; its subclasses inherit it.</div>' +
      '<div class="terms" role="group" aria-label="Terms that name this quality">' + c.terms.map(function (t) {
        return '<button type="button" class="term" data-c="' + c.id + '" data-term="' + esc(t) + '" aria-pressed="' + (m[t] !== false) + '" title="Click to take this term out of the cluster">' + esc(t) + '</button>'; }).join("") + '</div>' +
      '<table class="carriers">' + rows.map(function (r) {
        var was = dec[r.id] && dec[r.id].v ? '<span class="was">(you had: ' + (dec[r.id].v === "add" ? "add" : "leave out") + ')</span>' : "";
        return '<tr><td>' + esc(r.subject_label) + '</td><td>' + esc(r.value) + '</td><td class="n">' + r.abstracts + ' abstr. <span class="pmids">' +
          r.pmids.slice(0, 4).map(function (p) { return '<a href="https://pubmed.ncbi.nlm.nih.gov/' + esc(p) + '/" target="_blank" rel="noopener">' + esc(p) + '</a>'; }).join("") + '</span></td><td>' + was + '</td></tr>'; }).join("") + '</table>' +
      '</div><div class="acts"><div class="row">' +
      '<button type="button" class="btn wound" data-lift="' + c.id + '" data-v="wound" aria-pressed="' + (d.v === "wound") + '">Assert on Wound</button>' +
      '<button type="button" class="btn leave" data-lift="' + c.id + '" data-v="leave" aria-pressed="' + (d.v === "leave") + '">Leave out</button></div>' +
      '<textarea data-lift="' + c.id + '" placeholder="Note (optional)" aria-label="Note on this quality">' + esc(d.note || "") + '</textarea></div></article>';
  }

  var showOpts = [["open", "Undecided"], ["add", "Added"], ["leave", "Left out"], ["all", "All"]];
  var elkOpts = [["all", "Any ELK verdict"], ["ok", "ELK ok"], ["problem", "ELK objects"]];
  function seg(id, opts, cur, set) {
    var el = document.getElementById(id);
    el.innerHTML = opts.map(function (o) { return '<button type="button" data-k="' + o[0] + '" aria-pressed="' + (o[0] === cur) + '">' + o[1] + '</button>'; }).join("");
    el.onclick = function (e) { var b = e.target.closest("button"); if (!b) return; set(b.dataset.k); seg(id, opts, b.dataset.k, set); render(); };
  }
  seg("show", showOpts, show, function (k) { show = k; snapshot(); });
  seg("elkf", elkOpts, elkf, function (k) { elkf = k; });
  document.getElementById("q").addEventListener("input", render);

  function visible() {
    var q = document.getElementById("q").value.trim().toLowerCase();
    return ROWS.filter(function (r) {
      if (r.section === "cluster") return false;
      var d = dec[r.id] && dec[r.id].v;
      if (show === "open" && !openAtStart[r.id]) return false;
      if (show === "add" && d !== "add") return false;
      if (show === "leave" && d !== "leave") return false;
      if (elkf === "ok" && r.elk !== "ok") return false;
      if (elkf === "problem" && r.elk === "ok") return false;
      if (q && (r.subject + " " + r.predicate + " " + r.value + " " + r.subject_label + " " + r.value_label).toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
  }
  function chipFor(r) {
    var k = elkKind(r);
    if (k === "ok") return '<span class="chip ok">ELK: consistent</span>';
    return '<span class="chip bad" title="' + esc(r.elk) + '">ELK: ' + esc(r.elk.length > 90 ? r.elk.slice(0, 90) + "…" : r.elk) + '</span>';
  }
  function card(r) {
    var d = dec[r.id] || {};
    var resolved = [];
    if (r.subject_label && r.subject_label.toLowerCase() !== r.subject.toLowerCase()) resolved.push("“" + esc(r.subject) + "” resolves to <b>" + esc(r.subject_label) + "</b>");
    if (r.value_is_new) resolved.push("“" + esc(r.value) + "” is not in WONT yet — it would be added as a new class");
    else if (r.value_label && r.value_label.toLowerCase() !== r.value.toLowerCase()) resolved.push("“" + esc(r.value) + "” resolves to <b>" + esc(r.value_label) + "</b>");
    return '<article class="card ' + (d.v ? "dec-" + d.v : "") + '" id="' + r.id + '">' +
      '<div><div class="stmt">' + esc(r.subject) + ' <span class="pred">' + esc(r.predicate) + '</span> <span class="val">' + esc(r.value) + '</span></div>' +
      '<div class="meta">' + chipFor(r) + (r.already_in_wont ? '<span class="chip warn">already in WONT</span>' : '') +
        '<span>' + r.abstracts + ' abstract' + (r.abstracts === 1 ? '' : 's') + '</span>' +
        '<span class="pmids">' + r.pmids.slice(0, 8).map(function (p) { return '<a href="https://pubmed.ncbi.nlm.nih.gov/' + esc(p) + '/" target="_blank" rel="noopener">' + esc(p) + '</a>'; }).join("") + (r.pmids.length > 8 ? "…" : "") + '</span>' +
        (r.note ? '<span>reading: ' + esc(r.note) + '</span>' : '') + '</div>' +
      (resolved.length ? '<div class="res">' + resolved.join(" · ") + ' <code>' + esc((r.value_iri || "").split("/").pop()) + '</code></div>' : '') +
      '</div>' +
      '<div class="acts"><div class="row">' +
        '<button type="button" class="btn add" data-id="' + r.id + '" data-v="add" aria-pressed="' + (d.v === "add") + '">Add</button>' +
        '<button type="button" class="btn leave" data-id="' + r.id + '" data-v="leave" aria-pressed="' + (d.v === "leave") + '">Leave out</button></div>' +
        '<textarea id="note-' + r.id + '" data-id="' + r.id + '" placeholder="Note (optional)" aria-label="Note on this relation">' + esc(d.note || "") + '</textarea>' +
      '</div></article>';
  }
  var SECTIONS = [
    ["kind", "Specific to one kind of wound", "Statements that hold for this kind of wound, not for every wound."],
    ["wound", "On Wound itself", "Parts every wound has."],
    ["other", "Processes, dressings and other classes", "Relations on WONT classes outside the wound tree."]
  ];
  function groupsHTML(v) {
    var by = {}, order = [];
    v.forEach(function (r) { if (!by[r.subject_iri]) { by[r.subject_iri] = []; order.push(r.subject_iri); } by[r.subject_iri].push(r); });
    return order.map(function (iri) {
      var rs = by[iri], r0 = rs[0];
      return '<section class="group"><div class="ghead"><h2>' + esc(r0.subject_label || r0.subject) + '</h2><span class="iri">' + esc(iri.split("/").pop()) + '</span>' +
        '<details class="ax"><summary>its axioms in WONT (' + r0.existing_axioms.length + ')</summary><ul>' +
        r0.existing_axioms.map(function (a) { return "<li>" + esc(a) + "</li>"; }).join("") + '</ul></details></div>' +
        rs.map(card).join("") + '</section>';
    }).join("");
  }
  function render() {
    var v = visible(), html = "";
    var cs = CL.filter(clusterVisible);
    if (cs.length) html += '<h3 class="sec">Qualities every wound has</h3><p class="sec-lede">Asserted once on Wound, each is inherited by every kind of wound, so the per-class statements below it are not needed. Untick a term that does not name this quality.</p>' + cs.map(clusterCard).join("");
    SECTIONS.forEach(function (sec) {
      var rs = v.filter(function (r) { return r.section === sec[0]; });
      if (rs.length) html += '<h3 class="sec">' + sec[1] + '</h3><p class="sec-lede">' + sec[2] + '</p>' + groupsHTML(rs);
    });
    document.getElementById("list").innerHTML = html || '<p class="empty">Nothing matches these filters.</p>';
    counts();
  }
  function counts() {
    var a = 0, l = 0, ok = 0;
    ROWS.forEach(function (r) { var d = dec[r.id] && dec[r.id].v; if (d === "add") a++; if (d === "leave") l++; if (r.elk === "ok") ok++; });
    var single = ROWS.filter(function (r) { return r.section !== "cluster"; });
    a = 0; l = 0;
    single.forEach(function (r) { var d = dec[r.id] && dec[r.id].v; if (d === "add") a++; if (d === "leave") l++; });
    var cd = CL.filter(function (c) { return lift[c.id] && lift[c.id].v; }).length;
    document.getElementById("stats").innerHTML = '<span><b>' + cd + '/' + CL.length + '</b> wound qualities decided</span><span><b>' + a + '</b> relations added</span><span><b>' + l + '</b> left out</span><span><b>' + (single.length - a - l) + '</b> undecided</span><span><b>' + ok + '</b> of ' + ROWS.length + ' consistent under ELK</span>';
    document.getElementById("prog").style.width = ((a + l + cd) / (single.length + CL.length) * 100) + "%";
  }
  var queue = Promise.resolve();
  function persist(r, what) {
    var d = dec[r.id] || {};
    var body = { v: d.v || null, note: d.note || "", subject: r.subject, predicate: r.predicate, value: r.value,
                 subject_iri: r.subject_iri, value_iri: r.value_iri, when: new Date().toISOString() };
    dec[r.id] = body; counts();
    if (!db) { say("Not saved: the shared store is unavailable here. Reload the page to try again.", "bad"); return; }
    say("Saving…", "warn");
    queue = queue.then(function () { return db.doc("decision/" + r.id).set(body); })
      .then(function () {
        say("Saved — " + what + ".", "");
        var el = document.getElementById(r.id); if (el) { el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); }
      })
      .catch(function (e) { say("Not saved: " + why(e) + ". Your other decisions are safe.", "bad"); });
  }
  function persistLift(c, what) {
    var d = lift[c.id] || {};
    var body = { v: d.v || null, members: d.members || members(c), note: d.note || "", canonical: c.canonical, iri: c.iri, when: new Date().toISOString() };
    lift[c.id] = body; counts();
    if (!db) { say("Not saved: the shared store is unavailable here. Reload the page to try again.", "bad"); return; }
    say("Saving…", "warn");
    queue = queue.then(function () { return db.doc("lift/" + c.id).set(body); })
      .then(function () { say("Saved — " + what + ".", ""); var el = document.getElementById(c.id); if (el) { el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); } })
      .catch(function (e) { say("Not saved: " + why(e) + ". Your other decisions are safe.", "bad"); });
  }
  var byId = {}; ROWS.forEach(function (r) { byId[r.id] = r; });
  document.getElementById("list").addEventListener("click", function (e) {
    try {
      var tb = e.target.closest("button[data-term]");
      if (tb) {
        var c0 = CL.find(function (x) { return x.id === tb.dataset.c; }); if (!c0) return;
        var d0 = lift[c0.id] = JSON.parse(JSON.stringify(lift[c0.id] || {}));
        d0.members = members(c0); d0.members[tb.dataset.term] = !d0.members[tb.dataset.term];
        render(); persistLift(c0, (d0.members[tb.dataset.term] ? "put “" : "took “") + tb.dataset.term + (d0.members[tb.dataset.term] ? "” back into " : "” out of ") + c0.canonical);
        return;
      }
      var b = e.target.closest("button[data-v]"); if (!b) return;
      if (b.dataset.lift) {
        var c = CL.find(function (x) { return x.id === b.dataset.lift; }); if (!c) return;
        var dl = lift[c.id] = JSON.parse(JSON.stringify(lift[c.id] || {}));
        dl.members = members(c);
        dl.v = dl.v === b.dataset.v ? null : b.dataset.v;
        render(); persistLift(c, dl.v === "wound" ? "every wound has some " + c.canonical : dl.v === "leave" ? "left out " + c.canonical : "withdrew the decision on " + c.canonical);
        return;
      }
      var r = byId[b.dataset.id]; if (!r) return;
      var d = dec[r.id] = JSON.parse(JSON.stringify(dec[r.id] || {}));
      d.v = d.v === b.dataset.v ? null : b.dataset.v;
      render();
      persist(r, (d.v === "add" ? "added " : d.v === "leave" ? "left out " : "withdrew the decision on ") + "“" + r.subject + " " + r.predicate + " " + r.value + "”");
    } catch (err) { say("That click failed: " + why(err) + ". Nothing was saved.", "bad"); }
  });
  var timers = {};
  document.getElementById("list").addEventListener("input", function (e) {
    var t = e.target; if (t.tagName !== "TEXTAREA") return;
    if (t.dataset.lift) {
      var c = CL.find(function (x) { return x.id === t.dataset.lift; }); if (!c) return;
      var dl = lift[c.id] = JSON.parse(JSON.stringify(lift[c.id] || {}));
      dl.members = members(c); dl.note = t.value;
      clearTimeout(timers[c.id]);
      timers[c.id] = setTimeout(function () { persistLift(c, "note on " + c.canonical); }, 900);
      return;
    }
    var r = byId[t.dataset.id]; if (!r) return;
    var d = dec[r.id] = JSON.parse(JSON.stringify(dec[r.id] || {}));
    d.note = t.value;
    clearTimeout(timers[r.id]);
    timers[r.id] = setTimeout(function () { persist(r, "note on “" + r.subject + " " + r.predicate + " " + r.value + "”"); }, 900);
  });
  snapshot(); render();
  (window.claude && window.claude.use ? window.claude.use("db") : Promise.resolve(null)).then(function (store) {
    db = store;
    if (!db) { say("No shared store here — decisions cannot be saved from this view.", "bad"); return; }
    return Promise.all([load(1), loadLift(1)]).then(function (n) { snapshot(); render(); var t = n[0] + n[1]; say(t ? "Picked up " + t + " earlier decision" + (t === 1 ? "" : "s") + "." : "Ready.", ""); });
  }).catch(function (e) { say("Could not read earlier decisions (" + why(e) + "). They are still stored — reload the page.", "bad"); });
  function loadLift(attempt) {
    return db.collection("lift").limit(100).get().then(function (snap) {
      snap.docs.forEach(function (d) { lift[d.id] = JSON.parse(JSON.stringify(d.data())); });
      return snap.size;
    }, function (e) {
      if (attempt < 3) return new Promise(function (r) { setTimeout(r, 600 * attempt); }).then(function () { return loadLift(attempt + 1); });
      throw e;
    });
  }
  function load(attempt) {
    return db.collection("decision").limit(500).get().then(function (snap) {
      // stored documents come back read-only: keep copies (2026-10-02)
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
