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
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 1800 }, children: [run("AI Operations Manager for Independent Restaurants", { size: 30, color: MUTED })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 }, children: [run("OPSPILOT-SRS-001 · Summary v1.0 · October 2026", { size: 22, color: MUTED })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 }, children: [run(`Prepared by ${AUTHOR}`, { size: 22, color: MUTED })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 }, children: [run("Prepared for Brain3.ai - AI Automation Assignment (Full Stack AI Web Developer)", { size: 22, color: MUTED })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [run("Full detail: OpsPilot Software Requirements Specification v1.1", { size: 20, italics: true, color: MUTED })] }),
];

// ---------------- body ----------------
const body = [
  new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [run("1. Role & Industry")] }),
  p("**Operations manager for independent and small multi-site restaurants (hospitality).** OpsPilot does the daily analysis and follow-up work of an operations manager: it reviews yesterday's trading, finds what went wrong, explains why, assigns an investigation and chases it until it is resolved. It also plans tomorrow's staffing and prep."),
  H2("Why this role"),
  ...bullets([
    "**Thin margins:** independent restaurants typically run on 3-6% net margin, so labour creep, a manager over-discounting or a till that is regularly short can erase a month's profit.",
    "**Problems are found too late:** owners and GMs rarely have the time (or budget for an operations manager) to check the numbers daily, so leakage is discovered at month-end, if at all.",
    "**Dashboards are not enough:** POS reports show numbers but do not explain, prioritise or follow up. The valuable work is the judgement-and-follow-up loop, which is repetitive, data-heavy and time-critical - ideal for an AI agent.",
    "**Grounded in real experience:** the design draws on the author's work building finance and trading analytics for multi-site hospitality operators.",
  ]),

  H1("2. Tasks Automated"),
  p("The role was broken down into sub-functions and prioritised by impact and feasibility with free APIs:", { after: 60 }),
  ...table(["Role task", "What OpsPilot does", "Priority"], [
    ["Morning trading review", "Computes revenue, covers, spend per cover, GP %, labour %, prime cost, discounts, voids and cash-up variance vs last week, the 4-week median and targets. Gemini writes a short Daily Operations Brief.", "P0"],
    ["Spot leakage and cost creep", "9 deterministic anomaly rules (discount and void spikes, labour over target, daypart and product drops, cash variance, COGS drift), each attributed to a manager, daypart, product or till.", "P0"],
    ["Report before service", "Emails the verified brief to the owner at 07:00, without anyone opening the app.", "P0"],
    ["Assign and chase investigations", "Every warning or critical anomaly becomes a task (Open → Acknowledged → Resolved / Dismissed). Critical tasks still open after 8 hours trigger a 16:00 nudge.", "P1"],
    ["Plan tomorrow", "Weather forecast + same-weekday history → expected revenue and covers range, a labour-hours cap for the target labour %, and prep hints for weather-sensitive items.", "P1"],
    ["Answer ad-hoc questions", "\"Ask OpsPilot\" chat using Gemini function calling over whitelisted analytics tools; it can propose a task, which runs only after the user confirms.", "P1"],
    ["Weekly recap", "Monday 08:00 email: week vs previous week, anomalies opened and resolved, top and bottom products.", "P2"],
  ], [22, 68, 10]),
  p("**Out of scope for v1:** rota building, supplier ordering, payroll and live POS integrations (a POS simulator and CSV import stand in for the till)."),

  H1("3. Implementation"),
  p("OpsPilot is a single Next.js application on Google Cloud Run. The key design decision is that **the backend owns the numbers and Gemini owns the explanation**: every figure is computed by code, and the AI only turns verified facts into plain English."),
  ...table(["Layer", "Technology"], [
    ["Frontend", "Next.js 15 (App Router), React, TypeScript, Tailwind CSS, Recharts; responsive and mobile-first."],
    ["Backend", "Next.js route handlers with Zod validation, Prisma ORM, Neon PostgreSQL; Better Auth (email/password, Owner and Manager roles)."],
    ["AI", "Gemini 2.5 Flash: structured JSON output for briefs, function calling for chat."],
    ["Automation", "Cloud Scheduler (3 jobs) calling secured Cloud Run endpoints; GitHub Actions cron as a fallback trigger."],
    ["Data", "Deterministic POS simulator (~120 days: 40-item menu, orders, staff shifts, discounts, voids, cash-ups) using real Open-Meteo weather history, with five planted scenarios so every rule can be demonstrated; CSV import for real POS exports."],
  ], [16, 84]),
  ...figure("fig_pipeline.png", "Figure 1: How OpsPilot works", 650),
  H2("Third-party APIs (all free, no credit card)"),
  ...table(["Service", "Used for", "Free-tier limit / expected use"], [
    ["Gemini API (Google AI Studio)", "Brief narrative; chat with tool calling", "Free tier; budgeted at ≤ 60 requests/day"],
    ["Open-Meteo", "Weather forecast and history for the outlook", "No API key; < 10,000 calls/day (uses ~10)"],
    ["SendGrid", "Daily brief, follow-up nudges, weekly recap", "Free allowance; ~40 emails/month (Resend is a drop-in alternative)"],
    ["Cloud Run + Cloud Scheduler", "Hosting and proactive jobs", "180,000 vCPU-seconds/month; 3 scheduler jobs (exactly what is used)"],
    ["Neon PostgreSQL", "Database", "~0.5 GB free (demo uses ~40 MB)"],
  ], [26, 36, 38]),
  H2("Trustworthy AI: no made-up numbers"),
  ...steps([
    "The backend computes every metric and anomaly, then builds a **FactSheet** of id-tagged facts with display strings (e.g. lab.pct = \"31.2%\"). Raw transactions and staff surnames are never sent to the AI.",
    "Gemini receives only the FactSheet and must return schema-valid JSON (headline, sections, actions) that cites fact ids.",
    "A **Number Guard** checks every number in the text against the FactSheet. On failure it retries once, then falls back to a deterministic template brief. Chat answers are checked against the tool results they used.",
  ]),

  H1("4. Automation & User Interaction"),
  ...table(["Scheduled job", "When", "What the agent does"], [
    ["daily-brief", "Daily 07:00", "Recompute metrics → detect anomalies → open tasks → build outlook → write and verify brief → email the owner"],
    ["task-follow-up", "Daily 16:00", "Email a nudge for critical tasks still open after 8 hours"],
    ["weekly-recap", "Monday 08:00", "Email the weekly performance recap"],
  ], [18, 16, 66]),
  p("Jobs are idempotent (one run per site and date), authenticated with an OIDC token and logged for audit, so a retry never sends a duplicate email."),
  H2("User interface"),
  ...bullets([
    "**Morning Dashboard:** KPI cards with deltas (arrow and sign, not colour alone), the AI brief clearly labelled with its cited facts, a \"Needs attention\" list and tomorrow's outlook.",
    "**Anomaly Detail:** observed vs expected, a 28-day chart with the baseline band, the contributor breakdown and the linked task.",
    "**Investigations board:** Kanban of tasks with notes; acknowledge, resolve or dismiss (dismissing as \"expected\" mutes that rule for 7 days).",
    "**Ask OpsPilot:** streaming chat on every screen that shows which tools it used; actions need confirmation.",
    "**Settings & Data:** targets, thresholds and recipients; \"Simulate next day\" and \"Run job now\" drive the live demo.",
  ]),

  H1("5. Why It Works"),
  ...bullets([
    "**Measurable outcomes:** the daily numbers review drops from 30-60 minutes to under 5, and leakage or labour creep surfaces within 24 hours instead of at month-end.",
    "**Acts, not just reports:** each problem is attributed to a cause, turned into a task and chased until it is closed.",
    "**Trustworthy by construction:** figures come from code and are verified in the AI text, so a manager can act without re-checking a spreadsheet.",
    "**Proactive:** the owner has the brief before service without opening the app.",
    "**Free to run and resilient:** everything fits free tiers. If GCP requires billing, GitHub Actions triggers the same endpoints; if Gemini is unavailable, a template brief is sent; if SendGrid's trial ends, Resend replaces it in one class.",
    "**Balanced full stack:** a real backend (metrics engine, rule engine, AI guardrails, scheduled jobs) behind a responsive, mobile-first UI.",
  ]),

  H1("6. Delivery Plan"),
  ...table(["Step", "Output"], [
    ["1. Data & metrics", "Prisma schema on Neon, seeded POS simulator with planted scenarios, weather back-fill, KPI engine with unit tests"],
    ["2. Anomalies & tasks", "Rule registry (AR-01 to AR-09), attribution, automatic tasks and the task workflow"],
    ["3. AI layer", "FactSheet, Gemini brief with structured output, Number Guard and template fallback, Ask OpsPilot tools"],
    ["4. Automation", "Secured cron endpoints, SendGrid emails, Cloud Scheduler jobs on Cloud Run (GitHub Actions fallback)"],
    ["5. Frontend & demo", "Dashboard, anomaly detail, investigations, chat and settings; README, source code and a recorded walkthrough"],
  ], [22, 78]),
  p("The full requirements (73 traced requirements), class design and diagrams are in the OpsPilot Software Requirements Specification v1.1.", { run: { italics: true, color: MUTED } }),
];

const footer = new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ font: FONT, size: 18, color: MUTED, children: [PageNumber.CURRENT] })] })] });
const lvl = (text, fmt) => [{ level: 0, format: fmt, text, alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 460, hanging: 280 } } } }];

const doc = new Document({
  creator: AUTHOR, title: "OpsPilot - SRS Summary",
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

const out = path.join(__dirname, "OpsPilot_SRS_Summary.docx");
Packer.toBuffer(doc).then((b) => { fs.writeFileSync(out, b); console.log("Wrote", out); });
