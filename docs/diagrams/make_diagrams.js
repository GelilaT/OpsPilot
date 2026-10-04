// Generates all specification diagrams as SVG. Render to PNG with ./render.sh (headless Chrome).
// Figure titles are added as captions in the Word document, not inside the images.
const fs = require("fs");
const path = require("path");

const C = {
  navy: "#1F3A5F", blue: "#2F5597", teal: "#0F766E", amber: "#B45309", slate: "#475569",
  ink: "#0F172A", line: "#64748B", bgNavy: "#EAF0F7", bgBlue: "#DAE3F3", bgTeal: "#E6F4F1",
  bgAmber: "#FDF3E7", bgGrey: "#F1F5F9", white: "#FFFFFF", red: "#B91C1C", green: "#15803D",
};
const esc = (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const FONT = "font-family='Helvetica, Arial, sans-serif'";

const defs = `<defs>
  <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${C.line}"/></marker>
  <marker id="arrT" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${C.teal}"/></marker>
  <marker id="open" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10" fill="none" stroke="${C.line}" stroke-width="1.5"/></marker>
  <marker id="tri" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="12" markerHeight="12" orient="auto"><path d="M0,0 L12,6 L0,12 z" fill="${C.white}" stroke="${C.line}" stroke-width="1.5"/></marker>
  <marker id="dia" viewBox="0 0 14 10" refX="1" refY="5" markerWidth="14" markerHeight="10" orient="auto-start-reverse"><path d="M1,5 L7,1 L13,5 L7,9 z" fill="${C.line}"/></marker>
</defs>`;
const svg = (w, h, body) => `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${defs}<rect width="${w}" height="${h}" fill="${C.white}"/>${body}</svg>`;
const text = (x, y, t, o = {}) => `<text x="${x}" y="${y}" text-anchor="${o.anchor || "middle"}" ${FONT} font-size="${o.size || 14}" font-weight="${o.bold ? 700 : 400}" ${o.italic ? "font-style='italic'" : ""} fill="${o.color || C.ink}">${esc(t)}</text>`;
function label(x, y, t, o = {}) {
  const sz = o.size || 13, w = String(t).length * sz * 0.55 + 10;
  const ax = o.anchor === "start" ? x - 4 : o.anchor === "end" ? x - w + 4 : x - w / 2;
  return `<rect x="${ax}" y="${y - sz}" width="${w}" height="${sz + 6}" fill="${C.white}" opacity="0.92"/>` + text(x, y, t, { size: sz, anchor: o.anchor, color: o.color });
}
function box(x, y, w, h, title, sub = [], o = {}) {
  const fill = o.fill || C.bgNavy, stroke = o.stroke || C.navy;
  let s = `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${o.rx ?? 10}" fill="${fill}" stroke="${stroke}" stroke-width="${o.sw || 2}" ${o.dash ? "stroke-dasharray='8 6'" : ""}/>`;
  const lines = [title, ...sub], lh = o.lh || 21;
  const ty = y + h / 2 - (lines.length * lh) / 2 + 16;
  lines.forEach((t, i) => (s += text(x + w / 2, ty + i * lh, t, { size: i === 0 ? o.fs || 18 : o.ss || 14, bold: i === 0, color: i === 0 ? stroke : C.slate })));
  return s;
}
function arrow(x1, y1, x2, y2, lab, o = {}) {
  const m = o.teal ? "arrT" : "arr";
  let s = `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${o.teal ? C.teal : C.line}" stroke-width="2" ${o.noHead ? "" : `marker-end="url(#${m})"`} ${o.both ? `marker-start="url(#${m})"` : ""} ${o.dash ? "stroke-dasharray='6 5'" : ""}/>`;
  if (lab) s += label(o.lx ?? (x1 + x2) / 2, o.ly ?? (y1 + y2) / 2 - 6, lab, { anchor: o.anchor });
  return s;
}
function actor(x, y, lab) {
  return `<g stroke="${C.navy}" stroke-width="3" fill="none"><circle cx="${x}" cy="${y}" r="16"/><line x1="${x}" y1="${y + 16}" x2="${x}" y2="${y + 60}"/>
    <line x1="${x - 26}" y1="${y + 32}" x2="${x + 26}" y2="${y + 32}"/><line x1="${x}" y1="${y + 60}" x2="${x - 22}" y2="${y + 92}"/><line x1="${x}" y1="${y + 60}" x2="${x + 22}" y2="${y + 92}"/></g>` + text(x, y + 118, lab, { size: 16, bold: true });
}
// trimmed connector between two nodes {cx, cy, shape:'circle'|'rect', r | w,h}
function edge(n, tx, ty) {
  const dx = tx - n.cx, dy = ty - n.cy, len = Math.hypot(dx, dy) || 1;
  if (n.shape === "circle") return [n.cx + (dx / len) * (n.r + 3), n.cy + (dy / len) * (n.r + 3)];
  const s = Math.min((n.w / 2 + 3) / Math.abs(dx || 1e-9), (n.h / 2 + 3) / Math.abs(dy || 1e-9));
  return [n.cx + dx * s, n.cy + dy * s];
}
function conn(a, b, lab, o = {}) {
  const [x1, y1] = edge(a, b.cx, b.cy), [x2, y2] = edge(b, a.cx, a.cy);
  return arrow(x1, y1, x2, y2, lab, o);
}

// ---------- Context ----------
function context() {
  const W = 1600, H = 820;
  let b = "";
  b += box(560, 290, 480, 220, "OpsPilot", ["AI Operations Manager", "Next.js app on Google Cloud Run", "Metrics · Anomalies · Brief · Outlook · Chat"], { fill: C.bgTeal, stroke: C.teal, fs: 26, sw: 3 });
  b += actor(130, 210, "Owner / GM");
  b += actor(130, 520, "Shift Manager");
  b += arrow(200, 280, 555, 360, "Dashboard, chat, resolve tasks", { both: true });
  b += arrow(200, 590, 555, 460, "Acknowledge / annotate tasks", { both: true });
  b += box(640, 50, 320, 100, "Google Cloud Scheduler", ["3 jobs: 07:00 · 16:00 · Mon 08:00"], { fill: C.bgGrey, stroke: C.slate });
  b += arrow(800, 150, 800, 285, "HTTPS + OIDC token", { lx: 812, anchor: "start" });
  b += box(1230, 110, 300, 100, "Google Gemini API", ["2.5 Flash · structured output"], { fill: C.bgAmber, stroke: C.amber });
  b += box(1230, 350, 300, 100, "Open-Meteo API", ["Forecast + historical weather"], { fill: C.bgAmber, stroke: C.amber });
  b += box(1230, 590, 300, 100, "Twilio SendGrid API", ["Transactional email"], { fill: C.bgAmber, stroke: C.amber });
  b += arrow(1045, 340, 1225, 170, "FactSheet → narrative", { both: true, lx: 1120, ly: 240 });
  b += arrow(1045, 400, 1225, 400, "lat/long → weather", { both: true });
  b += arrow(1045, 460, 1225, 630, "Brief / recap / nudge", { lx: 1180, ly: 535, anchor: "start" });
  b += box(420, 660, 330, 110, "POS data source", ["Simulated POS · CSV import"], { fill: C.bgGrey, stroke: C.slate, dash: true });
  b += box(850, 660, 330, 110, "Neon PostgreSQL", ["Prisma ORM · free tier"]);
  b += arrow(640, 655, 720, 515, "orders, shifts, cash-ups", { lx: 600, ly: 590, anchor: "end" });
  b += arrow(930, 515, 990, 655, "read / write", { both: true, lx: 1000, ly: 590, anchor: "start" });
  b += text(1380, 750, "Inbox of Owner / GM", { size: 15, color: C.slate });
  b += arrow(1380, 695, 1380, 730, "");
  return svg(W, H, b);
}

// ---------- Level-1 DFD ----------
function dfd() {
  const W = 1700, H = 1070;
  let b = "";
  const ent = (x, y, lab) => { b += box(x, y, 210, 62, lab, [], { rx: 0, fill: C.bgGrey, stroke: C.slate, fs: 16 }); return { cx: x + 105, cy: y + 31, shape: "rect", w: 210, h: 62 }; };
  const proc = (cx, cy, n, l1, l2) => {
    b += `<circle cx="${cx}" cy="${cy}" r="66" fill="${C.bgTeal}" stroke="${C.teal}" stroke-width="2.5"/>`;
    b += text(cx, cy - 18, n, { size: 13, bold: true, color: C.teal }) + text(cx, cy + 4, l1, { size: 15, bold: true }) + text(cx, cy + 23, l2, { size: 15, bold: true });
    return { cx, cy, shape: "circle", r: 66 };
  };
  const store = (cx, cy, id, lab) => {
    const w = 230, h = 44, x = cx - w / 2, y = cy - h / 2;
    b += `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${C.bgBlue}"/><line x1="${x}" y1="${y}" x2="${x + w}" y2="${y}" stroke="${C.blue}" stroke-width="2"/><line x1="${x}" y1="${y + h}" x2="${x + w}" y2="${y + h}" stroke="${C.blue}" stroke-width="2"/><line x1="${x + 46}" y1="${y}" x2="${x + 46}" y2="${y + h}" stroke="${C.blue}" stroke-width="2"/>`;
    b += text(x + 23, cy + 5, id, { size: 14, bold: true, color: C.blue }) + text(x + 46 + (w - 46) / 2, cy + 5, lab, { size: 14 });
    return { cx, cy, shape: "rect", w, h };
  };
  let arrows = "";
  const E1 = ent(40, 50, "POS / CSV export");
  const E2 = ent(745, 50, "Cloud Scheduler");
  const E3 = ent(1440, 50, "Open-Meteo");
  const E4 = ent(40, 980, "Owner / Manager");
  const E5 = ent(745, 980, "Gemini API");
  const E6 = ent(1440, 980, "SendGrid");
  const P1 = proc(145, 290, "1.0", "Ingest", "data");
  const P2 = proc(520, 290, "2.0", "Compute", "metrics");
  const P3 = proc(900, 290, "3.0", "Detect", "anomalies");
  const P6 = proc(1545, 290, "6.0", "Build", "outlook");
  const P7 = proc(145, 760, "7.0", "Answer", "questions");
  const P5 = proc(520, 760, "5.0", "Manage", "tasks");
  const P4 = proc(900, 760, "4.0", "Generate", "brief");
  const P8 = proc(1545, 760, "8.0", "Send", "notifications");
  const D1 = store(330, 490, "D1", "Trading data");
  const D2 = store(710, 490, "D2", "Daily metrics");
  const D3 = store(1090, 490, "D3", "Anomalies & tasks");
  const D5 = store(1470, 490, "D5", "Weather");
  const D4 = store(1225, 880, "D4", "Briefs");
  arrows += conn(E1, P1, "orders, shifts, cash-ups", { lx: 190, ly: 160, anchor: "start" });
  arrows += conn(P1, D1, "validated records");
  arrows += conn(D1, P2, "transactions");
  arrows += conn(P2, D2, "KPIs + baselines");
  arrows += conn(D2, P3, "metrics");
  arrows += conn(P3, D3, "anomalies → tasks");
  arrows += conn(E3, P6, "forecast / history", { lx: 1560, ly: 180, anchor: "start" });
  arrows += conn(P6, D5, "weather");
  arrows += conn(D2, P4, "facts", { lx: 800, ly: 598 });
  arrows += conn(D3, P4, "anomalies");
  arrows += conn(D5, P4, "outlook", { lx: 1200, ly: 640 });
  arrows += conn(E2, P2, "07:00 trigger (runs 2.0 → 3.0 → 4.0 → 8.0)", { lx: 700, ly: 185, anchor: "end" });
  arrows += conn(P4, E5, "FactSheet / narrative", { both: true, lx: 900, ly: 905 });
  arrows += conn(P4, D4, "verified brief");
  arrows += conn(D4, P8, "brief / recap");
  arrows += conn(D3, P8, "overdue critical tasks", { lx: 1395, ly: 630, anchor: "start" });
  arrows += conn(P8, E6, "emails");
  arrows += conn(D3, P5, "tasks", { both: true, lx: 660, ly: 690 });
  arrows += conn(E4, P5, "acknowledge / resolve", { both: true, lx: 380, ly: 905 });
  arrows += conn(E4, P7, "question / answer", { both: true, lx: 150, ly: 885 });
  arrows += conn(P7, E5, "tool calling", { both: true, lx: 450, ly: 862 });
  arrows += conn(D2, P7, "tool results", { lx: 405, ly: 628 });
  return svg(W, H, arrows + b);
}

// ---------- Use cases ----------
function usecases() {
  const W = 1600, H = 900;
  let b = `<rect x="380" y="20" width="840" height="850" rx="16" fill="${C.bgGrey}" stroke="${C.slate}" stroke-width="2"/>` + text(800, 52, "OpsPilot", { size: 18, bold: true, color: C.slate });
  const uc = ["UC-01 View morning dashboard & brief", "UC-02 Drill into an anomaly", "UC-03 Manage investigation tasks", "UC-04 View tomorrow outlook", "UC-05 Ask OpsPilot a question", "UC-06 Browse brief archive", "UC-07 Configure targets & thresholds", "UC-08 Simulate day / import POS CSV", "UC-09 Generate & email daily brief", "UC-10 Follow up unresolved critical tasks", "UC-11 Send weekly recap"];
  const pos = uc.map((_, i) => [800, 100 + i * 70]);
  let lines = "";
  [0, 1, 2, 3, 4, 5, 6, 7].forEach((i) => (lines += `<line x1="200" y1="200" x2="${pos[i][0] - 300}" y2="${pos[i][1]}" stroke="${C.line}" stroke-width="1.5"/>`));
  [0, 1, 2, 4].forEach((i) => (lines += `<line x1="200" y1="560" x2="${pos[i][0] - 300}" y2="${pos[i][1]}" stroke="${C.line}" stroke-width="1.5"/>`));
  [8, 9, 10].forEach((i) => (lines += `<line x1="1400" y1="700" x2="${pos[i][0] + 300}" y2="${pos[i][1]}" stroke="${C.teal}" stroke-width="1.5"/>`));
  b += lines;
  uc.forEach((u, i) => (b += `<ellipse cx="${pos[i][0]}" cy="${pos[i][1]}" rx="300" ry="27" fill="${C.white}" stroke="${i >= 8 ? C.teal : C.navy}" stroke-width="2"/>` + text(pos[i][0], pos[i][1] + 5, u, { size: 16 })));
  b += actor(160, 140, "Owner / GM") + actor(160, 500, "Shift Manager") + actor(1440, 640, "Cloud Scheduler");
  return svg(W, H, b);
}

// ---------- Component (layered architecture) ----------
function component() {
  const W = 1600, H = 940;
  let b = `<rect x="40" y="20" width="1100" height="820" rx="14" fill="none" stroke="${C.teal}" stroke-width="2" stroke-dasharray="10 6"/>` + text(60, 48, "«container» Google Cloud Run — Next.js 15 application (TypeScript)", { anchor: "start", size: 17, bold: true, color: C.teal });
  b += text(70, 88, "PRESENTATION SUBSYSTEM  (React · Tailwind · Recharts)", { anchor: "start", size: 16, bold: true, color: C.navy });
  ["Morning Dashboard", "Anomaly Drill-down", "Investigations", "Trends", "Ask OpsPilot", "Briefs & Settings"].forEach((p, i) => (b += box(70 + i * 175, 100, 160, 70, p, [], { fs: 15 })));
  b += arrow(590, 175, 590, 230, "fetch / JSON (session cookie)", { lx: 605, ly: 205, anchor: "start" });
  b += text(70, 232, "API SUBSYSTEM  (/app/api route handlers + Zod validation)", { anchor: "start", size: 16, bold: true, color: C.navy });
  ["/metrics", "/briefs", "/anomalies", "/tasks", "/outlook", "/chat", "/ingest", "/cron/*"].forEach((p, i) => (b += box(70 + i * 131, 244, 122, 56, p, [], { fs: 14, fill: C.bgGrey, stroke: C.slate })));
  b += arrow(590, 304, 590, 357, "");
  b += text(70, 354, "DOMAIN SUBSYSTEMS  (src/server)", { anchor: "start", size: 16, bold: true, color: C.navy });
  [["Ingestion", "seed · simulate-day", "CSV import"], ["Metrics", "pure KPI functions", "baselines (median/MAD)"], ["Anomaly detection", "rule registry", "severity + evidence"], ["Outlook", "weather × weekday", "labour-hours cap"]]
    .forEach((s, i) => (b += box(70 + i * 262, 365, 245, 110, s[0], [s[1], s[2]], { fill: C.bgTeal, stroke: C.teal })));
  [["AI (brief + chat)", "FactSheet · prompts", "Number Guard · tools"], ["Jobs & tasks", "daily · follow-up · weekly", "task workflow"], ["Integrations", "gemini · weather", "mailer (SendGrid)"], ["Auth & settings", "NextAuth · roles", "cron OIDC / secret"]]
    .forEach((s, i) => (b += box(70 + i * 262, 495, 245, 110, s[0], [s[1], s[2]], { fill: C.bgTeal, stroke: C.teal })));
  b += arrow(590, 610, 590, 670, "Prisma Client", { lx: 605, ly: 645, anchor: "start" });
  b += box(250, 675, 680, 140, "Data subsystem — Neon PostgreSQL", ["Site · Product · Order · OrderLine · Shift · Discount · Void · CashUp", "WeatherDaily · DailyMetrics · Brief · Anomaly · Task · TaskNote", "Settings · JobRun · AiCallLog"]);
  b += box(1230, 60, 320, 100, "Cloud Scheduler", ["daily 07:00 · follow-up 16:00", "weekly Mon 08:00"], { fill: C.bgGrey, stroke: C.slate });
  b += arrow(1225, 110, 1144, 110, "", { teal: true }) + label(1190, 190, "POST /api/cron/*");
  b += box(1230, 360, 320, 90, "Gemini API", ["gemini-2.5-flash"], { fill: C.bgAmber, stroke: C.amber });
  b += box(1230, 480, 320, 90, "Open-Meteo", ["forecast + archive"], { fill: C.bgAmber, stroke: C.amber });
  b += box(1230, 600, 320, 90, "SendGrid", ["v3 Mail Send"], { fill: C.bgAmber, stroke: C.amber });
  b += arrow(1144, 405, 1225, 405, "", { both: true }) + arrow(1144, 525, 1225, 525, "", { both: true }) + arrow(1144, 645, 1225, 645, "");
  b += text(1190, 340, "via Integrations", { size: 14 });
  b += box(1230, 740, 320, 90, "Browser (desktop / mobile)", ["Owner · GM · Shift Manager"], { fill: C.white });
  b += arrow(1225, 785, 1144, 785, "", { both: true }) + label(1184, 772, "HTTPS");
  b += text(W / 2, 895, "Principle: the backend owns the numbers — Gemini owns the explanation.", { size: 17, italic: true, color: C.teal });
  return svg(W, H, b);
}

// ---------- Deployment ----------
function deployment() {
  const W = 1600, H = 900;
  const node = (x, y, w, h, t, o = {}) => {
    const f = o.fill || C.bgBlue, st = o.stroke || C.blue;
    return `<path d="M${x},${y} l14,-14 h${w} v${h} l-14,14 z" fill="${f}" stroke="${st}" stroke-width="2"/><line x1="${x + w}" y1="${y}" x2="${x + w + 14}" y2="${y - 14}" stroke="${st}" stroke-width="2"/><rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${f}" stroke="${st}" stroke-width="2"/>` + text(x + 14, y + 28, t, { anchor: "start", size: 16, bold: true, color: st });
  };
  const art = (x, y, w, t, sub) => box(x, y, w, sub ? 60 : 42, t, sub ? [sub] : [], { fill: C.white, stroke: C.slate, fs: 14, rx: 4 });
  let b = "", a = "";
  b += node(40, 300, 300, 190, "«device» User browser");
  b += art(65, 350, 250, "React UI (Next.js client)", "Chrome · Safari · mobile");
  b += art(65, 428, 250, "Session cookie (HTTP-only)");
  b += node(420, 40, 640, 640, "«cloud» Google Cloud project (europe-west2)");
  b += node(445, 95, 590, 300, "«node» Cloud Run service: opspilot", { fill: C.bgTeal, stroke: C.teal });
  b += art(470, 145, 540, "«container» Next.js standalone", "Node.js 20 LTS · port 8080");
  b += art(470, 225, 540, "«artifact» UI + API routes + scheduled job handlers");
  b += art(470, 285, 540, "min 0 / max 2 instances · 1 vCPU · 512 MiB");
  b += art(470, 340, 540, "Secrets injected as environment variables");
  b += art(445, 440, 190, "Cloud Scheduler", "3 HTTP jobs");
  b += art(645, 440, 190, "Secret Manager", "API keys, DB URL");
  b += art(845, 440, 190, "Artifact Registry", "container image");
  b += art(445, 530, 390, "Service account: scheduler-invoker", "OIDC token audience = service URL");
  b += art(845, 530, 190, "Cloud Logging", "request + job logs");
  b += node(1160, 40, 400, 150, "«cloud» Neon (eu-west-2)", { fill: C.bgNavy, stroke: C.navy });
  b += art(1185, 90, 350, "PostgreSQL 16 · pooled", "TLS · Prisma migrations");
  b += node(1160, 260, 400, 80, "«external» Gemini API (AI Studio)", { fill: C.bgAmber, stroke: C.amber });
  b += node(1160, 400, 400, 80, "«external» Open-Meteo API", { fill: C.bgAmber, stroke: C.amber });
  b += node(1160, 540, 400, 80, "«external» Twilio SendGrid API", { fill: C.bgAmber, stroke: C.amber });
  b += node(420, 750, 640, 120, "«cloud» GitHub", { fill: C.bgGrey, stroke: C.slate });
  b += art(450, 795, 290, "Repository + Actions CI", "lint · test · build image");
  b += art(770, 795, 270, "Fallback cron workflow", "X-Cron-Secret header");
  a += arrow(345, 395, 440, 300, "HTTPS", { both: true, lx: 385, ly: 335 });
  a += arrow(540, 436, 540, 400, "", { teal: true }) + label(610, 425, "OIDC", { size: 12 });
  a += arrow(740, 436, 740, 400, "") + arrow(940, 436, 940, 400, "");
  a += arrow(1052, 150, 1155, 120, "TLS :5432", { lx: 1105, ly: 122 });
  a += arrow(1052, 250, 1155, 300, "HTTPS / JSON", { lx: 1105, ly: 262 });
  a += arrow(1052, 320, 1155, 440, "HTTPS / JSON", { lx: 1105, ly: 370 });
  a += arrow(1052, 380, 1155, 580, "HTTPS / JSON", { lx: 1105, ly: 470 });
  a += arrow(595, 790, 595, 690, "push image", { lx: 605, ly: 735, anchor: "start" });
  a += arrow(905, 790, 905, 690, "POST /api/cron/* (fallback)", { dash: true, lx: 915, ly: 735, anchor: "start" });
  return svg(W, H, b + a);
}

// ---------- Access control matrix ----------
function access() {
  const W = 1500, H = 730;
  const roles = ["Owner", "Manager", "Scheduler (service acct.)"];
  const res = [
    ["Dashboard, KPIs, brief", "✓✓✗"], ["Anomaly detail", "✓✓✗"], ["Tasks: view / acknowledge / resolve", "✓✓✗"], ["Tasks: dismiss / reopen", "✓✗✗"],
    ["Ask OpsPilot chat", "✓✓✗"], ["Tomorrow outlook", "✓✓✗"], ["Briefs archive", "✓✓✗"], ["Settings (targets, thresholds, recipients)", "✓✗✗"],
    ["Simulate day / CSV import", "✓✗✗"], ["Run job now / force re-run", "✓✗✗"], ["POST /api/cron/* (daily, follow-up, weekly)", "✗✗✓"],
  ];
  const x0 = 40, y0 = 20, cw0 = 590, cw = 270, rh = 52;
  let b = `<rect x="${x0}" y="${y0}" width="${cw0 + cw * 3}" height="${rh}" fill="${C.blue}"/>` + text(x0 + 16, y0 + 33, "Resource / action", { anchor: "start", size: 17, bold: true, color: C.white });
  roles.forEach((r, i) => (b += text(x0 + cw0 + cw * i + cw / 2, y0 + 33, r, { size: 17, bold: true, color: C.white })));
  res.forEach((r, j) => {
    const y = y0 + rh * (j + 1);
    b += `<rect x="${x0}" y="${y}" width="${cw0 + cw * 3}" height="${rh}" fill="${j % 2 ? "#E9EEF8" : C.bgBlue}" stroke="#FFFFFF" stroke-width="2"/>` + text(x0 + 16, y + 32, r[0], { anchor: "start", size: 16 });
    [...r[1]].forEach((v, i) => (b += text(x0 + cw0 + cw * i + cw / 2, y + 35, v, { size: 24, bold: true, color: v === "✓" ? C.green : C.red })));
  });
  b += text(x0, y0 + rh * (res.length + 1) + 40, "Enforcement: middleware (session) → route guard requireRole(...) → service layer. Cron routes verify a Google OIDC token or X-Cron-Secret.", { anchor: "start", size: 15, color: C.slate });
  return svg(W, H, b);
}

// ---------- UML helpers ----------
function uml(x, y, w, name, attrs, ops, o = {}) {
  const hh = o.stereo ? 46 : 32, lh = 19;
  const h = hh + attrs.length * lh + 10 + (ops.length ? ops.length * lh + 10 : 6);
  const st = o.stroke || C.blue;
  let s = `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${o.fill || C.bgBlue}" stroke="${st}" stroke-width="1.8"/>`;
  if (o.stereo) s += text(x + w / 2, y + 17, o.stereo, { size: 12, italic: true, color: C.slate });
  s += text(x + w / 2, y + hh - 10, name, { size: 16, bold: true, color: st });
  s += `<line x1="${x}" y1="${y + hh}" x2="${x + w}" y2="${y + hh}" stroke="${st}" stroke-width="1.2"/>`;
  attrs.forEach((a, i) => (s += text(x + 8, y + hh + 18 + i * lh, a, { anchor: "start", size: 12.5 })));
  const yo = y + hh + attrs.length * lh + 10;
  s += `<line x1="${x}" y1="${yo}" x2="${x + w}" y2="${yo}" stroke="${st}" stroke-width="1.2"/>`;
  ops.forEach((a, i) => (s += text(x + 8, yo + 18 + i * lh, a, { anchor: "start", size: 12.5 })));
  return { svg: s, cx: x + w / 2, cy: y + h / 2, w, h, shape: "rect" };
}
function rel(a, b, o = {}) {
  const ta = o.via || [b.cx, b.cy], tb = o.via || [a.cx, a.cy];
  const [x1, y1] = edge(a, ta[0], ta[1]), [x2, y2] = edge(b, tb[0], tb[1]);
  const style = `fill="none" stroke="${C.line}" stroke-width="1.6" ${o.dash ? "stroke-dasharray='7 5'" : ""} ${o.end ? `marker-end="url(#${o.end})"` : ""} ${o.start ? `marker-start="url(#${o.start})"` : ""}`;
  let s = o.via ? `<path d="M${x1},${y1} Q${o.via[0]},${o.via[1]} ${x2},${y2}" ${style}/>` : `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" ${style}/>`;
  const put = (t, px, py, qx, qy) => { if (!t) return ""; const d = Math.hypot(qx - px, qy - py) || 1; const ux = (qx - px) / d, uy = (qy - py) / d; return text(px + ux * 24 - uy * 12, py + uy * 24 + ux * 12 + 4, t, { size: 13, bold: true, color: C.slate }); };
  s += put(o.m1, x1, y1, ta[0], ta[1]) + put(o.m2, x2, y2, tb[0], tb[1]);
  if (o.lab) { const [lx, ly] = o.via ? [0.25 * x1 + 0.5 * o.via[0] + 0.25 * x2, 0.25 * y1 + 0.5 * o.via[1] + 0.25 * y2] : [(x1 + x2) / 2, (y1 + y2) / 2]; s += label(lx, ly - 4, o.lab, { size: 12 }); }
  return s;
}

// ---------- Class diagram: domain ----------
function classDomain() {
  const W = 1810, H = 1110, cw = 232;
  const X = [30, 280, 530, 780, 1030, 1280, 1545];
  const k = {};
  const add = (id, col, y, attrs, ops) => (k[id] = uml(X[col], y, cw, id, attrs, ops));
  add("Product", 0, 20, ["-id : String", "-sku : String", "-name : String", "-isWet : Boolean", "-pricePence : Int", "-unitCostPence : Int"], ["+marginPence() : Int"]);
  add("Site", 2, 20, ["-id : String", "-name : String", "-timezone : String", "-lat : Float", "-lng : Float", "-settings : SiteSettings"], ["+tradingDate(ts) : Date", "+updateSettings(s) : Site"]);
  add("User", 4, 20, ["-id : String", "-email : String", "-passwordHash : String", "-role : Role", "-siteIds : String[*]"], ["+canAccess(action) : Boolean"]);
  add("WeatherDaily", 6, 20, ["-siteId : String", "-date : Date", "-tMax : Float", "-precipMm : Float", "-code : Int", "-source : WeatherSource"], []);
  const r2 = 340;
  add("OrderLine", 0, r2, ["-id : String", "-orderId : String", "-productId : String", "-qty : Int", "-pricePence : Int"], ["+linePence() : Int"]);
  add("Order", 1, r2, ["-id : String", "-externalId : String", "-openedAt : DateTime", "-covers : Int", "-tillId : String"], ["+netPence() : Int"]);
  add("Discount", 2, r2, ["-id : String", "-orderId : String", "-amountPence : Int", "-reason : String", "-managerId : String"], []);
  add("CashUp", 3, r2, ["-id : String", "-date : Date", "-tillId : String", "-expectedCashPence : Int", "-countedCashPence : Int", "-expectedCardPence : Int", "-countedCardPence : Int"], ["+variancePence() : Int"]);
  add("Employee", 4, r2, ["-id : String", "-firstName : String", "-lastInitial : String", "-role : String", "-hourlyRatePence : Int", "-managerCode : String"], ["+displayName() : String"]);
  add("Shift", 5, r2, ["-id : String", "-employeeId : String", "-start : DateTime", "-end : DateTime", "-scheduled : Boolean"], ["+hours() : Float"]);
  add("DailyMetrics", 6, r2, ["-siteId : String", "-date : Date", "-kpis : KpiSet", "-dayparts : Json", "-byManager : Json"], ["+compare(base) : Comparison"]);
  const r3 = 720;
  add("AiCallLog", 0, r3, ["-id : String", "-purpose : String", "-model : String", "-promptHash : String", "-latencyMs : Int", "-guardPassed : Boolean"], []);
  add("Void", 1, r3, ["-id : String", "-orderId : String", "-valuePence : Int", "-reason : String", "-managerId : String"], []);
  add("JobRun", 2, r3, ["-id : String", "-job : JobName", "-siteId : String", "-date : Date", "-status : JobStatus", "-durationMs : Int", "-error : String"], []);
  add("Brief", 3, r3, ["-id : String", "-date : Date", "-kind : BriefKind", "-source : BriefSource", "-content : Json", "-factSheet : Json", "-guard : Json"], ["+render(format) : String"]);
  add("Anomaly", 4, r3, ["-id : String", "-date : Date", "-ruleId : RuleId", "-severity : Severity", "-dimension : String", "-observed : Float", "-expected : Float", "-evidence : Json", "-streak : Int"], []);
  add("Task", 5, r3, ["-id : String", "-anomalyId : String", "-title : String", "-severity : Severity", "-state : TaskState", "-assigneeId : String", "-dueAt : DateTime"], ["+transition(to, actor, note)"]);
  add("TaskNote", 6, r3, ["-id : String", "-taskId : String", "-authorId : String", "-body : String", "-createdAt : DateTime"], []);
  let r = "";
  r += rel(k.Product, k.OrderLine, { m1: "1", m2: "*" });
  r += rel(k.Order, k.OrderLine, { start: "dia", m2: "1..*" });
  r += rel(k.Order, k.Discount, { m1: "1", m2: "*" });
  r += rel(k.Order, k.Void, { m1: "1", m2: "*" });
  r += rel(k.Site, k.Order, { m1: "1", m2: "*" });
  r += rel(k.Site, k.User, { m1: "*", m2: "*" });
  r += rel(k.Employee, k.Shift, { m1: "1", m2: "*" });
  r += rel(k.DailyMetrics, k.Anomaly, { m1: "1", m2: "*", lab: "evaluated into" });
  r += rel(k.Anomaly, k.Task, { m1: "1", m2: "0..1" });
  r += rel(k.Task, k.TaskNote, { start: "dia", m2: "*" });
  r += rel(k.Brief, k.Anomaly, {});
  r += rel(k.JobRun, k.Brief, {});
  let b = "";
  Object.values(k).forEach((n) => (b += n.svg));
  b += text(30, 1085, "Site 1 — * every operational entity (Order, Employee, CashUp, WeatherDaily, DailyMetrics, Anomaly, Brief, JobRun) via siteId; links omitted. JobRun produces 0..1 Brief; Brief cites * Anomaly; Anomaly opens 0..1 Task.", { anchor: "start", size: 14, italic: true, color: C.slate });
  return svg(W, H, r + b);
}

// ---------- Class diagram: services ----------
function classServices() {
  const W = 1840, H = 1010;
  const k = {};
  const add = (id, x, y, w, attrs, ops, o) => (k[id] = uml(x, y, w, id, attrs, ops, o));
  const T = { fill: C.bgTeal, stroke: C.teal }, A = { fill: C.bgAmber, stroke: C.amber };
  add("JobRunner", 60, 40, 330, ["-auth : CronAuth"], ["+runDaily(siteId, date, force) : JobRun", "+runFollowUp(now) : JobRun", "+runWeekly(weekStart) : JobRun"], T);
  add("BriefGenerator", 500, 40, 360, ["-llm : GeminiClient", "-guard : NumberGuard", "-fallback : TemplateBriefWriter"], ["+generate(siteId, date, kind) : Brief"], T);
  add("ChatAgent", 970, 40, 380, ["-llm : GeminiClient", "-tools : ChatTool[*]", "-guard : NumberGuard"], ["+answer(session, question) : Stream", "+confirm(actionId) : Task"], T);
  add("TaskService", 1460, 40, 360, ["-mailer : Mailer"], ["+createFromAnomaly(a) : Task", "+transition(id, to, actor, note) : Task", "+dueForFollowUp(now) : Task[*]"], T);
  add("MetricsEngine", 60, 340, 340, [], ["+computeDay(siteId, date) : DailyMetrics", "+baseline(siteId, date, metric) : Baseline"]);
  add("TemplateBriefWriter", 420, 340, 290, [], ["+write(factSheet) : BriefContent"]);
  add("GeminiClient", 830, 340, 330, ["-apiKey : Secret", "-model : String"], ["+generateStructured(p, schema) : Json", "+chat(msgs, tools) : Stream"], A);
  add("NumberGuard", 1200, 340, 270, ["-tolerance : Float"], ["+check(text, facts) : GuardResult"]);
  add("Mailer", 1510, 340, 290, [], ["+send(msg) : DeliveryResult"], { stereo: "«interface»" });
  add("AnomalyEngine", 60, 600, 340, ["-rules : AnomalyRule[*]"], ["+evaluate(m, base, settings) : Anomaly[*]"]);
  add("AnomalyRule", 470, 600, 300, ["+id : RuleId"], ["+evaluate(m, base, s) : Anomaly[*]"], { stereo: "«interface»" });
  add("FactSheetBuilder", 830, 600, 340, [], ["+build(metrics, anomalies, outlook) : FactSheet"]);
  add("OutlookService", 1220, 600, 260, ["-weather : WeatherClient"], ["+forecast(siteId, date) : Outlook"]);
  add("SendGridMailer", 1530, 600, 270, ["-apiKey : Secret"], ["+send(msg) : DeliveryResult"], A);
  add("DiscountSpikeRule", 250, 850, 220, [], ["AR-01"], { fill: C.white });
  add("LabourOverTargetRule", 490, 850, 230, [], ["AR-03"], { fill: C.white });
  add("CashVarianceRule", 740, 850, 250, [], ["AR-07 (… AR-01 – AR-09)"], { fill: C.white });
  add("WeatherClient", 1180, 850, 340, [], ["+forecast(lat, lng, date) : Weather", "+history(lat, lng, from, to) : Weather[*]"], A);
  let r = "";
  const dep = (a, b2, o = {}) => (r += rel(k[a], k[b2], { dash: true, end: "open", ...o }));
  dep("JobRunner", "BriefGenerator"); dep("JobRunner", "MetricsEngine");
  dep("JobRunner", "AnomalyEngine", { via: [-40, 420] });
  dep("JobRunner", "TaskService", { via: [940, -40] });
  dep("BriefGenerator", "TemplateBriefWriter"); dep("BriefGenerator", "GeminiClient"); dep("BriefGenerator", "NumberGuard");
  dep("BriefGenerator", "FactSheetBuilder", { via: [775, 520] });
  dep("ChatAgent", "GeminiClient"); dep("ChatAgent", "NumberGuard"); dep("ChatAgent", "MetricsEngine", { lab: "tool queries" });
  dep("AnomalyEngine", "MetricsEngine", { lab: "baselines" });
  dep("FactSheetBuilder", "OutlookService"); dep("OutlookService", "WeatherClient"); dep("TaskService", "Mailer");
  r += rel(k.AnomalyEngine, k.AnomalyRule, { start: "dia", m2: "1..*" });
  ["DiscountSpikeRule", "LabourOverTargetRule", "CashVarianceRule"].forEach((c) => (r += rel(k[c], k.AnomalyRule, { dash: true, end: "tri" })));
  r += rel(k.SendGridMailer, k.Mailer, { dash: true, end: "tri" });
  let b = "";
  Object.values(k).forEach((n) => (b += n.svg));
  return svg(W, H, r + b);
}

// ---------- Sequence helper ----------
function sequence(lanes, ext, msgs, W, H) {
  let b = "";
  const X = lanes.map((_, i) => 110 + i * ((W - 220) / (lanes.length - 1)));
  let body = "";
  let y = 120;
  msgs.forEach((m) => {
    if (m.gap) { y += m.gap; return; }
    if (m.frame) {
      const x = X[m.from] - 70, w = X[m.to] - X[m.from] + 140, fw = m.frame.length * 9 + 22;
      body += `<rect x="${x}" y="${y - 30}" width="${w}" height="${m.rows * 48 + 20}" fill="none" stroke="${C.slate}" stroke-width="1.5"/><rect x="${x}" y="${y - 30}" width="${fw}" height="22" fill="${C.bgGrey}" stroke="${C.slate}"/>` +
        text(x + 8, y - 14, m.frame, { anchor: "start", size: 13, bold: true }) + text(x + fw + 10, y - 14, m.label, { anchor: "start", size: 13, italic: true, color: C.slate });
      y += 14; return;
    }
    const [a, c, t, ret] = m;
    if (a === c) {
      body += `<path d="M${X[a]},${y} h40 v22 h-36" fill="none" stroke="${C.teal}" stroke-width="2" marker-end="url(#arrT)"/>` + label(X[a] + 50, y + 15, t, { anchor: "start", size: 14 });
      y += 56;
    } else {
      body += arrow(X[a], y, X[c] + (c > a ? -4 : 4), y, "", { dash: ret, teal: !ret });
      body += label((X[a] + X[c]) / 2, y - 8, t, { size: 14 });
      y += 48;
    }
  });
  const Hh = Math.max(H, y + 10);
  lanes.forEach((l, i) => {
    const e = ext.includes(i);
    b += `<line x1="${X[i]}" y1="74" x2="${X[i]}" y2="${Hh - 20}" stroke="${C.line}" stroke-width="1.5" stroke-dasharray="5 5"/>`;
    b += box(X[i] - 95, 20, 190, 54, l, [], { fs: 15, fill: e ? C.bgAmber : C.bgNavy, stroke: e ? C.amber : C.navy });
  });
  return svg(W, Hh, b + body);
}
function seqDaily() {
  return sequence(["Cloud Scheduler", "/api/cron/daily", "Metrics + Anomaly", "Open-Meteo", "Gemini API", "Number Guard", "Neon DB", "SendGrid"], [3, 4, 7], [
    [0, 1, "1. POST (OIDC token)"], [1, 6, "2. JobRun lock (site, date) — skip if done"], [1, 2, "3. build DailyMetrics(D-1) + baselines"],
    [2, 6, "4. aggregate orders, shifts, discounts, cash-ups"], [2, 2, "5. evaluate anomaly rules"], [2, 6, "6. upsert Anomalies → Tasks"],
    [1, 3, "7. forecast(lat, long, D+1)"], [3, 1, "8. temp, precip, weather code", true], [1, 1, "9. assemble FactSheet (ids per figure)"],
    [1, 4, "10. generateContent(FactSheet, responseSchema)"], [4, 1, "11. JSON brief { headline, sections, actions, factIds }", true],
    [1, 5, "12. validate every number ∈ FactSheet"], [5, 1, "13. pass | fail → retry once → template fallback", true],
    [1, 6, "14. save Brief + AiCallLog"], [1, 7, "15. send HTML brief to recipients"], [7, 1, "16. 202 Accepted", true],
    [1, 6, "17. JobRun = success"], [1, 0, "18. 200 OK", true],
  ], 1700, 980);
}
function seqAuth() {
  return sequence(["User", "Browser (UI)", "Middleware", "/api/auth (NextAuth)", "Neon DB"], [], [
    [0, 1, "1. enter email + password"], [1, 3, "2. POST /api/auth/callback/credentials"], [3, 4, "3. findUser(email)"], [4, 3, "4. user row | null", true],
    [3, 3, "5. bcrypt.compare(password, hash)"],
    { frame: "alt", label: "[invalid credentials]", from: 0, to: 3, rows: 1 },
    [3, 1, "6a. 401 — \"Email or password is incorrect\"", true], { gap: 30 },
    { frame: "alt", label: "[valid credentials]", from: 0, to: 3, rows: 2 },
    [3, 1, "6b. Set-Cookie: signed session (role, siteIds)", true], [1, 0, "7. redirect → Morning Dashboard", true], { gap: 30 },
    [1, 2, "8. GET /api/metrics (cookie)"], [2, 2, "9. verify session; requireRole()"], [2, 1, "10. 200 data | 401 expired | 403 forbidden", true],
  ], 1500, 860);
}
function seqChat() {
  return sequence(["Manager", "Chat UI", "/api/chat", "ChatAgent", "Gemini API", "Analytics tools", "Number Guard"], [4], [
    [0, 1, "1. \"Why were discounts high on Saturday?\""], [1, 2, "2. POST question (session)"], [2, 3, "3. answer(session, question)"],
    [3, 4, "4. generateContent(history ≤ 10, tool declarations)"], [4, 3, "5. functionCall get_discounts_breakdown(...)", true],
    [3, 5, "6. validate args → run query"], [5, 3, "7. rows by manager / daypart", true], [3, 4, "8. functionResponse(results)"],
    [4, 3, "9. answer text (+ proposed create_task)", true], [3, 6, "10. check numbers ∈ tool results"], [6, 3, "11. pass | fail → table fallback", true],
    [3, 1, "12. stream answer + confirmation card", true], [0, 1, "13. confirm \"Create task\""], [1, 2, "14. POST /api/tasks"], [2, 1, "15. 201 task created", true],
  ], 1600, 860);
}

// ---------- State charts ----------
const stateNode = (x, y, w, h, t, sub, o = {}) => box(x, y, w, h, t, sub ? [sub] : [], { rx: 26, fill: o.fill || C.bgBlue, stroke: o.stroke || C.blue, fs: 17 });
const startDot = (x, y) => `<circle cx="${x}" cy="${y}" r="13" fill="${C.ink}"/>`;
const endDot = (x, y) => `<circle cx="${x}" cy="${y}" r="15" fill="none" stroke="${C.ink}" stroke-width="2.5"/><circle cx="${x}" cy="${y}" r="9" fill="${C.ink}"/>`;
function stateTask() {
  const W = 1500, H = 740;
  let a = "", b = startDot(90, 340);
  b += stateNode(230, 290, 230, 100, "Open", "due next day 12:00");
  b += stateNode(640, 110, 250, 100, "Acknowledged", "being investigated");
  b += stateNode(1080, 290, 230, 100, "Resolved", "note ≥ 10 chars");
  b += box(640, 470, 250, 115, "Dismissed", ["reason + note", "\"expected\" ⇒ mute rule 7 days"], { rx: 26, fill: C.bgGrey, stroke: C.slate, fs: 17 });
  b += endDot(1420, 340);
  a += arrow(104, 340, 225, 340, "created", { lx: 165, ly: 325 });
  a += arrow(420, 285, 635, 175, "acknowledge()", { lx: 500, ly: 215 });
  a += arrow(465, 340, 1075, 340, "resolve(note)", { lx: 770, ly: 332 });
  a += arrow(890, 175, 1110, 285, "resolve(note)", { lx: 1030, ly: 215 });
  a += arrow(420, 395, 635, 520, "dismiss(reason) [Owner]", { lx: 505, ly: 490, anchor: "end" });
  a += arrow(765, 215, 765, 475, "dismiss [Owner]", { lx: 775, ly: 430, anchor: "start" });
  a += arrow(1315, 340, 1402, 340, "");
  a += `<path d="M1195,395 C1195,700 345,700 345,398" fill="none" stroke="${C.line}" stroke-width="2" stroke-dasharray="6 5" marker-end="url(#arr)"/>` + label(760, 632, "reopen(note) [Owner]");
  a += `<path d="M270,290 C240,190 430,190 410,286" fill="none" stroke="${C.teal}" stroke-width="2" marker-end="url(#arrT)"/>` + label(340, 200, "16:00 [critical ∧ open > 8 h] / nudge", { size: 13 });
  
  b += text(60, 300, "anomaly ≥ warning / manual", { anchor: "start", size: 13, color: C.slate });
  return svg(W, H, a + b);
}
function stateBrief() {
  const W = 1600, H = 850;
  let a = "", b = startDot(70, 170);
  b += stateNode(140, 120, 220, 100, "Pending", "job triggered");
  b += stateNode(470, 120, 240, 100, "BuildingFacts", "metrics · anomalies · outlook");
  b += stateNode(820, 120, 240, 100, "AwaitingAI", "Gemini, timeout 20 s");
  b += stateNode(1170, 120, 240, 100, "Validating", "schema + Number Guard");
  b += stateNode(1170, 380, 240, 100, "Ready (ai)", "source = ai", { fill: C.bgTeal, stroke: C.teal });
  b += stateNode(820, 380, 240, 100, "TemplateFallback", "deterministic writer", { fill: C.bgAmber, stroke: C.amber });
  b += stateNode(820, 610, 240, 100, "Ready (template)", "source = template", { fill: C.bgTeal, stroke: C.teal });
  b += stateNode(1170, 610, 240, 100, "Emailing", "retry ≤ 3, back-off");
  b += stateNode(140, 380, 220, 100, "Skipped", "no trading data", { fill: C.bgGrey, stroke: C.slate });
  b += box(1180, 775, 220, 50, "DeliveryFailed", [], { rx: 26, fill: C.bgGrey, stroke: C.red, fs: 15 });
  b += endDot(1520, 660) + endDot(250, 570);
  a += arrow(84, 170, 135, 170, "");
  a += arrow(365, 170, 465, 170, "data present");
  a += arrow(250, 225, 250, 375, "no DailyMetrics", { lx: 260, ly: 305, anchor: "start" });
  a += arrow(715, 170, 815, 170, "FactSheet ready");
  a += arrow(1065, 170, 1165, 170, "response");
  a += arrow(1290, 225, 1290, 375, "pass", { lx: 1300, ly: 305, anchor: "start" });
  a += `<path d="M1230,118 C1180,40 940,40 900,114" fill="none" stroke="${C.line}" stroke-width="2" marker-end="url(#arr)"/>` + label(1065, 55, "fail [attempt = 1] / retry with offending tokens");
  a += arrow(1180, 225, 1010, 375, "fail [attempt = 2]", { lx: 1110, ly: 300, anchor: "start" });
  a += arrow(900, 225, 900, 375, "error / timeout / 429", { lx: 890, ly: 305, anchor: "end" });
  a += arrow(940, 485, 940, 605, "written", { lx: 950, ly: 550, anchor: "start" });
  a += arrow(1290, 485, 1290, 605, "persist Brief", { lx: 1300, ly: 550, anchor: "start" });
  a += arrow(1065, 660, 1165, 660, "persist Brief");
  a += arrow(1415, 660, 1502, 660, "") + label(1458, 645, "sent", { size: 12 });
  a += arrow(1290, 715, 1290, 770, "") + label(1300, 750, "3 failures / log + show in UI", { size: 12, anchor: "start" });
  a += arrow(250, 485, 250, 550, "");
  return svg(W, H, a + b);
}

// ---------- Pipeline overview (large type, for the summary document) ----------
function pipeline() {
  const W = 1500, H = 490, bw = 200, X = [38, 283, 528, 773, 1018, 1263];
  const o = { fs: 22, ss: 16, lh: 26 };
  let b = "";
  b += `<rect x="20" y="108" width="968" height="190" rx="14" fill="${C.bgTeal}" opacity="0.55"/>` + text(30, 134, "Deterministic backend - owns the numbers", { anchor: "start", size: 17, bold: true, color: C.teal });
  b += `<rect x="1003" y="108" width="477" height="190" rx="14" fill="${C.bgAmber}" opacity="0.7"/>` + text(1013, 134, "AI layer - explains, then is verified", { anchor: "start", size: 17, bold: true, color: C.amber });
  const row1 = [["POS data", "simulator · CSV import"], ["Metrics engine", "KPIs · baselines"], ["Anomaly rules", "9 rules · attribution"], ["FactSheet", "id-tagged facts only"], ["Gemini API", "brief · chat tools"], ["Number Guard", "verify every number"]];
  row1.forEach((r, i) => (b += box(X[i], 150, bw, 125, r[0], [r[1]], { ...o, fill: C.white, stroke: i >= 4 ? C.amber : i === 0 ? C.slate : C.teal })));
  for (let i = 0; i < 5; i++) b += arrow(X[i] + bw + 2, 212, X[i + 1] - 4, 212, "");
  b += box(283, 16, 445, 64, "Cloud Scheduler", ["07:00 brief · 16:00 follow-up · Mon 08:00 recap"], { ...o, fs: 20, ss: 15, lh: 22, fill: C.bgGrey, stroke: C.slate });
  b += arrow(440, 82, 440, 146, "", { teal: true });
  const row2 = [[0, "Open-Meteo", "weather history + forecast", C.amber], [2, "Investigation tasks", "auto-created · chased", C.teal], [3, "Dashboard & chat", "Next.js UI", C.navy], [5, "Email (SendGrid)", "07:00 brief · nudges", C.amber]];
  row2.forEach(([c, t, s, col]) => (b += box(X[c], 350, bw, 110, t, [s], { ...o, fs: 20, ss: 15, fill: C.white, stroke: col })));
  b += arrow(200, 346, 330, 279, "");
  b += arrow(628, 279, 628, 346, "");
  b += arrow(730, 405, 769, 405, "");
  b += arrow(1363, 279, 1363, 346, "");
  b += arrow(1290, 279, 977, 380, "") + label(1120, 350, "verified brief", { size: 15 });
  return svg(W, H, b);
}

const figs = {
  fig_pipeline: pipeline,
  fig_context: context, fig_dfd: dfd, fig_usecases: usecases, fig_component: component, fig_deployment: deployment,
  fig_access: access, fig_class_domain: classDomain, fig_class_services: classServices, fig_seq_auth: seqAuth,
  fig_seq_daily: seqDaily, fig_seq_chat: seqChat, fig_state_task: stateTask, fig_state_brief: stateBrief,
};
for (const [name, fn] of Object.entries(figs)) fs.writeFileSync(path.join(__dirname, name + ".svg"), fn());
console.log("SVGs written:", Object.keys(figs).length);
