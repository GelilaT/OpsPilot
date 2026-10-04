// Builds OpsPilot_SRS_Summary.docx: cover page + a 3-page summary of the full SRS (v1.1).
// Run: node build_srs_summary.js
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun, Footer,
  AlignmentType, HeadingLevel, LevelFormat, BorderStyle, WidthType, ShadingType, PageNumber, VerticalAlign,
} = require("docx");

const AUTHOR = "Gelila Tefera";
const FONT = "Calibri";
const ACCENT = "4A86E8", HEAD_FILL = "4472C4", ROW_A = "D9E2F3", ROW_B = "E9EFF7", GRID = "8EAADB", MUTED = "595959";
const PAGE_W = 11906, PAGE_H = 16838, MARGIN = 1021; // A4, 1.8 cm
const CW = PAGE_W - 2 * MARGIN;
const BODY = 20, SMALL = 18; // half-points

const run = (text, o = {}) => new TextRun({ text, font: FONT, ...o });
const rich = (text, o = {}) => String(text).split(/(\*\*[^*]+\*\*)/).filter(Boolean).map((s) =>
  s.startsWith("**") ? run(s.slice(2, -2), { ...o, bold: true }) : run(s, o));
const p = (t, o = {}) => new Paragraph({ children: rich(t, { size: BODY, ...(o.run || {}) }), spacing: { after: o.after ?? 100, line: 264 } });
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [run(t)], keepNext: true });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [run(t)], keepNext: true });
const bullets = (arr) => arr.map((t) => new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: rich(t, { size: BODY }), spacing: { after: 50, line: 259 } }));
const steps = (arr) => arr.map((t) => new Paragraph({ numbering: { reference: "steps", level: 0 }, children: rich(t, { size: BODY }), spacing: { after: 50, line: 259 } }));

const bd = { style: BorderStyle.SINGLE, size: 4, color: GRID };
const borders = { top: bd, bottom: bd, left: bd, right: bd };
function table(headers, rows, weights) {
  const total = weights.reduce((a, b) => a + b, 0);
  const w = weights.map((x) => Math.floor((x / total) * CW));
  w[w.length - 1] += CW - w.reduce((a, b) => a + b, 0);
  const cell = (t, i, o = {}) => new TableCell({
    borders, width: { size: w[i], type: WidthType.DXA }, verticalAlign: VerticalAlign.CENTER,
    shading: { fill: o.fill, type: ShadingType.CLEAR, color: "auto" }, margins: { top: 35, bottom: 35, left: 90, right: 90 },
    children: [new Paragraph({ children: rich(t, { size: SMALL, bold: o.bold, color: o.color }) })],
  });
  const trs = [new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, i, { fill: HEAD_FILL, bold: true, color: "FFFFFF" })) })];
  rows.forEach((r, ri) => trs.push(new TableRow({ cantSplit: true, children: r.map((c, i) => cell(c, i, { fill: ri % 2 ? ROW_B : ROW_A, bold: i === 0 })) })));
  return [new Table({ width: { size: CW, type: WidthType.DXA }, columnWidths: w, rows: trs }), new Paragraph({ spacing: { after: 80 }, children: [] })];
}
function figure(file, caption, widthPx) {
  const png = fs.readFileSync(path.join(__dirname, "diagrams", file));
  const w = png.readUInt32BE(16), h = png.readUInt32BE(20), s = widthPx / w;
  return [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 60 }, keepNext: true, children: [new ImageRun({ type: "png", data: png, transformation: { width: widthPx, height: Math.round(h * s) }, altText: { title: caption, description: caption, name: file } })] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 100 }, children: [run(caption, { size: SMALL, color: ACCENT })] }),
  ];
}

// ---------------- cover ----------------
const cover = [
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 2600, after: 200 }, children: [run("Software Requirements Specification - Summary", { size: 32 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: [run("OpsPilot", { size: 64, bold: true, color: ACCENT })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 1800 }, children: [run("AI Restaurant Operations & Margin Management Platform", { size: 30, color: MUTED })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 }, children: [run("OPSPILOT-SRS-002 · Summary v2.0 · October 2026", { size: 22, color: MUTED })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 }, children: [run(`Prepared by ${AUTHOR}`, { size: 22, color: MUTED })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 }, children: [run("Prepared for Brain3.ai - AI Automation Assignment (Full Stack AI Web Developer)", { size: 22, color: MUTED })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [run("Full detail: OpsPilot Software Requirements Specification v2.0", { size: 20, italics: true, color: MUTED })] }),
];

// ---------------- body ----------------
const body = [
  new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [run("1. Role & Industry")] }),
  p("**Operations and margin manager for independent and small multi-site restaurants (UK hospitality).** Food and labour eat 55-65% of a restaurant's revenue, and margin leaks quietly: a supplier adds 18% to chicken and nobody reprices the dishes; a short delivery causes a Friday stock-out; stock is over-ordered and binned. The data to catch this exists - supplier invoices, POS sales, recipes, stock counts - but it lives in PDFs and spreadsheets and nobody joins it up daily. OpsPilot does that joining-up: it reads, reconciles, explains and proposes; managers approve."),
  p("It runs a closed loop: **Ingest → Understand → Detect → Investigate → Predict → Recommend → Automate → Measure**. Every number comes from deterministic, tested backend code; Gemini is used only where language is the problem - reading documents and explaining evidence - and is always checked.", { after: 60 }),
  ...figure("v2_loop.png", "Figure 1: The OpsPilot operating loop", 640),

  H1("2. Tasks Automated"),
  ...table(["Capability", "What OpsPilot does"], [
    ["AI invoice processing", "Upload PDF/photo → byte-level checks and SHA-256 duplicate gate → Gemini classification (confidence gate 0.6) → structured extraction → Python validation (line maths, VAT, totals recomputed, unit/pack normalisation) → supplier and line matching with learned aliases → price check vs last price and 90-day median → PO quantity/price match → fuzzy duplicate check → exception-based review → role-limited approval → posts stock receipts and price history. Fully audited state machine."],
    ["Supplier & procurement", "Normalised price history, supplier ranking (price, fill rate, lead time), cost-increase attribution by supplier, order-up-to purchase quantities with safety stock, pack/MOQ rounding, draft POs that are committed only after approval; recommendation accuracy tracked."],
    ["Inventory & waste", "Append-only stock ledger (receipts, theoretical consumption from sales × recipes, counts, waste); usage variance actual vs theoretical; days of cover, stock-out and overstock risk."],
    ["Demand forecasting", "Item × daypart forecast for 14 days: weighted weekday baseline × trend × weather, bank-holiday and event factors (ridge regression), p10/p50/p90, rolling backtests (WAPE targets 15% site / 30% item). Deterministic and testable."],
    ["Menu & margin", "Recipe costing from live invoice prices, GP %, contribution margin, menu engineering (Star/Plowhorse/Puzzle/Dog), margin decline and cost inflation alerts, repricing what-if."],
    ["Root-cause investigation", "Driver decomposition (revenue = orders × spend, LMDI mix/price split, day × daypart), 10 hypothesis tests joining stock, invoices, suppliers, labour, weather, leakage and memory; confidence-scored causes; evidence chain narrated by Gemini under a Number Guard."],
    ["Action Centre", "Recommendations (PO, supplier switch, par level, price review, staffing, waste) with evidence, computed weekly impact, risk, approver, expiry → idempotent execution → follow-up → outcome measured against a counterfactual."],
    ["Operational memory", "Investigations, notes, causes, actions and outcomes stored as structured records; retrieval by entity/cause + pgvector similarity + recency; recurring problems escalated."],
  ], [20, 80]),

  H1("3. Implementation"),
  ...table(["Layer", "Technology"], [
    ["Frontend", "Next.js 15 (App Router), TypeScript, Tailwind CSS, Recharts; typed client generated from the API's OpenAPI schema; Better Auth (sessions, roles, short-lived JWT)."],
    ["Backend", "Independent FastAPI service: Pydantic v2, SQLAlchemy 2 (async), Alembic; bounded contexts with hexagonal ports/adapters; RFC 7807 errors, idempotency keys, optimistic concurrency, append-only audit; JWT verified via JWKS with role + site scoping."],
    ["Workflows", "Worker service running Procrastinate (PostgreSQL job queue): idempotent steps, retries, dead-letter list, transactional outbox; one Cloud Scheduler dispatcher (every 5 min) drives site-timezone schedules."],
    ["Data", "Neon PostgreSQL + pgvector; invoice originals in private Cloud Storage (signed URLs); money in integer minor units, quantities as Decimal with units."],
    ["Quality", "pytest, property-based tests for money/units, golden invoice fixtures, forecast backtests, testcontainers integration tests, e2e demo scenarios; ruff, pyright, import-linter, GitHub Actions."],
  ], [14, 86]),
  H2("Third-party APIs (all free, no credit card)"),
  ...table(["Service", "Used for"], [
    ["Google Gemini API", "Invoice classification and extraction (structured output), evidence narration, chat tool calling, embeddings for memory"],
    ["Open-Meteo", "Weather forecast and history for demand factors"],
    ["gov.uk Bank Holidays", "UK holiday calendar for forecasting"],
    ["SendGrid (Resend fallback)", "Daily brief, approval and risk alerts, approved POs to suppliers"],
    ["Cloud Run + Cloud Scheduler", "web, api and worker services; one dispatcher job"],
  ], [28, 72]),
  H2("Trustworthy AI by design"),
  ...bullets([
    "**AI output is a proposal, not a fact:** schema-validated, confidence-gated, then every invoice number is recomputed and checked in Python; documents are treated as data (prompt-injection defence).",
    "**AI never calculates:** forecasts, costs, impacts and confidence are deterministic; Gemini only explains facts the backend built, and the Number Guard rejects any unverified number.",
    "**History only from records:** \"this happened before\" is cited only from retrieved memory entries.",
  ]),

  H1("4. Automation & User Interaction"),
  p("**Worked example (seeded demo):** Supplier A's invoice shows chicken thigh +18% and 12 kg delivered against a 20 kg PO → OpsPilot flags price_increase and qty_mismatch before approval → Friday revenue falls 18% → the investigation shows orders flat, spend -14%, chicken dishes -37%, 82% in Friday dinner, stock-out at 18:40, caused by the short delivery, and recalls a similar case on 19 Sep (confidence 0.86) → the Action Centre proposes switching to Supplier B (+£84/week), raising the par level and a Chicken Wrap price review (GP 68.1% → 64.3%) → the GM approves, a draft PO is created → after 7 days chicken cost per kg is measured -8.7% vs counterfactual: improved, stored in memory."),
  ...table(["Schedule (site time)", "Automated work"], [
    ["02:00 nightly", "Metrics, theoretical consumption, forecast, procurement plan, margins, detection, investigations, recommendations"],
    ["06:00", "Measure outcomes of executed recommendations"],
    ["07:00", "Daily brief email: KPIs, margin moves, invoices to review, risks, pending approvals, outcomes"],
    ["16:00 / Monday 08:00", "Approval and task follow-ups / weekly margin bridge"],
    ["On upload", "Invoice pipeline: classify → extract → validate → match → review"],
  ], [24, 76]),
  p("**Screens:** Morning Dashboard · Invoice inbox and side-by-side review · Suppliers & prices · Inventory (mobile counts, waste, variance) · Forecast & procurement · Menu & margins matrix · Investigation evidence chain · Action Centre · Ask OpsPilot (tool-restricted chat with confirmation) · Settings & audit. Roles: Owner, GM, Head Chef, Shift Manager, with approval limits."),

  H1("5. Why It Works"),
  ...bullets([
    "**Measurable money outcomes:** price increases caught on the invoice, true dish margins daily, fewer stock-outs and less waste, and every action measured against a counterfactual.",
    "**A real workflow system, not a dashboard:** state machines, approvals, idempotent execution, ledgers and audit - the parts that make automation trustworthy for money.",
    "**AI where it adds value, maths where it must be right:** document understanding and explanation from Gemini; every number from tested code.",
    "**It learns:** confirmed line mappings, outcomes and root causes feed memory and future investigations.",
    "**Full-stack depth:** independent FastAPI service, worker, PostgreSQL design and a responsive Next.js UI, all on free tiers.",
  ]),
  p("**Delivery:** foundations → demo MVP slice (invoice-to-outcome for the chicken scenario across every loop stage) → breadth (forecasting, inventory variance, menu matrix, chat) → hardening. Full requirements (119 functional, traced), class design and 19 diagrams are in SRS v2.0.", { run: { color: MUTED } }),
];

const footer = new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ font: FONT, size: 18, color: MUTED, children: [PageNumber.CURRENT] })] })] });
const lvl = (text, fmt) => [{ level: 0, format: fmt, text, alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 460, hanging: 280 } } } }];

const doc = new Document({
  creator: AUTHOR, title: "OpsPilot v2 - SRS Summary",
  styles: {
    default: { document: { run: { font: FONT, size: BODY } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 28, font: FONT, color: ACCENT }, paragraph: { spacing: { before: 200, after: 90 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 22, bold: true, font: FONT, color: ACCENT }, paragraph: { spacing: { before: 120, after: 60 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [
    { reference: "bullets", levels: lvl("●", LevelFormat.BULLET) },
    { reference: "steps", levels: lvl("%1.", LevelFormat.DECIMAL) },
  ] },
  sections: [{
    properties: { titlePage: true, page: { size: { width: PAGE_W, height: PAGE_H }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN, footer: 500 }, pageNumbers: { start: 0 } } },
    footers: { default: footer, first: new Footer({ children: [new Paragraph({ children: [] })] }) },
    children: [...cover, ...body],
  }],
});

const out = path.join(__dirname, "OpsPilot_SRS_Summary_v2.docx");
Packer.toBuffer(doc).then((b) => { fs.writeFileSync(out, b); console.log("Wrote", out); });
