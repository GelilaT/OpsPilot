// OpsPilot v2 diagrams. Writes v2_*.svg; render with ./render.sh
const fs = require("fs");
const path = require("path");
const L = require("./lib");
const { C, svg, text, label, box, arrow, actor, conn, node, uml, rel, sequence, stateNode, startDot, endDot } = L;
const P = (d, lab, o = {}) => L.path(d, lab, o);

// ---------- 1. Loop overview ----------
function loop() {
  const W = 1600, H = 690, w = 330, h = 140, X = [40, 430, 820, 1210];
  const T = { fill: C.bgTeal, stroke: C.teal }, A = { fill: C.bgAmber, stroke: C.amber }, N = { fill: C.bgNavy, stroke: C.navy };
  const o = { fs: 24, ss: 15, lh: 25 };
  let a = "", b = "";
  const top = [["1  Ingest", "POS sales · labour · cash-up", "supplier invoices · stock counts", T], ["2  Understand", "invoice classification + extraction", "deterministic validation · matching", A], ["3  Detect", "anomaly rules · price checks", "usage variance · margin drift", T], ["4  Investigate", "driver decomposition · hypotheses", "evidence chain · AI narrative", A]];
  const bot = [["8  Measure", "outcome vs counterfactual", "result stored in memory", N], ["7  Automate", "approval workflow", "PO · task · par · notify executors", N], ["6  Recommend", "purchase quantities · supplier switch", "repricing · par levels · staffing", N], ["5  Predict", "item × daypart demand forecast", "ingredient needs · stock-out risk", T]];
  top.forEach((t, i) => (b += box(X[i], 40, w, h, t[0], [t[1], t[2]], { ...o, ...t[3] })));
  bot.forEach((t, i) => (b += box(X[i], 450, w, h, t[0], [t[1], t[2]], { ...o, ...t[3] })));
  for (let i = 0; i < 3; i++) a += arrow(X[i] + w + 4, 110, X[i + 1] - 6, 110, "");
  for (let i = 3; i > 0; i--) a += arrow(X[i] - 4, 520, X[i - 1] + w + 6, 520, "");
  a += arrow(1375, 184, 1375, 444, "");
  b += box(540, 268, 520, 92, "Operational memory", ["past investigations · root causes · actions · outcomes"], { fs: 21, ss: 15, lh: 25, fill: C.bgPurple, stroke: C.purple });
  a += arrow(205, 446, 535, 345, "") + label(330, 400, "learn", { size: 15 });
  a += arrow(1065, 300, 1290, 186, "") + label(1190, 245, "recall similar cases", { size: 15 });
  const ly = 650;
  [["Deterministic core (owns every number)", C.teal, C.bgTeal], ["AI step + deterministic validation", C.amber, C.bgAmber], ["Workflow with human approval", C.navy, C.bgNavy]].forEach((l, i) => {
    const x = 160 + i * 460;
    b += `<rect x="${x}" y="${ly - 16}" width="22" height="22" rx="4" fill="${l[2]}" stroke="${l[1]}" stroke-width="2"/>` + text(x + 32, ly, l[0], { anchor: "start", size: 16, color: C.ink });
  });
  return svg(W, H, a + b);
}

// ---------- 2. Context ----------
function context() {
  const W = 1600, H = 900;
  let a = "", b = "";
  b += box(560, 330, 480, 240, "OpsPilot", ["Restaurant operations & margin platform", "Next.js web · FastAPI api · worker", "invoices · inventory · forecasts · margins", "investigations · Action Centre"], { fill: C.bgTeal, stroke: C.teal, fs: 28, ss: 15, lh: 24, sw: 3 });
  b += actor(120, 110, "Owner / GM") + actor(120, 380, "Head Chef") + actor(120, 640, "Shift Manager");
  a += arrow(185, 180, 555, 370, "approve actions, invoices, POs", { both: true, lx: 360, ly: 250 });
  a += arrow(185, 450, 555, 450, "recipes, stock counts, waste", { both: true });
  a += arrow(185, 710, 555, 530, "tasks, cash-up", { both: true, lx: 360, ly: 640 });
  b += box(640, 40, 320, 80, "Cloud Scheduler", ["dispatcher every 5 min"], { fill: C.bgGrey, stroke: C.slate });
  a += arrow(800, 122, 800, 325, "HTTPS + OIDC", { lx: 812, anchor: "start" });
  const ex = [["Google Gemini API", "classify · extract · narrate · embed", 110], ["Open-Meteo API", "weather forecast + history", 260], ["gov.uk Bank Holidays", "UK holiday calendar", 410], ["SendGrid (Resend fallback)", "briefs · alerts · approved POs", 560]];
  ex.forEach(([t, s, y]) => { b += box(1230, y, 330, 82, t, [s], { fill: C.bgAmber, stroke: C.amber, fs: 17 }); a += arrow(1045, 450, 1225, y + 41, "", { both: y < 500 }); });
  const bt = [["POS data", "simulator · CSV · adapter", 230, C.slate, true], ["Supplier invoices", "PDF / image upload", 560, C.slate, true], ["Neon PostgreSQL", "pgvector · job queue", 890, C.navy, false], ["Object storage", "invoice originals", 1220, C.navy, false]];
  bt.forEach(([t, s, x, col, dash]) => { b += box(x, 740, 290, 92, t, [s], { fill: dash ? C.bgGrey : C.bgNavy, stroke: col, dash, fs: 17 }); a += arrow(x + 145, 735, 800 + (x + 145 - 800) * 0.35, 575, "", { both: !dash }); });
  return svg(W, H, a + b);
}

// ---------- 3. Level-1 DFD ----------
function dfd() {
  const W = 1700, H = 1100;
  let a = "", b = "";
  const ent = (x, y, lab, w = 220) => { b += box(x, y, w, 58, lab, [], { rx: 0, fill: C.bgGrey, stroke: C.slate, fs: 15 }); return { cx: x + w / 2, cy: y + 29, shape: "rect", w, h: 58 }; };
  const proc = (cx, cy, n, l1, l2) => { b += `<circle cx="${cx}" cy="${cy}" r="64" fill="${C.bgTeal}" stroke="${C.teal}" stroke-width="2.5"/>` + text(cx, cy - 18, n, { size: 13, bold: true, color: C.teal }) + text(cx, cy + 4, l1, { size: 14.5, bold: true }) + text(cx, cy + 23, l2, { size: 14.5, bold: true }); return { cx, cy, shape: "circle", r: 64 }; };
  const store = (cx, cy, id, lab, w = 200) => { const h = 42, x = cx - w / 2, y = cy - h / 2; b += `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${C.bgBlue}"/><line x1="${x}" y1="${y}" x2="${x + w}" y2="${y}" stroke="${C.blue}" stroke-width="2"/><line x1="${x}" y1="${y + h}" x2="${x + w}" y2="${y + h}" stroke="${C.blue}" stroke-width="2"/><line x1="${x + 40}" y1="${y}" x2="${x + 40}" y2="${y + h}" stroke="${C.blue}" stroke-width="2"/>` + text(x + 20, cy + 5, id, { size: 13, bold: true, color: C.blue }) + text(x + 40 + (w - 40) / 2, cy + 5, lab, { size: 13 }); return { cx, cy, shape: "rect", w, h }; };
  const E1 = ent(40, 40, "POS / CSV export"), E2 = ent(340, 40, "Supplier invoices"), G1 = ent(640, 40, "Gemini API"), E3 = ent(1070, 40, "Weather + bank holidays"), E4 = ent(1410, 470, "Cloud Scheduler");
  const MG = ent(40, 620, "Owner / GM / Chef"), G2 = ent(840, 1000, "Gemini API"), SG = ent(1410, 1000, "SendGrid");
  const P1 = proc(150, 230, "1.0", "Ingest", "sales"), P2 = proc(450, 230, "2.0", "Process", "invoices"), P3 = proc(750, 230, "3.0", "Maintain", "inventory"), P4 = proc(1180, 230, "4.0", "Forecast", "demand"), P5 = proc(1520, 230, "5.0", "Plan", "procurement");
  const P6 = proc(450, 650, "6.0", "Analyse", "margins"), P7 = proc(800, 650, "7.0", "Detect &", "investigate"), P8 = proc(1180, 650, "8.0", "Action", "Centre"), P9 = proc(1520, 650, "9.0", "Brief &", "notify");
  const D1 = store(150, 420, "D1", "Sales & labour"), D2 = store(450, 420, "D2", "Invoices & prices"), D3 = store(750, 420, "D3", "Stock ledger"), D5 = store(965, 420, "D5", "Recipes"), D4 = store(1180, 420, "D4", "Forecasts");
  const D6 = store(600, 850, "D6", "Investigations & memory", 250), D7 = store(1180, 850, "D7", "Recommendations", 220);
  a += conn(E1, P1, "orders, shifts, cash-ups", { lx: 160, ly: 130, anchor: "start" });
  a += conn(P1, D1, "");
  a += conn(E2, P2, "PDF / image", { lx: 460, ly: 140, anchor: "start" });
  a += conn(P2, G1, "classify · extract", { both: true, lx: 640, ly: 160 });
  a += conn(P2, D2, "validated lines");
  a += conn(P2, D3, "goods received", { lx: 640, ly: 330 });
  a += conn(D1, P3, "sales × recipes", { lx: 330, ly: 330 });
  a += conn(P3, D3, "movements", { both: true, lx: 790, ly: 345, anchor: "start" });
  a += conn(D5, P3, "recipes", { lx: 880, ly: 315 });
  a += conn(E3, P4, "", {});
  a += P("M245,410 Q700,330 1120,255", "sales history", { lx: 1010, ly: 295 });
  a += conn(P4, D4, "item × daypart");
  a += conn(D4, P5, "ingredient needs", { lx: 1420, ly: 330 });
  a += conn(D3, P5, "on hand", { lx: 1270, ly: 312 });
  a += conn(P5, P8, "draft POs", { lx: 1390, ly: 450 });
  a += conn(E4, P5, "nightly", { lx: 1530, ly: 380, anchor: "start" });
  a += conn(E4, P9, "07:00", { lx: 1530, ly: 565, anchor: "start" });
  a += conn(D2, P6, "costs", { lx: 460, ly: 540, anchor: "start" });
  a += conn(D5, P6, "recipes", { lx: 720, ly: 520 });
  a += conn(D1, P6, "item sales", { lx: 270, ly: 540 });
  a += conn(P6, P7, "margin facts");
  a += conn(D3, P7, "stock, usage", { lx: 790, ly: 540, anchor: "start" });
  a += conn(P7, D6, "evidence chains", { both: true, lx: 620, ly: 760 });
  a += conn(P7, G2, "narrate · embed", { both: true, lx: 905, ly: 860, anchor: "start" });
  a += conn(P7, P8, "recommendations");
  a += conn(P8, D7, "", { both: true });
  a += conn(D7, P9, "results", { lx: 1380, ly: 760 });
  a += conn(P9, SG, "emails", { lx: 1530, ly: 930, anchor: "start" });
  a += conn(MG, P2, "upload · review", { lx: 300, ly: 470 });
  a += P("M150,682 C150,975 1000,975 1120,688", "approve / reject", { lx: 400, ly: 905 });
  return svg(W, H, a + b);
}

// ---------- 4. Component ----------
function component() {
  const W = 1800, H = 1100;
  let a = "", b = "";
  b += `<rect x="30" y="20" width="1200" height="230" rx="14" fill="none" stroke="${C.navy}" stroke-width="2" stroke-dasharray="10 6"/>` + text(48, 48, "«Cloud Run» web - Next.js 15 · TypeScript · Tailwind · Recharts", { anchor: "start", size: 17, bold: true, color: C.navy });
  ["Dashboard", "Action Centre", "Invoices", "Inventory & POs", "Menu & Margins", "Investigations", "Ask OpsPilot"].forEach((s, i) => (b += box(50 + i * 162, 66, 150, 66, s, [], { fs: 14.5 })));
  b += box(50, 158, 330, 64, "Better Auth", ["sessions · roles · JWT + JWKS"], { fill: C.white, fs: 16 });
  b += box(400, 158, 400, 64, "Typed API client", ["generated from the FastAPI OpenAPI schema"], { fill: C.white, fs: 16 });
  a += arrow(630, 252, 630, 298, "HTTPS · REST /api/v1 · Bearer JWT", { lx: 645, ly: 280, anchor: "start" });
  b += `<rect x="30" y="300" width="1200" height="600" rx="14" fill="none" stroke="${C.teal}" stroke-width="2" stroke-dasharray="10 6"/>` + text(48, 328, "«Cloud Run» api - FastAPI · Pydantic v2 · SQLAlchemy 2 (async) · Alembic", { anchor: "start", size: 17, bold: true, color: C.teal });
  ["/invoices", "/suppliers", "/inventory", "/forecasts", "/procurement", "/menu", "/investigations", "/actions", "/chat", "/internal"].forEach((s, i) => (b += box(45 + i * 117, 345, 110, 48, s, [], { fs: 13, fill: C.bgGrey, stroke: C.slate })));
  b += text(48, 425, "DOMAIN (bounded contexts, pure Python)", { anchor: "start", size: 15, bold: true, color: C.teal });
  [["Sales & Labour", "metrics · cash-up"], ["Purchasing", "invoices · suppliers · POs"], ["Inventory", "stock ledger · variance"], ["Forecasting", "demand · backtests"], ["Menu & Margin", "recipe costing · matrix"], ["Intelligence", "anomalies · RCA · memory"], ["Action Centre", "recommendations · outcomes"], ["Briefing & Chat", "FactSheet · Number Guard"]]
    .forEach((s, i) => (b += box(45 + (i % 4) * 295, 440 + Math.floor(i / 4) * 105, 280, 90, s[0], [s[1]], { fill: C.bgTeal, stroke: C.teal, fs: 17 })));
  b += text(48, 668, "PORTS & ADAPTERS (adapter chosen per organisation/site via IntegrationConnection)", { anchor: "start", size: 15, bold: true, color: C.teal });
  [["AIPort", "Gemini"], ["PosPort", "simulator · CSV"], ["AccountingPort", "CSV export"], ["MailPort", "SendGrid · Resend"], ["WeatherPort", "Open-Meteo"], ["CalendarPort", "gov.uk"], ["StoragePort", "GCS · local"], ["Repositories", "SQLAlchemy"]].forEach((s, i) => (b += box(45 + i * 148, 684, 140, 70, s[0], [s[1]], { fill: C.white, stroke: C.teal, fs: 14, ss: 12.5 })));
  b += text(630, 800, "RFC 7807 errors · Idempotency-Key on POST · cursor pagination · request-id logging · append-only audit_event", { size: 14, color: C.slate });
  b += text(630, 830, "Layering rule: api → domain services → ports; domain never imports FastAPI, SQLAlchemy sessions or SDKs", { size: 14, italic: true, color: C.slate });
  b += `<rect x="1290" y="300" width="480" height="600" rx="14" fill="none" stroke="${C.purple}" stroke-width="2" stroke-dasharray="10 6"/>` + text(1305, 328, "«Cloud Run» worker - Procrastinate", { anchor: "start", size: 17, bold: true, color: C.purple });
  [["Invoice pipeline", "classify → extract → validate → match"], ["Nightly intelligence", "metrics → forecast → procurement →", "margins → detect → investigate"], ["Outcome evaluator", "measures executed actions"], ["Outbox relay", "events · emails · retries · DLQ"]]
    .forEach((s, i) => (b += box(1310, 350 + i * 125, 440, 108, s[0], s.slice(1), { fill: C.bgPurple, stroke: C.purple, fs: 17 })));
  b += text(1530, 880, "same image · shares domain + ports packages", { size: 13, italic: true, color: C.slate });
  a += arrow(1232, 405, 1286, 405, "", { teal: true }) + label(1259, 395, "enqueue", { size: 12 });
  b += box(1290, 20, 480, 90, "Cloud Scheduler", ["POST /internal/dispatch every 5 min (OIDC)"], { fill: C.bgGrey, stroke: C.slate });
  a += arrow(1530, 112, 1530, 296, "", { teal: true });
  b += box(150, 960, 640, 100, "Neon PostgreSQL + pgvector", ["OLTP · stock ledger · job queue · outbox · embeddings"], { fill: C.bgNavy, stroke: C.navy, fs: 19 });
  b += box(830, 960, 380, 100, "Object storage (GCS)", ["invoice originals · signed URLs"], { fill: C.bgNavy, stroke: C.navy, fs: 19 });
  a += arrow(470, 902, 470, 956, "", { both: true }) + arrow(1020, 902, 1020, 956, "");
  a += P("M1400,902 V932 H700 V956", "") ;
  [["Gemini", 1290, 960], ["Open-Meteo", 1535, 960], ["gov.uk holidays", 1290, 1015], ["SendGrid", 1535, 1015]].forEach(([t, x, y]) => (b += box(x, y, 235, 45, t, [], { fill: C.bgAmber, stroke: C.amber, fs: 15 })));
  a += arrow(1650, 902, 1650, 956, "") + label(1700, 935, "via ports", { size: 12 });
  return svg(W, H, a + b);
}

// ---------- 5. Deployment ----------
function deployment() {
  const W = 1600, H = 920;
  const nd = (x, y, w, h, t, o = {}) => { const f = o.fill || C.bgBlue, st = o.stroke || C.blue; return `<path d="M${x},${y} l14,-14 h${w} v${h} l-14,14 z" fill="${f}" stroke="${st}" stroke-width="2"/><line x1="${x + w}" y1="${y}" x2="${x + w + 14}" y2="${y - 14}" stroke="${st}" stroke-width="2"/><rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${f}" stroke="${st}" stroke-width="2"/>` + text(x + 14, y + 28, t, { anchor: "start", size: 16, bold: true, color: st }); };
  const art = (x, y, w, t, sub) => box(x, y, w, sub ? 60 : 42, t, sub ? [sub] : [], { fill: C.white, stroke: C.slate, fs: 14, rx: 4 });
  let b = "", a = "";
  b += nd(30, 330, 260, 170, "«device» Browser");
  b += art(50, 380, 220, "Next.js client", "desktop · tablet · phone");
  b += art(50, 450, 220, "Session cookie (HTTP-only)");
  b += nd(360, 40, 760, 700, "«cloud» Google Cloud project (europe-west2)");
  b += nd(385, 95, 220, 270, "«service» web", { fill: C.bgNavy, stroke: C.navy });
  b += art(400, 145, 190, "Next.js standalone", "Node 20 · :8080");
  b += art(400, 215, 190, "Better Auth", "JWT issuer · /jwks");
  b += art(400, 285, 190, "min 0 · max 2");
  b += nd(635, 95, 220, 270, "«service» api", { fill: C.bgTeal, stroke: C.teal });
  b += art(650, 145, 190, "FastAPI · uvicorn", "Python 3.12 · :8080");
  b += art(650, 215, 190, "JWKS verifier", "role guards");
  b += art(650, 285, 190, "min 0 · max 3");
  b += nd(885, 95, 210, 270, "«service» worker", { fill: C.bgPurple, stroke: C.purple });
  b += art(900, 145, 180, "Procrastinate", "same image");
  b += art(900, 215, 180, "/internal/dispatch", "OIDC only");
  b += art(900, 285, 180, "max 1 · 1 GiB");
  b += art(385, 420, 220, "Cloud Scheduler", "1 job · */5 min");
  b += art(635, 420, 220, "Secret Manager", "API keys · DB URL");
  b += art(885, 420, 210, "Artifact Registry", "2 images");
  b += art(385, 510, 470, "Cloud Storage bucket", "invoice originals · private · signed URLs (10 min)");
  b += art(885, 510, 210, "Cloud Logging", "JSON logs · request id");
  b += art(385, 600, 710, "Service accounts", "api-sa (storage, secrets) · worker-sa · scheduler-invoker (OIDC)");
  b += nd(1190, 40, 380, 150, "«cloud» Neon (eu-west-2)", { fill: C.bgNavy, stroke: C.navy });
  b += art(1210, 90, 340, "PostgreSQL 16 + pgvector", "pooled TLS · Alembic migrations");
  [["Gemini API", 260], ["Open-Meteo", 370], ["gov.uk Bank Holidays", 480], ["SendGrid", 590]].forEach(([t, y]) => (b += nd(1190, y, 380, 70, "«external» " + t, { fill: C.bgAmber, stroke: C.amber })));
  b += nd(360, 790, 760, 110, "«cloud» GitHub", { fill: C.bgGrey, stroke: C.slate });
  b += art(385, 835, 360, "Actions CI", "ruff · pyright · pytest · eslint · build · deploy");
  b += art(765, 835, 330, "Fallback cron workflow", "X-Cron-Secret");
  a += arrow(295, 410, 380, 250, "HTTPS", { both: true, lx: 330, ly: 315 });
  a += arrow(608, 230, 630, 230, "", { teal: true });
  a += arrow(858, 260, 880, 260, "");
  a += arrow(495, 416, 940, 372, "", { teal: true }) + label(700, 400, "OIDC", { size: 12 });
  a += arrow(1112, 150, 1185, 120, "TLS", { lx: 1150, ly: 128 });
  a += arrow(1112, 300, 1185, 295, "") + arrow(1112, 320, 1185, 405, "") + arrow(1112, 340, 1185, 515, "") + arrow(1112, 355, 1185, 620, "");
  a += label(1150, 470, "HTTPS", { size: 12 });
  a += arrow(560, 830, 560, 752, "deploy", { lx: 570, ly: 790, anchor: "start" });
  a += arrow(930, 830, 930, 752, "fallback trigger", { dash: true, lx: 940, ly: 790, anchor: "start" });
  return svg(W, H, b + a);
}

// ---------- 6. Access control ----------
function access() {
  const roles = ["Owner", "GM", "Head Chef", "Shift Mgr", "Service"];
  const res = [
    ["Dashboard, briefs, investigations (read)", "✓✓✓✓✗"], ["Upload invoices, fix extraction, map lines", "✓✓✓✗✗"], ["Approve invoice (any value / with exceptions)", "✓✓✗✗✗"],
    ["Approve invoice (clean, under limit)", "✓✓✓✗✗"], ["Stock counts and waste logging", "✓✓✓✓✗"], ["Recipes, catalogue, par levels", "✓✓✓✗✗"],
    ["Approve purchase orders", "✓✓✓*✗✗"], ["Approve recommendations (pricing, supplier switch)", "✓✓✗✗✗"], ["Tasks: acknowledge / resolve", "✓✓✓✓✗"],
    ["Settings, thresholds, users", "✓✗✗✗✗"], ["Audit log", "✓✓✗✗✗"], ["/internal/* (dispatch, workers)", "✗✗✗✗✓"],
  ];
  const W = 1500, x0 = 30, y0 = 20, cw0 = 640, cw = 160, rh = 50, H = y0 + rh * (res.length + 1) + 80;
  let b = `<rect x="${x0}" y="${y0}" width="${cw0 + cw * 5}" height="${rh}" fill="${C.blue}"/>` + text(x0 + 16, y0 + 32, "Resource / action", { anchor: "start", size: 17, bold: true, color: C.white });
  roles.forEach((r, i) => (b += text(x0 + cw0 + cw * i + cw / 2, y0 + 32, r, { size: 17, bold: true, color: C.white })));
  res.forEach((r, j) => {
    const y = y0 + rh * (j + 1);
    b += `<rect x="${x0}" y="${y}" width="${cw0 + cw * 5}" height="${rh}" fill="${j % 2 ? "#E9EEF8" : C.bgBlue}" stroke="#FFFFFF" stroke-width="2"/>` + text(x0 + 16, y + 31, r[0], { anchor: "start", size: 16 });
    const marks = r[1].match(/✓\*|✓|✗/g);
    marks.forEach((v, i) => (b += text(x0 + cw0 + cw * i + cw / 2, y + 34, v, { size: 22, bold: true, color: v.startsWith("✓") ? C.green : C.red })));
  });
  b += text(x0, H - 40, "* Head Chef may approve POs up to the site's PO limit. All checks are enforced in FastAPI dependencies; the UI only hides controls.", { anchor: "start", size: 15, color: C.slate });
  return svg(W, H, b);
}

// ---------- 7. Class diagrams ----------
function classSales() {
  const W = 1810, H = 620, cw = 232, X = [30, 280, 530, 780, 1030, 1280, 1545];
  const k = {};
  const add = (id, col, y, at, op) => (k[id] = uml(X[col], y, cw, id, at, op || []));
  add("Site", 0, 20, ["-id : UUID", "-organisation_id : UUID", "-name : str", "-timezone : str", "-currency : CurrencyCode", "-lat, lng : float"]);
  add("Order", 1, 20, ["-id : UUID", "-external_id : str", "-opened_at : datetime", "-covers : int", "-till_id : str"], ["+net_minor() : int"]);
  add("OrderLine", 2, 20, ["-order_id : UUID", "-menu_item_id : UUID", "-qty : int", "-price_minor : int"]);
  add("MenuItem", 3, 20, ["-id : UUID", "-name : str", "-category : str", "-price_minor : int", "-active : bool"], ["+current_cost() : Money"]);
  add("Recipe", 4, 20, ["-id : UUID", "-menu_item_id : UUID", "-version : int", "-yield_portions : int", "-effective_from : date"], ["+cost_at(date) : Money"]);
  add("RecipeLine", 5, 20, ["-recipe_id : UUID", "-ingredient_id : UUID", "-qty : Decimal", "-uom : Uom", "-waste_factor : Decimal"]);
  add("Ingredient", 6, 20, ["-id : UUID", "-name : str", "-base_uom : Uom", "-category : str", "-shelf_life_days : int"]);
  add("Employee", 0, 330, ["-id : UUID", "-first_name : str", "-last_initial : str", "-role : str", "-rate_minor : int"]);
  add("Shift", 1, 330, ["-employee_id : UUID", "-start : datetime", "-end : datetime", "-scheduled : bool"], ["+hours() : Decimal"]);
  add("Discount", 2, 330, ["-order_id : UUID", "-amount_minor : int", "-reason : str", "-manager_id : UUID"]);
  add("Void", 4, 330, ["-order_id : UUID", "-value_minor : int", "-reason : str", "-manager_id : UUID"]);
  add("CashUp", 5, 330, ["-date : date", "-till_id : str", "-expected_minor : int", "-counted_minor : int"], ["+variance_minor() : int"]);
  add("DailyMetrics", 6, 330, ["-site_id : UUID", "-date : date", "-kpis : KpiSet", "-by_daypart : dict", "-by_item : dict"]);
  add("MenuItemCostSnapshot", 3, 330, ["-menu_item_id : UUID", "-date : date", "-cost_minor : int", "-gp_pct : Decimal", "-cm_minor : int"]);
  let r = "";
  r += rel(k.Order, k.OrderLine, { start: "dia", m2: "1..*" });
  r += rel(k.OrderLine, k.MenuItem, { m1: "*", m2: "1" });
  r += rel(k.MenuItem, k.Recipe, { m1: "1", m2: "1..*" });
  r += rel(k.Recipe, k.RecipeLine, { start: "dia", m2: "1..*" });
  r += rel(k.RecipeLine, k.Ingredient, { m1: "*", m2: "1" });
  r += rel(k.Site, k.Order, { m1: "1", m2: "*" });
  r += rel(k.Site, k.Employee, { m1: "1", m2: "*" });
  r += rel(k.Employee, k.Shift, { m1: "1", m2: "*" });
  r += rel(k.Order, k.Discount, { m1: "1", m2: "*" });
  r += rel(k.MenuItem, k.MenuItemCostSnapshot, { m1: "1", m2: "*" });
  let b = ""; Object.values(k).forEach((n) => (b += n.svg));
  b += text(30, 595, "All operational tables carry organisation_id, site_id and created_at; money is integer minor units + ISO 4217 currency; quantities are Decimal with an explicit unit of measure. Void, like Discount, belongs to Order.", { anchor: "start", size: 13.5, italic: true, color: C.slate });
  return svg(W, H, r + b);
}
function classPurchasing() {
  const W = 1810, H = 900, cw = 232, X = [30, 280, 530, 780, 1030, 1280, 1545];
  const k = {};
  const add = (id, col, y, at, op, o) => (k[id] = uml(X[col], y, cw, id, at, op || [], o));
  add("Supplier", 0, 20, ["-id : UUID", "-name : str", "-vat_number : str", "-lead_time_days : int", "-order_days : list"]);
  add("SupplierProduct", 1, 20, ["-supplier_id : UUID", "-ingredient_id : UUID", "-sku : str", "-pack_qty : Decimal", "-pack_uom : Uom", "-moq_packs : int"]);
  add("PriceObservation", 2, 20, ["-supplier_product_id : UUID", "-observed_on : date", "-unit_price_minor : int", "-per_base_uom_minor : Decimal", "-source_line_id : UUID"]);
  add("LineAlias", 3, 20, ["-supplier_id : UUID", "-raw_text_norm : str", "-supplier_product_id : UUID", "-confirmed_by : UUID"]);
  add("InvoiceDocument", 4, 20, ["-id : UUID", "-sha256 : str", "-storage_key : str", "-mime : str", "-state : IntakeState", "-doc_type : DocumentType", "-confidence : Decimal"], ["+transition(to, reason)"]);
  add("Invoice", 5, 20, ["-id : UUID", "-supplier_id : UUID", "-number : str", "-invoice_date : date", "-subtotal_minor : int", "-vat_minor : int", "-status : InvoiceStatus"], ["+recompute_totals()", "+approve(user)"]);
  add("InvoiceLine", 6, 20, ["-invoice_id : UUID", "-raw_description : str", "-qty : Decimal", "-uom : Uom", "-unit_price_minor : int", "-line_total_minor : int", "-match_confidence : Decimal"]);
  add("InvoiceException", 6, 400, ["-invoice_id : UUID", "-line_id : UUID?", "-code : ExceptionCode", "-severity : Severity", "-facts : dict", "-resolved_by : UUID?"]);
  add("PurchaseOrder", 0, 420, ["-id : UUID", "-supplier_id : UUID", "-status : POStatus", "-delivery_date : date", "-total_minor : int", "-recommendation_id : UUID?"], ["+approve(user)", "+mark_sent()"]);
  add("PurchaseOrderLine", 1, 420, ["-po_id : UUID", "-supplier_product_id : UUID", "-packs : int", "-expected_price_minor : int"]);
  add("GoodsReceipt", 2, 420, ["-po_id : UUID?", "-invoice_id : UUID?", "-received_on : date", "-lines : list"]);
  add("StockMovement", 3, 420, ["-ingredient_id : UUID", "-at : datetime", "-type : MovementType", "-qty_base : Decimal", "-cost_minor : int", "-ref_type, ref_id"]);
  add("StockCount", 4, 420, ["-id : UUID", "-counted_at : datetime", "-counted_by : UUID", "-status : CountStatus"], ["+post()"]);
  add("StockCountLine", 5, 420, ["-count_id : UUID", "-ingredient_id : UUID", "-qty_base : Decimal"]);
  add("WasteRecord", 3, 700, ["-ingredient_id : UUID", "-qty_base : Decimal", "-reason : WasteReason", "-recorded_by : UUID"]);
  add("ParLevel", 4, 700, ["-ingredient_id : UUID", "-min_base : Decimal", "-max_base : Decimal", "-source : manual|recommended"]);
  let r = "";
  r += rel(k.Supplier, k.SupplierProduct, { m1: "1", m2: "*" });
  r += rel(k.SupplierProduct, k.PriceObservation, { m1: "1", m2: "*" });
  r += rel(k.InvoiceDocument, k.Invoice, { m1: "1", m2: "0..1" });
  r += rel(k.Invoice, k.InvoiceLine, { start: "dia" });
  r += rel(k.InvoiceLine, k.InvoiceException, { m1: "1", m2: "*" });
  r += rel(k.PurchaseOrder, k.PurchaseOrderLine, { start: "dia", m2: "1..*" });
  r += rel(k.PurchaseOrderLine, k.GoodsReceipt, {});
  r += rel(k.GoodsReceipt, k.StockMovement, {});
  r += rel(k.StockCount, k.StockCountLine, { start: "dia", m2: "*" });
  r += rel(k.StockMovement, k.StockCount, {});
  r += rel(k.WasteRecord, k.StockMovement, { lab: "waste" });
  r += rel(k.Supplier, k.PurchaseOrder, { m1: "1", m2: "*" });
  let b = ""; Object.values(k).forEach((n) => (b += n.svg));
  b += text(30, 875, "Stock is never a mutable balance: on-hand = Σ StockMovement.qty_base. Goods receipts, counts (adjustments) and waste all post movements. LineAlias maps raw invoice text to a SupplierProduct once a manager confirms it.", { anchor: "start", size: 13.5, italic: true, color: C.slate });
  return svg(W, H, r + b);
}
function classIntel() {
  const W = 1810, H = 760, cw = 232, X = [30, 280, 530, 780, 1030, 1280, 1545];
  const k = {};
  const add = (id, col, y, at, op, o) => (k[id] = uml(X[col], y, cw, id, at, op || [], o));
  add("ForecastRun", 0, 20, ["-id : UUID", "-model_version : str", "-trained_through : date", "-wape : Decimal", "-bias : Decimal"]);
  add("ForecastValue", 1, 20, ["-run_id : UUID", "-menu_item_id : UUID", "-date : date", "-daypart : Daypart", "-p50 : Decimal", "-p10, p90 : Decimal", "-drivers : dict"]);
  add("Anomaly", 2, 20, ["-id : UUID", "-detector : str", "-severity : Severity", "-subject : EntityRef", "-observed : Decimal", "-expected : Decimal", "-fingerprint : str"]);
  add("Investigation", 3, 20, ["-id : UUID", "-anomaly_id : UUID", "-status : InvStatus", "-finding : str", "-confidence : Decimal", "-graph : dict"], ["+top_cause()"]);
  add("EvidenceNode", 4, 20, ["-investigation_id : UUID", "-kind : EvidenceKind", "-claim_template : str", "-facts : dict", "-verdict : supports|refutes|neutral", "-weight : Decimal"]);
  add("CauseCandidate", 5, 20, ["-investigation_id : UUID", "-cause_code : CauseCode", "-confidence : Decimal", "-evidence_ids : list"]);
  add("MemoryEntry", 6, 20, ["-id : UUID", "-subjects : list[EntityRef]", "-cause_code : CauseCode", "-summary : str", "-outcome : Outcome?", "-embedding : vector(768)"]);
  add("Recommendation", 2, 420, ["-id : UUID", "-type : RecType", "-status : RecStatus", "-expected_impact_minor : int", "-risk : Risk", "-evidence_ref : UUID", "-expires_at : datetime"], ["+transition(to, actor)"]);
  add("Approval", 3, 420, ["-recommendation_id : UUID", "-decided_by : UUID", "-decision : approve|reject", "-note : str", "-at : datetime"]);
  add("ActionExecution", 4, 420, ["-recommendation_id : UUID", "-executor : str", "-idempotency_key : str", "-status : ExecStatus", "-result_ref : EntityRef"]);
  add("OutcomeMeasurement", 5, 420, ["-recommendation_id : UUID", "-metric : str", "-baseline : Decimal", "-actual : Decimal", "-effect : Decimal", "-verdict : Outcome"]);
  add("Task", 1, 420, ["-id : UUID", "-title : str", "-state : TaskState", "-assignee_id : UUID", "-due_at : datetime"]);
  add("AuditEvent", 6, 420, ["-id : bigint", "-actor : str", "-entity : EntityRef", "-action : str", "-before, after : dict", "-at : datetime"]);
  add("Job", 0, 420, ["-id : bigint", "-task_name : str", "-args : dict", "-status : str", "-attempts : int", "-lock : str"]);
  let r = "";
  r += rel(k.ForecastRun, k.ForecastValue, { start: "dia", m2: "*" });
  r += rel(k.Anomaly, k.Investigation, { m1: "1", m2: "0..1" });
  r += rel(k.Investigation, k.EvidenceNode, { start: "dia", m2: "1..*" });
  r += rel(k.EvidenceNode, k.CauseCandidate, {});
  r += rel(k.CauseCandidate, k.MemoryEntry, {});
  r += rel(k.Investigation, k.Recommendation, { m1: "1", m2: "*" });
  r += rel(k.Recommendation, k.Approval, { m1: "1", m2: "0..*" });
  r += rel(k.Approval, k.ActionExecution, {});
  r += rel(k.ActionExecution, k.OutcomeMeasurement, {});
  r += rel(k.Recommendation, k.Task, {});
  r += rel(k.OutcomeMeasurement, k.MemoryEntry, { lab: "written back", via: [1560, 380] });
  let b = ""; Object.values(k).forEach((n) => (b += n.svg));
  b += text(30, 735, "Investigations never store free AI text as facts: EvidenceNode.facts holds computed values; claims are templates rendered from those facts.", { anchor: "start", size: 13.5, italic: true, color: C.slate });
  return svg(W, H, r + b);
}
function classServices() {
  const W = 1840, H = 1030;
  const k = {};
  const add = (id, x, y, w, at, op, o) => (k[id] = uml(x, y, w, id, at, op, o));
  const T = { fill: C.bgTeal, stroke: C.teal }, A = { fill: C.bgAmber, stroke: C.amber }, Pp = { fill: C.bgPurple, stroke: C.purple };
  add("InvoicePipeline", 30, 30, 330, ["-ai : AIPort", "-storage : StoragePort"], ["+run(document_id) : IntakeState"], Pp);
  add("NightlyPipeline", 400, 30, 330, ["-site_id : UUID"], ["+run(date) : PipelineReport"], Pp);
  add("RecommendationService", 770, 30, 360, ["-executors : dict[RecType, Executor]"], ["+propose(rec)", "+decide(id, user, decision)", "+execute(id)"], Pp);
  add("OutcomeEvaluator", 1170, 30, 320, [], ["+due(now) : list[Rec]", "+measure(rec) : Outcome"], Pp);
  add("MemoryService", 1530, 30, 290, ["-ai : AIPort"], ["+remember(inv)", "+recall(query) : list"], Pp);
  add("ExtractionValidator", 30, 300, 330, [], ["+validate(extraction) : list[Issue]"]);
  add("SupplierMatcher", 30, 440, 330, [], ["+match(header) : Match"]);
  add("LineMatcher", 30, 580, 330, [], ["+match(line, supplier) : Match"]);
  add("PriceAnalyzer", 30, 720, 330, [], ["+check(line) : list[Exception]"]);
  add("DuplicateDetector", 30, 860, 330, [], ["+find(invoice) : list[Invoice]"]);
  add("InventoryLedger", 400, 300, 330, [], ["+on_hand(ingredient, at)", "+post(movements)"]);
  add("VarianceAnalyzer", 400, 450, 330, [], ["+usage_variance(period)"]);
  add("ForecastEngine", 400, 590, 330, ["-model_version : str"], ["+fit(site)", "+predict(dates) : ForecastRun", "+backtest() : Metrics"]);
  add("ProcurementPlanner", 400, 790, 330, [], ["+recommend(site, date) : list[POLine]"]);
  add("MarginEngine", 770, 300, 360, [], ["+cost_items(date)", "+engineering_matrix(period)"]);
  add("AnomalyEngine", 770, 450, 360, ["-detectors : list[Detector]"], ["+run(date) : list[Anomaly]"]);
  add("InvestigationEngine", 770, 600, 360, ["-tests : list[HypothesisTest]"], ["+investigate(anomaly) : Investigation"]);
  add("HypothesisTest", 770, 790, 360, ["+cause_code : CauseCode"], ["+evaluate(ctx) : list[EvidenceNode]"], { stereo: "«interface»" });
  add("NumberGuard", 1170, 300, 320, [], ["+check(text, facts) : GuardResult"], A);
  add("AIPort", 1170, 450, 320, [], ["+classify(doc)", "+extract(doc, schema)", "+narrate(facts, schema)", "+embed(text)"], { stereo: "«interface»", ...A });
  add("GeminiAdapter", 1170, 690, 320, ["-model : str"], ["(implements AIPort)"], A);
  add("Executor", 1530, 300, 290, [], ["+execute(rec, key) : Result"], { stereo: "«interface»" });
  add("CreatePOExecutor", 1530, 470, 290, [], ["draft PO"], { fill: C.white });
  add("ParLevelExecutor", 1530, 570, 290, [], ["update par"], { fill: C.white });
  add("TaskExecutor", 1530, 670, 290, [], ["price review / task"], { fill: C.white });
  let r = "";
  const dep = (a2, b2, o = {}) => (r += rel(k[a2], k[b2], { dash: true, end: "open", ...o }));
  dep("InvoicePipeline", "ExtractionValidator"); dep("NightlyPipeline", "InventoryLedger"); dep("NightlyPipeline", "MarginEngine");
  dep("RecommendationService", "Executor", { via: [1500, 200] }); dep("InvestigationEngine", "NumberGuard"); dep("InvestigationEngine", "AIPort");
  dep("OutcomeEvaluator", "MemoryService", {}); dep("ProcurementPlanner", "ForecastEngine"); dep("AnomalyEngine", "InvestigationEngine");
  r += rel(k.InvestigationEngine, k.HypothesisTest, { start: "dia", m2: "1..*" });
  r += rel(k.GeminiAdapter, k.AIPort, { dash: true, end: "tri" });
  r += rel(k.CreatePOExecutor, k.Executor, { dash: true, end: "tri" });
  r += `<path d="M1530,605 H1505" fill="none" stroke="${C.line}" stroke-width="1.6" stroke-dasharray="7 5"/><path d="M1530,705 H1505 V380 H1526" fill="none" stroke="${C.line}" stroke-width="1.6" stroke-dasharray="7 5" marker-end="url(#tri)"/>`;
  let b = ""; Object.values(k).forEach((n) => (b += n.svg));
  b += text(30, 1010, "Purple: orchestration (worker jobs) · teal/blue: deterministic domain services · amber: AI boundary. InvoicePipeline also calls SupplierMatcher, LineMatcher, PriceAnalyzer and DuplicateDetector in order.", { anchor: "start", size: 13.5, italic: true, color: C.slate });
  return svg(W, H, r + b);
}

// ---------- 8. Sequences ----------
function seqAuth() {
  return sequence(["Manager", "web (Next.js)", "Better Auth", "api (FastAPI)", "PostgreSQL"], [], [
    [0, 1, "1. sign in (email + password)"], [1, 2, "2. signIn.email()"], [2, 4, "3. verify scrypt hash · create session"], [2, 1, "4. session cookie", true],
    [1, 2, "5. getToken() → short-lived JWT (sub, role, site_ids)"], [1, 3, "6. GET /api/v1/invoices  Authorization: Bearer JWT"],
    [3, 2, "7. fetch /jwks (cached 10 min)", true], [3, 3, "8. verify signature, exp, aud; load role"], [3, 3, "9. require_role(...) + site scope check"],
    [3, 4, "10. query scoped to site_ids"], [3, 1, "11. 200 | 401 expired | 403 forbidden (RFC 7807)", true],
  ], 1500, 700);
}
function seqInvoice() {
  return sequence(["Head Chef", "api", "Storage", "worker", "Gemini", "Validator + matchers", "PostgreSQL"], [4], [
    [0, 1, "1. POST /invoices (file, Idempotency-Key)"], [1, 1, "2. sniff MIME · size · SHA-256"], [1, 6, "3. exact duplicate? → state=duplicate"],
    [1, 2, "4. put original (private)"], [1, 6, "5. InvoiceDocument(received) + job enqueued"], [1, 0, "6. 202 Accepted {document_id}", true],
    [3, 4, "7. classify(doc) → type, confidence, multi_doc"], { frame: "alt", label: "[not invoice · conf < 0.6 · multi-doc] → not_invoice / needs_review", from: 3, to: 5, rows: 0 }, { gap: 12 },
    [3, 4, "8. extract(doc, schema) → header + lines"], [3, 5, "9. validate maths, dates, VAT; recompute totals"],
    [3, 5, "10. match supplier · lines · price history · PO"], [3, 5, "11. fuzzy duplicate check"], [3, 6, "12. Invoice + lines + exceptions; state"],
    [3, 6, "13. audit_event + outbox(invoice.ready)"], [0, 1, "14. review exceptions · approve"], [1, 6, "15. receipt movements + price observations"],
  ], 1700, 980);
}
function seqNightly() {
  return sequence(["Scheduler", "api /internal", "worker", "Domain services", "Weather + holidays", "Gemini", "PostgreSQL"], [4, 5], [
    [0, 1, "1. POST /internal/dispatch (OIDC)"], [1, 6, "2. enqueue due site jobs (idempotent key: site+date)"], [2, 3, "3. metrics(D-1) · theoretical consumption"],
    [3, 4, "4. forecast weather + bank holidays"], [2, 3, "5. ForecastEngine.predict(D+1..D+7)"], [2, 3, "6. ProcurementPlanner.recommend()"],
    [2, 3, "7. MarginEngine.cost_items() · matrix"], [2, 3, "8. AnomalyEngine.run() → anomalies"], [2, 3, "9. InvestigationEngine (per anomaly)"],
    [3, 5, "10. narrate(evidence graph) → guarded text"], [2, 3, "11. RecommendationService.propose()"], [2, 6, "12. persist · outbox(brief.ready)"],
    [2, 2, "13. 07:00 local: compose + email brief"],
  ], 1600, 820);
}
function seqInvestigation() {
  return sequence(["AnomalyEngine", "InvestigationEngine", "Driver tree", "Hypothesis tests", "MemoryService", "NumberGuard", "Gemini"], [6], [
    [0, 1, "1. anomaly: revenue −18% (Fri)"], [1, 2, "2. decompose revenue = orders × spend"], [2, 1, "3. orders −4.5% · spend −14.1% · mix → chicken dishes", true],
    [1, 2, "4. segment item by day/daypart"], [2, 1, "5. 82% of drop in Friday dinner", true], [1, 3, "6. run tests for chicken-dish ingredients"],
    [3, 1, "7. stock-out 18:40 · short delivery · price +18% · weather normal", true], [1, 4, "8. recall(entities, cause codes)"],
    [4, 1, "9. similar case 19 Sep (short delivery, Supplier A)", true], [1, 1, "10. score causes (strength × coverage × timing)"],
    [1, 6, "11. narrate(evidence graph, schema)"], [6, 1, "12. finding / evidence / causes / next action", true], [1, 5, "13. check every number ∈ facts"],
    [5, 1, "14. pass | fail → retry → template", true],
  ], 1650, 860);
}
function seqAction() {
  return sequence(["Investigation", "RecommendationService", "GM", "Executor", "OutcomeEvaluator", "MemoryService"], [], [
    [0, 1, "1. propose: switch chicken to Supplier B (impact +£84/wk)"], [1, 1, "2. status=proposed · expires in 72 h"], [1, 2, "3. Action Centre card + email"],
    [2, 1, "4. approve (note)"], [1, 1, "5. Approval row · status=approved · audit"], [1, 3, "6. execute(rec, idempotency key)"],
    [3, 1, "7. draft PO #PO-118 created → completed", true], [1, 1, "8. schedule follow-up at +7 days"], [4, 1, "9. due(): measure cost per kg vs counterfactual", true],
    [4, 4, "10. effect −8.7% (expected −9%) → improved"], [4, 5, "11. remember(outcome, cause, action)"], [4, 2, "12. outcome shown on card", true],
  ], 1500, 760);
}

// ---------- 9. State charts ----------
function stateInvoice() {
  const W = 1500, H = 720;
  let a = "", b = startDot(50, 120);
  const S = {};
  const add = (id, x, y, t, sub, o) => { S[id] = stateNode(x, y, 200, 86, t, sub, o); b += S[id].svg; };
  add("rec", 100, 77, "received", "file stored, hashed");
  add("cls", 380, 77, "classifying", "Gemini classify");
  add("ext", 660, 77, "extracting", "Gemini extract");
  add("val", 940, 77, "validating", "maths · dates · VAT");
  add("mat", 1220, 77, "matching", "supplier · lines · prices");
  add("rev", 1220, 330, "needs_review", "exceptions open", { fill: C.bgAmber, stroke: C.amber });
  add("rdy", 940, 330, "ready_for_approval", "clean / resolved", { fill: C.bgTeal, stroke: C.teal });
  add("apr", 660, 330, "approved", "role + limit checked", { fill: C.bgTeal, stroke: C.teal });
  add("pst", 380, 330, "posted", "stock + prices", { fill: C.bgTeal, stroke: C.teal });
  add("not", 100, 330, "not_invoice", "other document type", { fill: C.bgGrey, stroke: C.slate });
  add("dup", 100, 560, "duplicate", "same SHA-256 / key", { fill: C.bgGrey, stroke: C.slate });
  add("rej", 940, 590, "rejected", "reason required", { fill: C.bgGrey, stroke: C.slate });
  add("fail", 1220, 590, "failed", "retries exhausted", { fill: C.bgRed, stroke: C.red });
  b += endDot(480, 540);
  a += arrow(64, 120, 96, 120, "");
  a += conn(S.rec, S.cls, "") + conn(S.cls, S.ext, "invoice") + conn(S.ext, S.val, "") + conn(S.val, S.mat, "ok");
  a += conn(S.mat, S.rev, "exceptions", { lx: 1330, ly: 260, anchor: "start" }) + conn(S.mat, S.rdy, "clean", { lx: 1150, ly: 245 });
  a += conn(S.val, S.rev, "math / field issues", { lx: 1050, ly: 205, anchor: "end" });
  a += conn(S.rev, S.rdy, "resolved") + conn(S.rdy, S.apr, "approve") + conn(S.apr, S.pst, "post");
  a += conn(S.rdy, S.rej, "reject", { lx: 1050, ly: 530, anchor: "start" }) + conn(S.rev, S.rej, "reject", { lx: 1200, ly: 505 });
  a += conn(S.rev, S.fail, "", {}) + label(1330, 520, "errors after 3 retries", { size: 12, anchor: "start" });
  a += conn(S.cls, S.not, "not invoice", { lx: 330, ly: 245, anchor: "end" });
  a += L.path("M100,140 C20,300 20,560 96,600", "duplicate", { lx: 50, ly: 470 });
  a += L.path("M480,165 C620,255 1150,250 1260,326", "conf < 0.6 / multi-doc", { lx: 780, ly: 232 });
  a += L.path("M760,418 C760,505 1040,505 1040,422", "edit after approval", { lx: 900, ly: 505 });
  a += arrow(480, 418, 480, 522, "");
  return svg(W, H, a + b);
}
function stateRecommendation() {
  const W = 1700, H = 700;
  let a = "", b = startDot(50, 140);
  const S = {};
  const add = (id, x, y, t, sub, o) => { S[id] = stateNode(x, y, 200, 86, t, sub, o); b += S[id].svg; };
  add("dra", 100, 97, "draft", "evidence attached");
  add("pro", 380, 97, "proposed", "impact · risk · expiry");
  add("apr", 660, 97, "approved", "approver recorded", { fill: C.bgTeal, stroke: C.teal });
  add("exe", 940, 97, "executing", "idempotent executor");
  add("com", 1220, 97, "completed", "PO / task / par", { fill: C.bgTeal, stroke: C.teal });
  add("exp", 100, 330, "expired", "not decided in time", { fill: C.bgGrey, stroke: C.slate });
  add("rej", 380, 330, "rejected", "reason captured", { fill: C.bgGrey, stroke: C.slate });
  add("sup", 660, 330, "superseded", "newer evidence", { fill: C.bgGrey, stroke: C.slate });
  add("fail", 940, 330, "failed", "executor error", { fill: C.bgRed, stroke: C.red });
  add("fol", 1220, 330, "follow_up", "measure at +N days");
  add("out", 1220, 560, "outcome_measured", "improved · no change · worse", { fill: C.bgPurple, stroke: C.purple });
  b += endDot(1560, 603);
  a += arrow(64, 140, 96, 140, "");
  a += conn(S.dra, S.pro, "publish") + conn(S.pro, S.apr, "approve") + conn(S.apr, S.exe, "") + conn(S.exe, S.com, "success");
  a += conn(S.com, S.fol, "") + conn(S.fol, S.out, "evaluate", { lx: 1330, ly: 505, anchor: "start" });
  a += conn(S.pro, S.exp, "TTL elapsed", { lx: 270, ly: 265, anchor: "end" }) + conn(S.pro, S.rej, "reject", { lx: 490, ly: 265, anchor: "start" }) + conn(S.pro, S.sup, "newer evidence", { lx: 640, ly: 245, anchor: "start" });
  a += arrow(1090, 186, 1090, 326, "") + label(1100, 265, "error after retries", { size: 12, anchor: "start" });
  a += arrow(990, 326, 990, 188, "") + label(980, 265, "retry", { size: 12, anchor: "end" });
  a += arrow(1425, 603, 1542, 603, "") + label(1484, 588, "to memory", { size: 12 });
  return svg(W, H, a + b);
}
function statePO() {
  const W = 1600, H = 520;
  let a = "", b = startDot(50, 130);
  const S = {};
  const add = (id, x, y, t, sub, o) => { S[id] = stateNode(x, y, 200, 86, t, sub, o); b += S[id].svg; };
  add("dra", 100, 87, "draft", "from recommendation");
  add("pen", 370, 87, "pending_approval", "limit check");
  add("com", 640, 87, "committed", "approved by role", { fill: C.bgTeal, stroke: C.teal });
  add("sen", 910, 87, "sent", "email to supplier (opt.)");
  add("prt", 1180, 87, "part_received", "GRN / invoice lines");
  add("rcv", 1180, 320, "received", "three-way matched", { fill: C.bgTeal, stroke: C.teal });
  add("can", 370, 320, "cancelled", "reason", { fill: C.bgGrey, stroke: C.slate });
  b += endDot(1450, 363);
  a += arrow(64, 130, 96, 130, "");
  a += conn(S.dra, S.pen, "submit") + conn(S.pen, S.com, "approve") + conn(S.com, S.sen, "send") + conn(S.sen, S.prt, "partial");
  a += conn(S.prt, S.rcv, "complete") + conn(S.sen, S.rcv, "full receipt", { lx: 1080, ly: 260 }) + arrow(1385, 363, 1432, 363, "");
  a += conn(S.pen, S.can, "reject") + conn(S.dra, S.can, "discard", { lx: 250, ly: 260 }) + conn(S.com, S.can, "cancel", { lx: 560, ly: 260 });
  b += text(800, 490, "Edits to lines while pending_approval or committed return the PO to draft and clear the approval.", { size: 15, italic: true, color: C.slate });
  return svg(W, H, a + b);
}

// ---------- 10. Evidence chain example ----------
function evidence() {
  const W = 1700, H = 900;
  let a = "", b = "";
  const n = (id, x, y, w, t, sub, kind) => {
    const sty = { root: [C.bgNavy, C.navy], sup: [C.bgTeal, C.teal], ref: [C.bgGrey, C.slate], mem: [C.bgPurple, C.purple], out: [C.bgAmber, C.amber] }[kind];
    const nn = node(x, y, w, 84, t, sub ? [sub] : [], { fill: sty[0], stroke: sty[1], fs: 17, ss: 13.5, lh: 21 }); b += nn.svg; return nn;
  };
  const R = n("r", 620, 20, 460, "Revenue −18.0% vs 4-wk Friday median", "Fri 10 Oct · £7,410 vs £9,040", "root");
  const O = n("o", 380, 160, 380, "Orders −4.5%", "within normal range (z = −0.8)", "ref");
  const Sp = n("s", 1020, 160, 380, "Average spend −14.1%", "mix effect −11.9% · price effect 0.0%", "sup");
  const I = n("i", 1020, 300, 380, "Chicken dishes units −37%", "4 items, led by Chicken Wrap −41% · 71% of spend change", "sup");
  const D = n("d", 1020, 440, 380, "82% of the drop in Friday dinner", "18:30-21:30 · no chicken dishes sold after 18:40", "sup");
  const St = n("st", 560, 440, 380, "Chicken thigh stock-out 18:40", "stock ledger: on hand 0 kg · forecast need 6.2 kg", "sup");
  const Dl = n("dl", 560, 580, 380, "Delivery short 40% (INV-4471)", "Supplier A: 12 kg invoiced vs 20 kg PO", "sup");
  const Pr = n("pr", 100, 580, 380, "Chicken thigh price +18%", "£7.90/kg vs 90-day median £6.70/kg", "sup");
  const W1 = n("w", 40, 300, 250, "Weather normal", "14 °C, dry · factor 1.00", "ref");
  const Ds = n("ds", 310, 300, 250, "Discounts normal", "2.8% vs 3.1% baseline", "ref");
  const M = n("m", 1020, 580, 380, "Similar case 19 Sep", "short delivery · Supplier A · resolved by par +30%", "mem");
  const C1 = n("c", 340, 740, 1020, "Root cause: supplier short delivery → ingredient stock-out (confidence 0.86)", "Next actions: switch chicken to Supplier B (−9% /kg) · raise par 18 → 24 kg · review wrap price (GP 68.1% → 64.3%)", "out");
  a += conn(R, O, "") + conn(R, Sp, "") + conn(Sp, I, "") + conn(I, D, "") + conn(D, St, "explained by") + conn(St, Dl, "caused by") + conn(Dl, Pr, "same invoice");
  a += conn(Dl, M, "matches pattern") + conn(Dl, C1, "") + conn(M, C1, "") ;
  a += L.path("M620,45 H165 V296", "ruled out", { dash: true, lx: 400, ly: 40 }) + L.path("M620,85 H335 V296", "", { dash: true });
  const lg = [["finding", C.navy, C.bgNavy], ["supporting evidence", C.teal, C.bgTeal], ["ruled out", C.slate, C.bgGrey], ["memory", C.purple, C.bgPurple], ["conclusion", C.amber, C.bgAmber]];
  lg.forEach((l, i) => (b += `<rect x="${1450}" y="${40 + i * 34}" width="20" height="20" rx="4" fill="${l[2]}" stroke="${l[1]}" stroke-width="2"/>` + text(1478, 56 + i * 34, l[0], { anchor: "start", size: 14 })));
  return svg(W, H, a + b);
}


// ---------- Agent loop ----------
function agentLoop() {
  const W = 1700, H = 640, w = 245, h = 118, X = [30, 305, 580, 855, 1130, 1405], y = 150;
  const steps = [
    ["Detect", ["detector registry", "money-ranked severity"], C.teal, C.bgTeal, ["price +18% on INV-4471", "Fri revenue -18%"]],
    ["Investigate", ["driver tree · hypotheses", "evidence chain · memory"], C.teal, C.bgTeal, ["short delivery → stock-out", "confidence 0.86"]],
    ["Recommend", ["action + computed impact", "risk · approver · expiry"], C.teal, C.bgTeal, ["switch to Supplier B", "+£84 / week"]],
    ["Human approval", ["approve · adjust · reject", "role + limit checked"], C.amber, C.bgAmber, ["GM approves", "in the Action Centre"]],
    ["Execute", ["idempotent executor", "PO · par · task · email"], C.navy, C.bgNavy, ["draft PO-118 created", "supplier emailed"]],
    ["Measure", ["outcome vs counterfactual", "verdict written to memory"], C.navy, C.bgNavy, ["cost/kg -8.7% at +7 days", "improved"]],
  ];
  let a = "", b = "";
  b += `<rect x="20" y="70" width="815" height="230" rx="14" fill="${C.bgTeal}" opacity="0.35"/>` + text(30, 96, "Agent works autonomously", { anchor: "start", size: 17, bold: true, color: C.teal });
  b += `<rect x="845" y="70" width="265" height="230" rx="14" fill="${C.bgAmber}" opacity="0.6"/>` + text(977, 96, "Human in the loop", { size: 17, bold: true, color: C.amber });
  b += `<rect x="1120" y="70" width="560" height="230" rx="14" fill="${C.bgNavy}" opacity="0.6"/>` + text(1130, 96, "Agent executes and follows up", { anchor: "start", size: 17, bold: true, color: C.navy });
  steps.forEach((st, i) => {
    b += box(X[i], y, w, h, `${i + 1}  ${st[0]}`, st[1], { fill: C.white, stroke: st[2], fs: 21, ss: 14.5, lh: 24, sw: i === 3 ? 3.5 : 2 });
    b += text(X[i] + w / 2, 330, st[4][0], { size: 14, color: C.slate, italic: true }) + text(X[i] + w / 2, 351, st[4][1], { size: 14, color: C.slate, italic: true });
    if (i < 5) a += arrow(X[i] + w + 3, y + h / 2, X[i + 1] - 5, y + h / 2, "");
  });

  b += box(600, 450, 500, 100, "Operational memory", ["cases · causes · actions · outcomes · manager notes"], { fill: C.bgPurple, stroke: C.purple, fs: 20, ss: 14.5, lh: 25 });
  a += L.path("M1527,272 C1527,500 1240,500 1105,500", "learn", { lx: 1400, ly: 470 });
  a += L.path("M600,500 C340,500 330,440 330,276", "recall similar cases", { lx: 440, ly: 485 });
  a += L.path("M977,272 V425 H50 V276", "", { dash: true });
  b += label(700, 430, "rejected / expired → reason stored, detector tuned", { size: 13 });
  b += text(W / 2, 610, "Every step is persisted on one OperationsCase, so the timeline of what the agent saw, concluded, proposed, did and achieved is auditable.", { size: 15, italic: true, color: C.slate });
  return svg(W, H, a + b);
}

// ---------- Tenancy & integration configuration ----------
function tenancy() {
  const W = 1700, H = 820;
  const k = {};
  const add = (id, x, y, w, at, op, o) => (k[id] = uml(x, y, w, id, at, op || [], o));
  const T = { fill: C.bgTeal, stroke: C.teal }, A = { fill: C.bgAmber, stroke: C.amber }, Pp = { fill: C.bgPurple, stroke: C.purple };
  add("Organisation", 640, 20, 300, ["-id : UUID", "-name : str", "-default_currency : CurrencyCode", "-status : active|suspended"]);
  add("User", 120, 20, 280, ["-id : UUID", "-organisation_id : UUID", "-email : str"]);
  add("Membership", 120, 260, 280, ["-user_id : UUID", "-site_id : UUID? (null = all sites)", "-role : Role", "-approval_limits : dict"]);
  add("Site", 640, 260, 300, ["-id : UUID", "-organisation_id : UUID", "-name : str", "-timezone : str", "-currency : CurrencyCode", "-vat_scheme : str", "-lat, lng : float"], ["+context() : SiteContext"]);
  add("ConfigValue", 1180, 20, 330, ["-scope : system|organisation|site", "-scope_id : UUID?", "-key : str", "-value : json", "-version : int"], ["resolve: site → organisation → system"], Pp);
  add("IntegrationConnection", 1180, 290, 330, ["-organisation_id : UUID", "-site_id : UUID?", "-kind : IntegrationKind", "-provider : str", "-secret_ref : str", "-settings : json", "-status : str"], [], A);
  add("SiteContext", 1180, 600, 330, ["+site, organisation, timezone, currency", "+config : EffectiveConfig", "+adapters : AdapterRegistry"], [], { stereo: "«value object»", ...T });
  let b = "";
  b += box(330, 600, 380, 170, "Organisation reference data", ["suppliers · supplier products · price history", "ingredients · unit conversions", "menu items · recipes (site overrides allowed)", "shared by all sites of the organisation"], { fill: C.bgNavy, stroke: C.navy, fs: 17, ss: 13.5, lh: 22, rx: 4 });
  b += box(760, 600, 380, 170, "Site operational data", ["orders · shifts · cash-ups · invoices", "stock ledger · counts · waste · POs", "forecasts · anomalies · cases · memory", "every row: organisation_id + site_id"], { fill: C.bgTeal, stroke: C.teal, fs: 17, ss: 13.5, lh: 22, rx: 4 });
  let r = "";
  r += rel(k.Organisation, k.Site, { m1: "1", m2: "1..*" });
  r += rel(k.Organisation, k.User, { m1: "1", m2: "*" });
  r += rel(k.User, k.Membership, { m1: "1", m2: "1..*" });
  r += rel(k.Membership, k.Site, { m1: "*", m2: "0..1" });
  r += rel(k.Organisation, k.ConfigValue, { m1: "1", m2: "*" });
  r += rel(k.Site, k.IntegrationConnection, { m1: "1", m2: "*" });
  r += rel(k.Site, k.SiteContext, { dash: true, end: "open", lab: "builds" });
  r += rel(k.Site, { cx: 950, cy: 685, w: 380, h: 170, shape: "rect" }, { m1: "1", m2: "*" });
  r += L.path("M700,190 C560,330 520,450 520,596", "1 .. *", { lx: 540, ly: 420 });
  Object.values(k).forEach((n) => (b += n.svg));
  b += text(30, 805, "Adding a restaurant is configuration, not code: create Organisation → Sites → Memberships → ConfigValues → IntegrationConnections; domain services only ever see a SiteContext.", { anchor: "start", size: 14.5, italic: true, color: C.slate });
  return svg(W, H, r + b);
}

const figs = {
  v2_agent_loop: agentLoop, v2_tenancy: tenancy,
  v2_loop: loop, v2_context: context, v2_dfd: dfd, v2_component: component, v2_deployment: deployment, v2_access: access,
  v2_class_sales: classSales, v2_class_purchasing: classPurchasing, v2_class_intel: classIntel, v2_class_services: classServices,
  v2_seq_auth: seqAuth, v2_seq_invoice: seqInvoice, v2_seq_nightly: seqNightly, v2_seq_investigation: seqInvestigation, v2_seq_action: seqAction,
  v2_state_invoice: stateInvoice, v2_state_recommendation: stateRecommendation, v2_state_po: statePO, v2_evidence: evidence,
};
for (const [name, fn] of Object.entries(figs)) fs.writeFileSync(path.join(__dirname, name + ".svg"), fn());
console.log("v2 SVGs written:", Object.keys(figs).length);
