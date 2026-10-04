// Builds OpsPilot_SRS_v1.1.docx in the "Software Design Specification" layout
// (List of Tables/Figures → Definitions → Introduction → System Architecture → Object Model → Detailed Design → Appendices → References).
// Run: node diagrams/make_diagrams.js && diagrams/render.sh && node build_srs.js
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun, Footer,
  AlignmentType, HeadingLevel, LevelFormat, BorderStyle, WidthType, ShadingType, PageNumber,
  TableOfContents, VerticalAlign,
} = require("docx");

// ---------- constants ----------
const DOC_ID = "OPSPILOT-SRS-001";
const VERSION = "1.1";
const DATE = "29 September 2026";
const MONTH_YEAR = "September 2026";
const AUTHOR = "Gelila Tefera";
const FONT = "Calibri", MONO = "Consolas";
const ACCENT = "4A86E8";          // heading / caption blue
const HEAD_FILL = "4472C4";       // table header
const ROW_A = "D9E2F3", ROW_B = "E9EFF7", GRID = "8EAADB", CLASS_TXT = "2F5597", MUTED = "595959";
const PAGE_W = 11906, PAGE_H = 16838, MARGIN = 1247; // A4, 2.2 cm
const CW = PAGE_W - 2 * MARGIN;

// ---------- text helpers ----------
const run = (text, o = {}) => new TextRun({ text, font: o.mono ? MONO : FONT, ...o });
function rich(text, o = {}) {
  return String(text).split(/(\*\*[^*]+\*\*)/).filter(Boolean).map((seg) =>
    seg.startsWith("**") ? run(seg.slice(2, -2), { ...o, bold: true }) : run(seg, o));
}
const p = (text, o = {}) => new Paragraph({ children: rich(text, o.run || {}), spacing: { after: 140, line: 288 }, alignment: o.align, indent: o.indent });
const H1 = (t, brk = true) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [run(t)], pageBreakBefore: brk });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [run(t)] });
const H3 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [run(t)] });
const bullet = (t) => new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: rich(t), spacing: { after: 70, line: 276 } });
const bullets = (arr) => arr.map(bullet);
const arrowItem = (t) => new Paragraph({ numbering: { reference: "arrows", level: 0 }, children: rich(t), spacing: { after: 70, line: 276 } });
let numRef = 0;
const numbered = (arr) => { const ref = `num${numRef++}`; NUM_REFS.push(ref); return arr.map((t) => new Paragraph({ numbering: { reference: ref, level: 0 }, children: rich(t), spacing: { after: 70, line: 276 } })); };
const NUM_REFS = [];
const spacer = (after = 80) => new Paragraph({ children: [run("")], spacing: { after } });
const code = (lines) => lines.map((l, i) => new Paragraph({
  shading: { type: ShadingType.CLEAR, fill: "F2F2F2", color: "auto" }, spacing: { after: 0, before: i === 0 ? 80 : 0, line: 240 },
  children: [run(l === "" ? " " : l, { mono: true, size: 16 })],
}));

// ---------- numbered captions ----------
const TABLES = [], FIGURES = [];
function tableCaption(title) {
  TABLES.push(title);
  return new Paragraph({ spacing: { before: 200, after: 80 }, indent: { left: 567 }, keepNext: true, children: [run(`Table: ${TABLES.length} ${title}`, { color: ACCENT, size: 24 })] });
}
function figure(file, title) {
  FIGURES.push(title);
  const png = fs.readFileSync(path.join(__dirname, "diagrams", file));
  const w = png.readUInt32BE(16), h = png.readUInt32BE(20);
  const maxW = 620, maxH = 820, s = Math.min(maxW / w, maxH / h);
  return [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 160 }, keepNext: true, children: [new ImageRun({
      type: "png", data: png, transformation: { width: Math.round(w * s), height: Math.round(h * s) },
      altText: { title, description: title, name: file },
    })] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 60, after: 240 }, children: [run(`Figure ${FIGURES.length}: ${title}`, { color: ACCENT, size: 22 })] }),
  ];
}

// ---------- tables ----------
const bd = { style: BorderStyle.SINGLE, size: 4, color: GRID };
const borders = { top: bd, bottom: bd, left: bd, right: bd };
function cell(content, width, o = {}) {
  const paras = (Array.isArray(content) ? content : [content]).map((t) =>
    new Paragraph({ spacing: { after: 20 }, alignment: o.align, children: rich(String(t), { size: o.size || 19, bold: o.bold, color: o.color }) }));
  return new TableCell({
    borders, width: { size: width, type: WidthType.DXA }, verticalAlign: VerticalAlign.TOP,
    shading: o.fill ? { fill: o.fill, type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 50, bottom: 50, left: 100, right: 100 }, children: paras,
  });
}
function widths(weights) {
  const total = weights.reduce((a, b) => a + b, 0);
  const w = weights.map((x) => Math.floor((x / total) * CW));
  w[w.length - 1] += CW - w.reduce((a, b) => a + b, 0);
  return w;
}
// Blue banded table in the style of the reference document; caption above.
function table(caption, headers, rows, weights, o = {}) {
  const w = widths(weights);
  const trs = [];
  if (headers) trs.push(new TableRow({ tableHeader: true, cantSplit: true, children: headers.map((h, i) => cell(h, w[i], { bold: true, fill: HEAD_FILL, color: "FFFFFF" })) }));
  rows.forEach((r, ri) => trs.push(new TableRow({ cantSplit: true, children: r.map((c, i) => cell(c, w[i], { fill: ri % 2 ? ROW_B : ROW_A, bold: o.firstColBold !== false && i === 0 && !o.plainFirst })) })));
  return [...(caption ? [tableCaption(caption)] : []), new Table({ width: { size: CW, type: WidthType.DXA }, columnWidths: w, rows: trs }), spacer(120)];
}
// UML-style class box as a one-column table (name / attributes / operations).
function classBox(name, attrs, ops, stereo) {
  const w = [CW];
  const line = (t) => new Paragraph({ spacing: { after: 30 }, children: [run(t, { bold: true, color: CLASS_TXT, size: 20 })] });
  const mk = (children, align) => new TableRow({ cantSplit: true, children: [new TableCell({ borders, width: { size: CW, type: WidthType.DXA }, shading: { fill: "DAE3F3", type: ShadingType.CLEAR, color: "auto" }, margins: { top: 70, bottom: 70, left: 120, right: 120 }, children }) ] });
  const rows = [mk([...(stereo ? [new Paragraph({ alignment: AlignmentType.CENTER, children: [run(stereo, { italics: true, size: 18, color: MUTED })] })] : []), new Paragraph({ alignment: AlignmentType.CENTER, children: [run(name, { bold: true, color: CLASS_TXT, size: 22 })] })])];
  rows.push(mk(attrs.length ? attrs.map(line) : [line(" ")]));
  if (ops.length) rows.push(mk(ops.map(line)));
  return [tableCaption(`${name} Class`), new Table({ width: { size: CW, type: WidthType.DXA }, columnWidths: w, rows }), spacer(120)];
}

// ---------- requirements (single source; also drives the traceability matrix) ----------
const REQ = {
  ING: { title: "Data ingestion and POS simulation", uc: "UC-08", scr: "SCR-09", api: "/api/ingest/*", items: [
    ["The system shall provide a seed command that generates at least 120 consecutive trading days of deterministic data for a configured site from a fixed random seed, so that every run reproduces identical figures.", "Must"],
    ["Seed data shall include: at least 40 products in categories flagged wet (drinks) or dry (food) with price and unit cost; orders with line items, timestamps, covers, table/channel; employees with role and hourly rate; shifts (clock-in/out); discounts (amount, reason, authorising manager); voids (value, reason, manager); and daily cash-ups (expected vs counted cash and card).", "Must"],
    ["The seed shall inject the demonstration scenarios listed in the Demonstration Scenarios table on configurable dates so each anomaly rule can be observed deterministically.", "Must"],
    ["The system shall back-fill daily historical weather (max/min temperature, precipitation, weather code) for the seeded period from the Open-Meteo Historical API and store it in WeatherDaily; if the API is unavailable the seed shall continue with weather marked as missing.", "Must"],
    ["An Owner shall be able to trigger \"Simulate next trading day\" from the UI, optionally choosing a scenario; the system shall generate the next un-traded date using the same generator and then recompute metrics and anomalies for that date (FR-MET-06, FR-ANO-01).", "Must"],
    ["The system shall accept an orders CSV upload (max 5 MB / 50,000 rows) with columns external_order_id, timestamp (ISO 8601), sku, quantity, unit_price, discount_amount, discount_reason, manager_code, void_flag.", "Should"],
    ["CSV validation shall reject the file and return a row-level error report when any row has missing required columns, an unparseable timestamp, a negative quantity or price, or an unknown SKU (unless \"create unknown products\" is selected); the user may choose \"skip invalid rows\" to import the valid remainder.", "Should"],
    ["Imports shall be idempotent on (site, external_order_id): re-importing the same file shall not duplicate orders.", "Should"],
  ] },
  MET: { title: "Metrics engine", uc: "UC-01, UC-05", scr: "SCR-02, SCR-05", api: "/api/metrics", items: [
    ["The system shall compute a DailyMetrics record per site per trading date, where a trading date runs from 05:00 to 04:59 local time (Europe/London by default).", "Must"],
    ["The system shall compute the KPIs defined in the KPI Definitions table using the formulas given there; all monetary values shall be stored as integer pence and displayed in GBP (£) with thousands separators.", "Must"],
    ["The system shall compute each KPI per daypart (Lunch 11:00–14:59, Afternoon 15:00–17:29, Dinner 17:30–21:59, Late 22:00–close; configurable per site) and per manager where the metric is attributable.", "Must"],
    ["For every KPI the system shall compute comparisons vs the previous trading day, vs the same weekday last week, vs the 4-week same-weekday median, and vs target where a target exists.", "Must"],
    ["Currency and count deltas shall be expressed as percentage change; ratio deltas (e.g. labour %) shall be expressed in percentage points (pt).", "Must"],
    ["Metric computation shall be idempotent and shall be triggered automatically after any ingestion affecting a date; re-computing a date shall overwrite its previous DailyMetrics record.", "Must"],
    ["Where a denominator is zero or data is missing, the metric shall be stored as null and displayed as \"—\"; it shall be excluded from baselines and AI FactSheets.", "Must"],
  ] },
  ANO: { title: "Anomaly detection", uc: "UC-02", scr: "SCR-02, SCR-03", api: "/api/anomalies", items: [
    ["The system shall evaluate every rule in the anomaly rule registry (Anomaly Rule Registry table) each time DailyMetrics are computed for a date.", "Must"],
    ["Each detected anomaly shall record: rule ID, severity (info, warning, critical), metric, observed value, expected value, deviation, attributed dimension (manager, daypart, product, category or till), an evidence payload (the breakdown used) and a drill-down link.", "Must"],
    ["Baselines shall be the median of the same weekday over the trailing 4 weeks; spread shall be the median absolute deviation scaled by 1.4826 (σ). A rule shall be skipped, and the skip logged, when fewer than 3 valid baseline observations exist.", "Must"],
    ["When a single dimension value accounts for at least 50% of the excess over baseline, the anomaly shall name it as the primary contributor (e.g. \"Manager M. — 68% of excess discounts\").", "Must"],
    ["The system shall keep at most one open anomaly per (site, rule, dimension); a repeat on consecutive days shall increment a streak counter instead of creating a duplicate.", "Must"],
    ["Every anomaly of severity warning or critical shall automatically create an investigation Task (FR-TSK-01).", "Must"],
    ["Rule thresholds shall be configurable per site within the ranges in FR-SET-02.", "Should"],
    ["Anomaly detection shall be fully deterministic and shall not call any AI service.", "Must"],
  ] },
  BRF: { title: "Daily Operations Brief", uc: "UC-01, UC-06, UC-09", scr: "SCR-02, SCR-07", api: "/api/briefs, /api/cron/daily", items: [
    ["The system shall generate one Daily Operations Brief per site per trading date, triggered by the scheduled daily job (FR-NTF-01) or on demand by an Owner (\"Regenerate\").", "Must"],
    ["The system shall build a FactSheet (Appendix A) containing only pre-computed facts, each with a unique id, label, value, unit and display string, plus anomalies, tomorrow's outlook and context (site, date, weekday, weather). Raw transactions and staff surnames shall never be sent to the AI service.", "Must"],
    ["The system shall call the Gemini API (model gemini-2.5-flash) with a fixed system instruction, the FactSheet and a JSON responseSchema; temperature shall be ≤ 0.3.", "Must"],
    ["The AI output shall conform to the schema: headline (≤ 140 characters), summary (≤ 3 sentences), sections[{title, body, factIds[]}], actions[{title, rationale, anomalyId?, priority}]. Non-conforming output shall be treated as a failure.", "Must"],
    ["The Number Guard shall extract every numeric token (including £, %, pt, × and plain numbers) from the AI text and verify that each matches a FactSheet display value, or a FactSheet value within half of the last displayed digit. Dates and times present in the FactSheet context are allowed.", "Must"],
    ["On a Number Guard or schema failure the system shall retry once, supplying the list of offending tokens; on a second failure, a Gemini error, or a timeout of 20 s, it shall produce a deterministic template brief from the same FactSheet and mark the brief source as \"template\".", "Must"],
    ["The system shall persist each Brief with status, source (ai | template), Number Guard result, FactSheet snapshot, model name and latency.", "Must"],
    ["In the UI, each brief section shall show its cited facts; selecting a cited fact shall reveal the underlying figure and its comparison.", "Should"],
    ["On-demand regeneration shall be limited to 5 per site per day to protect the AI free-tier quota.", "Should"],
  ] },
  TSK: { title: "Investigation queue and follow-up", uc: "UC-03, UC-10", scr: "SCR-03, SCR-04", api: "/api/tasks, /api/cron/followup", items: [
    ["The system shall create a Task automatically from each warning/critical anomaly and shall allow users to create a Task manually from any anomaly or brief action.", "Must"],
    ["A Task shall have the states Open, Acknowledged, Resolved and Dismissed, with the transitions in the Task State Transitions table; any other transition shall be rejected with an error message.", "Must"],
    ["Each Task shall have a title, linked anomaly, severity, assignee, due date (default: next trading day 12:00) and a timestamped note history.", "Must"],
    ["Resolving or dismissing a Task shall require a note of at least 10 characters; dismissing shall additionally require a reason (false positive, expected / known cause, duplicate).", "Must"],
    ["The follow-up job (16:00 daily) shall email the assignee and the Owner a nudge for every critical Task still Open more than 8 hours after creation, at most once per Task per day.", "Must"],
    ["When a Task is dismissed as \"expected / known cause\", the system shall suppress new anomalies for the same rule and dimension for 7 days.", "Should"],
    ["The Investigations board shall allow filtering by state, severity, assignee and date, and shall show counts per column.", "Must"],
  ] },
  OUT: { title: "Tomorrow Outlook", uc: "UC-04", scr: "SCR-02", api: "/api/outlook", items: [
    ["The system shall fetch tomorrow's forecast (max temperature, precipitation sum, precipitation probability, weather code) for the site coordinates from the Open-Meteo Forecast API and cache it for 3 hours.", "Must"],
    ["The system shall estimate tomorrow's revenue and covers as the 4-week same-weekday median multiplied by a weather adjustment factor, derived from the site's history (mean revenue residual per temperature band and rain / no-rain) and bounded to 0.80–1.20; the estimate shall be shown as a range (±1σ).", "Must"],
    ["The system shall compute a recommended labour-hours cap = expected revenue × target labour % ÷ average blended hourly rate, and, where scheduled shifts exist for tomorrow, flag an over- or under-staffing gap of more than 10%.", "Must"],
    ["The system shall identify weather-sensitive products (unit sales on days ≥ 20 °C differing by ≥ 25% from other days, with at least 8 observations in each group) and show up to 3 prep hints when tomorrow's forecast falls in the relevant band.", "Should"],
    ["If the weather service is unavailable, the outlook shall fall back to the weekday-only estimate and state that weather was not considered.", "Must"],
  ] },
  CHT: { title: "Ask OpsPilot (conversational analysis)", uc: "UC-05", scr: "SCR-06", api: "/api/chat", items: [
    ["The system shall provide a chat panel, available from every screen, that accepts natural-language questions about the site's operations.", "Must"],
    ["The system shall answer using Gemini function calling restricted to the whitelisted tools in the Whitelisted Chat Tools table; the AI shall have no direct database or SQL access.", "Must"],
    ["Each tool shall validate its arguments (known site, date range ≤ 92 days and within available data, enumerated dimensions) and return a structured error for invalid input.", "Must"],
    ["The Number Guard (FR-BRF-05) shall be applied to chat answers using the numbers returned by the tools called in that turn; answers failing the guard shall be replaced by the tool results rendered as a table with a short fixed explanation.", "Must"],
    ["Actions with side effects (create_task) shall be proposed as a confirmation card and executed only after the user confirms.", "Must"],
    ["The assistant shall decline questions outside restaurant operations with a short explanation.", "Should"],
    ["A single turn shall make at most 5 tool calls; the conversation context shall include at most the last 10 messages of the session; responses shall be streamed to the UI.", "Should"],
  ] },
  NTF: { title: "Proactive notifications and scheduled jobs", uc: "UC-09, UC-10, UC-11", scr: "SCR-07, SCR-09", api: "/api/cron/*", items: [
    ["At 07:00 Europe/London each day the system shall generate the Daily Brief for the previous trading date and email it to the site's configured recipients; the email shall contain the headline, KPI table with comparisons, up to 3 top anomalies with deep links, tomorrow's outlook and a link to the dashboard.", "Must"],
    ["At 08:00 each Monday the system shall email a Weekly Recap: week vs previous week and vs 4-week average, anomalies opened / resolved / still open, and top and bottom 5 products.", "Should"],
    ["Cron endpoints shall accept requests only with a valid Google OIDC token for the configured service account and audience, or a matching X-Cron-Secret header (fallback schedulers); all other requests shall receive HTTP 401.", "Must"],
    ["Each job shall be idempotent per (job, site, date) using a unique JobRun record; a repeat call shall return the existing result unless force=true is supplied by an Owner.", "Must"],
    ["Email sending shall be retried up to 3 times with exponential back-off; final failures shall be recorded on the JobRun and shown in the UI delivery status.", "Must"],
    ["All emails shall include an HTML part and a plain-text alternative, and a link to manage recipients in Settings.", "Must"],
    ["Every emailed item shall also appear as an in-app notification.", "Could"],
  ] },
  SET: { title: "Settings and site configuration", uc: "UC-07", scr: "SCR-08", api: "/api/settings", items: [
    ["An Owner shall be able to configure per site: name, timezone, latitude/longitude, daypart boundaries, target labour %, target COGS %, discount tolerance %, cash variance threshold (£), brief recipients and brief send time.", "Must"],
    ["The system shall validate settings: target labour % 10–60, target COGS % 15–50, discount tolerance 1–25%, cash variance threshold £5–£500, latitude −90..90, longitude −180..180, recipients as valid email addresses (max 10).", "Must"],
    ["Every settings change shall be recorded with user, timestamp and before / after values.", "Should"],
    ["An Owner shall be able to run each scheduled job on demand (\"Run now\") and view the last 30 JobRuns with status and duration.", "Must"],
  ] },
  AUTH: { title: "Authentication and authorisation", uc: "all", scr: "SCR-01", api: "/api/auth/*", items: [
    ["Users shall sign in with email and password (NextAuth credentials provider; passwords hashed with bcrypt, cost ≥ 10).", "Must"],
    ["The system shall support two roles: Owner (all functions) and Manager (dashboard, anomalies, tasks, chat; no settings, simulation, import or job control).", "Must"],
    ["Sessions shall expire after 12 hours of inactivity.", "Must"],
    ["Every API route except /api/auth/* and /api/cron/* shall require an authenticated session and shall enforce role permissions server-side.", "Must"],
  ] },
};
const reqId = (k, i) => `FR-${k}-${String(i + 1).padStart(2, "0")}`;
const reqTable = (k) => table(`Functional Requirements — ${REQ[k].title}`, ["ID", "Requirement", "Priority"], REQ[k].items.map((r, i) => [reqId(k, i), r[0], r[1]]), [14, 74, 12]);

// ---------- detailed design data ----------
// attrs: [name, type, visibility, invariant]; ops: [name, visibility, returnType, args, pre, post]
const CLASSES = [
  { name: "Site", desc: "A restaurant location. Owns all operational data and its configuration.",
    attrs: [["id", "String", "Private", "Not null, unique (cuid)"], ["name", "String", "Public", "Not null, 2–80 characters"], ["timezone", "String", "Private", "Not null, valid IANA zone; default Europe/London"], ["lat", "Float", "Private", "Not null, −90 ≤ lat ≤ 90"], ["lng", "Float", "Private", "Not null, −180 ≤ lng ≤ 180"], ["settings", "SiteSettings", "Private", "Not null; every value within the FR-SET-02 ranges"]],
    ops: [["tradingDate", "Public", "Date", "ts : DateTime", "ts is a valid timestamp", "Returns the trading date of ts using the site timezone and the 05:00 cut-off."], ["updateSettings", "Public", "Site", "s : SiteSettings", "Caller is an Owner; s passes validation", "Settings are persisted and a SettingsAudit row (before/after) is written."]] },
  { name: "User", desc: "A person who signs in to OpsPilot.",
    attrs: [["id", "String", "Private", "Not null, unique"], ["email", "String", "Private", "Not null, unique, lower-cased; valid address (contains one @, a domain with a dot, ≥ 5 characters)"], ["passwordHash", "String", "Private", "Not null; bcrypt hash, cost ≥ 10; never returned by any API"], ["role", "Role", "Private", "Not null; one of the Role enumeration"], ["siteIds", "String[*]", "Private", "At least one existing site"]],
    ops: [["canAccess", "Public", "Boolean", "action : Action", "None", "Returns true only if the role permits the action (Access Control matrix)."]] },
  { name: "Order", desc: "A POS check. Composed of OrderLines; may have Discounts and Voids.",
    attrs: [["id", "String", "Private", "Not null, unique"], ["siteId", "String", "Private", "Not null, references Site"], ["externalId", "String", "Private", "Not null; unique per site (import idempotency)"], ["openedAt", "DateTime", "Private", "Not null; valid date-time"], ["covers", "Int", "Public", "Not null, ≥ 0"], ["tillId", "String", "Public", "Not null"]],
    ops: [["netPence", "Public", "Int", "None", "Lines, discounts and voids are loaded", "Returns Σ line value − discounts − voids in pence (ex-VAT)."]] },
  { name: "OrderLine", desc: "One product line on an order.",
    attrs: [["id", "String", "Private", "Not null, unique"], ["orderId", "String", "Private", "Not null, references Order"], ["productId", "String", "Private", "Not null, references Product"], ["qty", "Int", "Public", "Not null, > 0"], ["pricePence", "Int", "Public", "Not null, ≥ 0"]],
    ops: [["linePence", "Public", "Int", "None", "None", "Returns qty × pricePence."]] },
  { name: "Discount", desc: "A price reduction applied to an order, attributed to an authorising manager.",
    attrs: [["id", "String", "Private", "Not null, unique"], ["orderId", "String", "Private", "Not null, references Order"], ["amountPence", "Int", "Public", "Not null, > 0 and ≤ order gross value"], ["reason", "String", "Public", "Not null, ≤ 80 characters"], ["managerId", "String", "Private", "Not null, references an Employee with a managerCode"]], ops: [] },
  { name: "Void", desc: "An item removed from an order after entry.",
    attrs: [["id", "String", "Private", "Not null, unique"], ["orderId", "String", "Private", "Not null, references Order"], ["valuePence", "Int", "Public", "Not null, > 0"], ["reason", "String", "Public", "Not null, ≤ 80 characters"], ["managerId", "String", "Private", "Not null, references Employee"]], ops: [] },
  { name: "Shift", desc: "Worked (or scheduled) hours of an employee.",
    attrs: [["id", "String", "Private", "Not null, unique"], ["employeeId", "String", "Private", "Not null, references Employee"], ["start", "DateTime", "Public", "Not null"], ["end", "DateTime", "Public", "Not null, end > start, duration ≤ 16 h"], ["scheduled", "Boolean", "Public", "Not null; true = rota, false = actual"]],
    ops: [["hours", "Public", "Float", "None", "None", "Returns (end − start) in hours, 2 decimal places."]] },
  { name: "CashUp", desc: "End-of-day till reconciliation.",
    attrs: [["id", "String", "Private", "Not null, unique; (siteId, date, tillId) unique"], ["date", "Date", "Public", "Not null, valid trading date"], ["tillId", "String", "Public", "Not null"], ["expectedCashPence", "Int", "Private", "Not null, ≥ 0"], ["countedCashPence", "Int", "Private", "Not null, ≥ 0"], ["expectedCardPence", "Int", "Private", "Not null, ≥ 0"], ["countedCardPence", "Int", "Private", "Not null, ≥ 0"]],
    ops: [["variancePence", "Public", "Int", "None", "None", "Returns (countedCash + countedCard) − (expectedCash + expectedCard); negative means a shortfall."]] },
  { name: "DailyMetrics", desc: "Materialised KPIs for one site and trading date.",
    attrs: [["siteId", "String", "Private", "Not null; (siteId, date) unique"], ["date", "Date", "Public", "Not null"], ["kpis", "KpiSet", "Public", "Not null; every KPI of the KPI Definitions table; null allowed only when undefined"], ["dayparts", "Json", "Public", "Not null; Σ dayparts = day total (integrity check)"], ["byManager", "Json", "Public", "Not null"], ["computedAt", "DateTime", "Private", "Not null"]],
    ops: [["compare", "Public", "Comparison", "base : Baseline", "base computed for the same metric set", "Returns deltas: % for money and counts, pt for ratios."]] },
  { name: "Anomaly", desc: "A rule breach detected by the Anomaly Engine.",
    attrs: [["id", "String", "Private", "Not null, unique"], ["date", "Date", "Public", "Not null"], ["ruleId", "RuleId", "Public", "Not null; one of AR-01 … AR-09"], ["severity", "Severity", "Public", "Not null"], ["dimension", "String", "Public", "Not null, e.g. manager:sam-k, daypart:dinner"], ["observed", "Float", "Public", "Not null"], ["expected", "Float", "Public", "Not null"], ["evidence", "Json", "Private", "Not null; the breakdown used for attribution"], ["streak", "Int", "Public", "Not null, ≥ 1"]], ops: [] },
  { name: "Task", desc: "An investigation raised from an anomaly or created manually.",
    attrs: [["id", "String", "Private", "Not null, unique"], ["anomalyId", "String", "Private", "Nullable; unique when present"], ["title", "String", "Public", "Not null, 1–140 characters"], ["severity", "Severity", "Public", "Not null"], ["state", "TaskState", "Public", "Not null; changes only through transition()"], ["assigneeId", "String", "Private", "Not null, references User"], ["dueAt", "DateTime", "Public", "Not null, dueAt > createdAt"]],
    ops: [["transition", "Public", "Task", "to : TaskState, actor : User, note : String", "Transition allowed by the Task State Transitions table and actor's role; note ≥ 10 characters for Resolved/Dismissed", "State updated; TaskNote appended; if dismissed as EXPECTED a 7-day suppression is recorded."]] },
  { name: "Brief", desc: "A daily brief or weekly recap as delivered to users.",
    attrs: [["id", "String", "Private", "Not null; (siteId, date, kind) unique"], ["date", "Date", "Public", "Not null"], ["kind", "BriefKind", "Public", "Not null"], ["source", "BriefSource", "Public", "Not null"], ["content", "Json", "Public", "Not null; conforms to the response schema (Appendix A)"], ["factSheet", "Json", "Private", "Not null; snapshot used for generation"], ["guard", "Json", "Private", "Not null; {passed, violations[]}"], ["promptVersion", "String", "Private", "Not null"]],
    ops: [["render", "Public", "String", "format : html | text | json", "content is valid", "Returns the brief in the requested format (email HTML, plain text or API JSON)."]] },
  { name: "JobRun", desc: "Audit and idempotency record for one scheduled job execution.",
    attrs: [["id", "String", "Private", "Not null; (job, siteId, date) unique"], ["job", "JobName", "Public", "Not null"], ["siteId", "String", "Private", "Not null"], ["date", "Date", "Public", "Not null"], ["status", "JobStatus", "Public", "Not null"], ["durationMs", "Int", "Public", "≥ 0"], ["error", "String", "Private", "Nullable; set when status = FAILED"]], ops: [] },
  { name: "MetricsEngine", desc: "Pure functions that turn transactions into KPIs and baselines.", attrs: [],
    ops: [["computeDay", "Public", "DailyMetrics", "siteId : String, date : Date", "Site exists; date has trading data", "DailyMetrics upserted (idempotent); integrity check Σ dayparts = total logged."], ["baseline", "Public", "Baseline", "siteId, date, metric", "None", "Returns {median, sigma, n} of the same weekday over 4 weeks; n < 3 ⇒ insufficient flag."]] },
  { name: "AnomalyEngine", desc: "Runs the rule registry. Each rule implements the AnomalyRule interface (polymorphism).",
    attrs: [["rules", "AnomalyRule[*]", "Private", "Not empty; unique rule ids"]],
    ops: [["evaluate", "Public", "Anomaly[*]", "m : DailyMetrics, base : Baseline, s : SiteSettings", "m is computed; s is valid", "Returns anomalies deduplicated per (site, rule, dimension), with severity per the rule registry and suppressions applied."]] },
  { name: "FactSheetBuilder", desc: "Builds the only document the AI is allowed to read.", attrs: [],
    ops: [["build", "Public", "FactSheet", "metrics, anomalies, outlook", "Inputs belong to the same site and date", "Every fact has a unique id and a display string; no raw rows or surnames are included."]] },
  { name: "BriefGenerator", desc: "Orchestrates FactSheet → Gemini → Number Guard → fallback.",
    attrs: [["llm", "GeminiClient", "Private", "Not null"], ["guard", "NumberGuard", "Private", "Not null"], ["fallback", "TemplateBriefWriter", "Private", "Not null"], ["promptVersion", "String", "Private", "Not null, semantic version"]],
    ops: [["generate", "Public", "Brief", "siteId : String, date : Date, kind : BriefKind", "DailyMetrics exist for the date", "A Brief is persisted with source AI or TEMPLATE; at most 2 AI calls are made."]] },
  { name: "NumberGuard", desc: "Rejects AI text containing any number that is not a computed fact.",
    attrs: [["tolerance", "Float", "Private", "Half of the last displayed digit"]],
    ops: [["check", "Public", "GuardResult", "text : String, facts : FactSheet", "facts is not empty", "passed = true only if every numeric token matches a fact (algorithm in Appendix A.3); violations are listed."]] },
  { name: "GeminiClient", desc: "Adapter for the Gemini API. The only class that talks to the AI service.",
    attrs: [["apiKey", "Secret", "Private", "Not null; read from Secret Manager; never logged"], ["model", "String", "Private", "Not null; default gemini-2.5-flash"], ["timeoutMs", "Int", "Private", "20,000"]],
    ops: [["generateStructured", "Public", "Json", "prompt : String, schema : Schema", "Daily quota not exhausted", "Returns schema-valid JSON or throws AiError(QUOTA | TIMEOUT | INVALID); an AiCallLog row is written."], ["chat", "Public", "Stream", "messages : Message[*], tools : ToolDecl[*]", "≤ 10 messages; ≤ 5 tool calls per turn", "Streams text and function calls."]] },
  { name: "ChatAgent", desc: "Answers questions using whitelisted analytics tools.",
    attrs: [["tools", "ChatTool[*]", "Private", "Only the whitelisted tools"], ["maxToolCalls", "Int", "Private", "5"], ["historyLimit", "Int", "Private", "10"]],
    ops: [["answer", "Public", "Stream", "session : Session, question : String", "Authenticated session; question ≤ 1,000 characters", "Streams a guarded answer; side-effecting actions are returned as confirmation cards only."], ["confirm", "Public", "Task", "actionId : String", "Action was proposed in this session and not yet executed", "The proposed task is created and returned."]] },
  { name: "OutlookService", desc: "Builds tomorrow's demand and staffing outlook.",
    attrs: [["weather", "WeatherClient", "Private", "Not null"]],
    ops: [["forecast", "Public", "Outlook", "siteId : String, date : Date", "Site has ≥ 4 weeks of history", "Returns revenue/covers range, labour-hours cap, prep hints and a weatherConsidered flag."]] },
  { name: "WeatherClient", desc: "Adapter for the Open-Meteo forecast and archive APIs.",
    attrs: [["forecastUrl", "String", "Private", "Valid https URL: api.open-meteo.com/v1/forecast"], ["archiveUrl", "String", "Private", "Valid https URL: archive-api.open-meteo.com/v1/archive"], ["cacheTtl", "Int", "Private", "10,800 s"]],
    ops: [["forecast", "Public", "Weather", "lat, lng, date", "Coordinates valid; date within 16 days", "Returns daily forecast; cached for 3 h."], ["history", "Public", "Weather[*]", "lat, lng, from, to", "from ≤ to", "Returns daily history for the range."]] },
  { name: "Mailer", stereo: "«interface»", desc: "Abstraction for email providers; SendGridMailer is the v1 implementation, so a provider can be swapped in one class.", attrs: [],
    ops: [["send", "Public", "DeliveryResult", "msg : EmailMessage", "≥ 1 recipient; HTML and text parts present", "Returns ACCEPTED or FAILED; SendGridMailer retries up to 3 times with back-off."]] },
  { name: "JobRunner", desc: "Entry point for the three scheduled jobs.",
    attrs: [["auth", "CronAuth", "Private", "OIDC audience and/or shared secret configured"]],
    ops: [["runDaily", "Public", "JobRun", "siteId, date, force : Boolean", "Caller verified (OIDC or secret)", "Metrics, anomalies, tasks, brief and email processed; JobRun = SUCCESS / SKIPPED / FAILED."], ["runFollowUp", "Public", "JobRun", "now : DateTime", "Caller verified", "Nudges sent for critical tasks open > 8 h, at most once per task per day."], ["runWeekly", "Public", "JobRun", "weekStart : Date", "Caller verified; weekStart is a Monday", "Weekly recap generated and emailed."]] },
  { name: "TaskService", desc: "Creates and moves investigation tasks.",
    attrs: [["mailer", "Mailer", "Private", "Not null"]],
    ops: [["createFromAnomaly", "Public", "Task", "a : Anomaly", "a.severity ≥ WARNING; no open task for the anomaly", "Task created in state OPEN with default due date."], ["dueForFollowUp", "Public", "Task[*]", "now : DateTime", "None", "Returns critical OPEN tasks older than 8 h not nudged today."]] },
];
const ENUMS = [
  ["Role", "Types of user that can sign in.", ["OWNER", "MANAGER"]],
  ["Severity", "Severity of an anomaly and its task.", ["INFO", "WARNING", "CRITICAL"]],
  ["TaskState", "Lifecycle state of an investigation task.", ["OPEN", "ACKNOWLEDGED", "RESOLVED", "DISMISSED"]],
  ["DismissReason", "Why a task was dismissed.", ["FALSE_POSITIVE", "EXPECTED", "DUPLICATE"]],
  ["BriefKind", "Type of brief.", ["DAILY", "WEEKLY"]],
  ["BriefSource", "Who wrote the brief text.", ["AI", "TEMPLATE"]],
  ["JobName", "The three scheduled jobs.", ["DAILY_BRIEF", "TASK_FOLLOW_UP", "WEEKLY_RECAP"]],
  ["JobStatus", "Result of a job execution.", ["RUNNING", "SUCCESS", "SKIPPED", "FAILED"]],
  ["RuleId", "Anomaly rules in the registry.", ["AR-01 … AR-09"]],
  ["Daypart", "Trading periods within a day.", ["LUNCH", "AFTERNOON", "DINNER", "LATE"]],
  ["WeatherSource", "Origin of a weather record.", ["ARCHIVE", "FORECAST"]],
];

// ================= document body =================
const B = [];

// ----- DEFINITIONS -----
B.push(
  H1("DEFINITIONS, ACRONYMS, ABBREVIATIONS"),
  ...table(null, ["Term", "Description"], [
    ["Anomaly", "A metric value that breaches a rule in the anomaly rule registry."],
    ["ATV / Spend per cover", "Average transaction value; net revenue ÷ covers."],
    ["Baseline", "Median of the same weekday over the trailing 4 weeks."],
    ["Cash-up", "End-of-day reconciliation of expected vs counted cash and card takings."],
    ["COGS", "Cost of goods sold — theoretical ingredient/drink cost of items sold."],
    ["Cover", "One guest served."],
    ["Daypart", "A trading period within the day (Lunch, Afternoon, Dinner, Late)."],
    ["FactSheet", "The JSON document of pre-computed, id-tagged facts that is the only data passed to Gemini."],
    ["GM", "General Manager of a restaurant site."],
    ["GP %", "Gross profit % = (net revenue − COGS) ÷ net revenue."],
    ["Labour %", "Labour cost ÷ net revenue."],
    ["Leakage", "Revenue lost to discounts, voids, comps and cash variances."],
    ["MAD", "Median absolute deviation; robust spread measure (σ ≈ 1.4826 × MAD)."],
    ["Number Guard", "Validator that rejects AI text containing any number not present in the FactSheet."],
    ["OIDC", "OpenID Connect; token used by Cloud Scheduler to authenticate to Cloud Run."],
    ["POS", "Point of sale (till) system."],
    ["Prime cost %", "(COGS + labour cost) ÷ net revenue."],
    ["pt", "Percentage point — the unit for differences between two percentages."],
    ["Void", "An item removed from an order after being entered."],
    ["Wet / Dry", "Drinks / Food revenue categories."],
    ["SRS / SDS", "Software Requirements Specification / Software Design Specification."],
    ["MoSCoW", "Prioritisation scheme: Must, Should, Could, Won't."],
  ], [25, 75]),
);

// ----- 1 INTRODUCTION -----
B.push(
  H1("1. INTRODUCTION"),
  H2("1.1 Purpose"),
  p("This is the Software Requirements Specification for **OpsPilot — an AI Operations Manager for independent restaurants**. It records the research behind the chosen role, specifies uniquely identified requirements, and breaks the product down into subsystems, objects and classes to describe how each part will be implemented. It is the implementation guide for the build phase and a tool for verification and validation of the final product, through the requirements traceability matrix in the appendices."),
  p("OpsPilot performs the daily analytical and follow-up work of a restaurant operations manager. Every morning it reconciles trading, labour, leakage and cash-up data, detects anomalies with deterministic statistics, explains them in plain English with Google Gemini, opens investigation tasks, chases them until they are resolved, and prepares tomorrow's staffing and prep outlook using weather forecasts. Its central design principle is that **the backend owns the numbers and Gemini owns the explanation**: every figure in AI-written text is verified against computed facts before a manager sees it."),
  p("**Intended audience:** the Brain3.ai reviewer (approval of scope and approach), the developer (implementation guide) and any future tester or contributor."),
  p("**Scope — OpsPilot will:**"),
  ...bullets([
    "Ingest daily trading data (orders, products, labour shifts, discounts, voids, cash-ups) from a simulated POS or a CSV export.",
    "Compute operational KPIs and comparisons deterministically in the backend.",
    "Detect operational anomalies (leakage, labour creep, daypart and product declines, cash variances, COGS drift) and attribute them to a manager, daypart, product or till.",
    "Write a concise Daily Operations Brief with Gemini, verified by a Number Guard so that no invented figures reach the user.",
    "Open investigation tasks automatically, and follow up on critical tasks that remain unresolved.",
    "Forecast tomorrow's demand using weather and weekday history, and recommend a labour-hours cap and prep hints.",
    "Answer ad-hoc operational questions through a tool-restricted chat assistant.",
    "Act proactively on a schedule: morning brief email, afternoon follow-up, Monday weekly recap.",
  ]),
  p("**Scope — OpsPilot will not (v1):** connect to live commercial POS or rota APIs (Toast, Square, Lightspeed, etc.); change rotas or place supplier orders autonomously; process payroll; produce statutory or accounting reports (P&L, VAT); or provide multi-tenant billing."),
  ...table("Goals and Measures of Success", ["Goal", "Measure of success"], [
    ["Remove the daily manual numbers review", "Time for a GM to understand yesterday's trading falls from ~30–60 min to < 5 min (reading one brief)."],
    ["Catch leakage and cost creep early", "Discount, void, cash and labour anomalies surfaced within 24 hours (vs. month-end management accounts)."],
    ["Trustworthy AI output", "100% of numbers in delivered AI text match computed facts (enforced by Number Guard, FR-BRF-05)."],
    ["Close the loop, not just report", "Every warning/critical anomaly becomes a tracked task; critical tasks are chased the same day."],
    ["Zero-cost operation for the demo", "Runs entirely on free tiers (Free-Tier Budget table) with no paid services."],
  ], [35, 65]),

  H2("1.2 General Overview"),
  p("Independent restaurants run on thin margins (typically 3–6% net), so a few points of labour creep, a manager over-discounting or a till that is regularly £40 short can erase a month's profit. Larger groups employ operations managers and finance teams to watch these numbers daily; an independent owner or GM usually cannot afford a £40–55k operations manager, and so the checking happens late (at month-end), partially, or not at all."),
  p("Existing POS dashboards show numbers but do not explain them, do not prioritise and do not follow up. The author's professional experience building finance and trading analytics for UK multi-site hospitality operators shows that the valuable part of the job is not the report — it is noticing what changed, working out why, telling the right person and making sure something is done. That judgement-and-follow-up loop is repetitive, data-heavy and time-critical, which makes it an excellent candidate for an AI agent."),
  p("Decomposition and prototyping approaches were used to examine the role and fine-tune the requirements. The operations manager role was broken down into sub-functions, each scored for impact, frequency and automation feasibility with free APIs; the top-priority functions form the v1 scope."),
  ...table("Role Research and Breakdown", ["#", "Sub-function", "Human effort today", "Impact", "Feasibility", "Priority", "OpsPilot capability"], [
    ["1", "Review yesterday's trading (sales, labour, GP)", "30–60 min daily", "High", "High", "P0", "Daily Operations Brief"],
    ["2", "Spot leakage and cost creep (discounts, voids, cash, labour)", "Often missed until month-end", "Very high", "High", "P0", "Anomaly detection engine"],
    ["3", "Report to the owner before service", "15 min daily", "High", "High", "P0", "07:00 proactive email"],
    ["4", "Assign and chase investigations", "Ad hoc, easily forgotten", "High", "High", "P1", "Investigation queue + 16:00 follow-up"],
    ["5", "Plan tomorrow (staffing, prep)", "20 min daily", "High", "Medium", "P1", "Tomorrow Outlook (weather + history)"],
    ["6", "Answer ad-hoc questions", "Spreadsheet digging", "Medium", "High", "P1", "Ask OpsPilot chat (tool-restricted)"],
    ["7", "Weekly performance recap", "1–2 h weekly", "Medium", "High", "P2", "Monday weekly recap email"],
    ["8", "Maintain targets and thresholds", "Occasional", "Medium", "High", "P2", "Settings"],
    ["–", "Rota building, supplier ordering, payroll, hiring", "High", "High", "Low (paid APIs / risk)", "Out of scope", "Future extensions"],
  ], [4, 24, 14, 9, 11, 9, 22]),
  p("**Value proposition:**"),
  ...bullets([
    "**Cheaper than a person, faster than month-end:** a target price of ~£99 per site per month against a £40–55k salary, with anomalies surfaced within 24 hours.",
    "**Explains and acts, not just displays:** each insight names the cause (manager, daypart, product) and becomes a tracked task that is chased.",
    "**Trustworthy by construction:** figures are computed by code and verified in the AI text, so a GM can act on the brief without re-checking the spreadsheet.",
    "**Proactive:** the owner receives the brief before service starts, without opening the app.",
  ]),
  p("OpsPilot is a new, self-contained product. In production it would sit downstream of a restaurant's POS, rota and cash-up tools; in this version those are represented by a simulated POS and a CSV importer that write into OpsPilot's own database. The high-level context diagram of the system is presented as follows:"),
  ...figure("fig_context.png", "Context Diagram"),
  p("Since the context diagram only gives a high-level description of the system's components and their interactions, it is not sufficient to understand how data moves through the agent. A Level One Data Flow Diagram was therefore used: it expands the single process of the context diagram into the eight major processes of the system, the data stores they share and the external entities they exchange data with. It also makes the automation visible — the Cloud Scheduler trigger drives processes 2.0 → 3.0 → 4.0 → 8.0 without any user action."),
  ...figure("fig_dfd.png", "Level One Data Flow Diagram"),
  ...table("Product Functions", ["ID", "Function", "Summary"], [
    ["F1", "Data ingestion", "Seeded POS simulation with injected scenarios, next-day simulation, CSV import."],
    ["F2", "Metrics engine", "Daily KPIs, daypart and manager breakdowns, baselines and comparisons."],
    ["F3", "Anomaly detection", "Deterministic, statistical rules with severity, attribution and evidence."],
    ["F4", "Daily Operations Brief", "Gemini narrative from a FactSheet, verified by the Number Guard, with a template fallback."],
    ["F5", "Investigation queue", "Tasks from anomalies, a state workflow, notes, follow-up nudges and a suppression feedback loop."],
    ["F6", "Tomorrow Outlook", "Weather-adjusted demand estimate, labour-hours cap and prep hints."],
    ["F7", "Ask OpsPilot", "Chat with Gemini function calling over whitelisted analytics tools."],
    ["F8", "Proactive automation", "07:00 brief, 16:00 follow-up and Monday 08:00 recap via Cloud Scheduler + SendGrid."],
    ["F9", "Settings and administration", "Targets, thresholds, recipients, job control, audit."],
  ], [8, 24, 68]),
  ...figure("fig_usecases.png", "Use-Case Diagram"),
  ...table("Use Case Descriptions", ["Use case", "Primary actor", "Description"], [
    ["UC-01 View morning dashboard & brief", "Owner / GM, Manager", "See yesterday's KPIs with comparisons, the AI brief, items needing attention and tomorrow's outlook."],
    ["UC-02 Drill into an anomaly", "Owner / GM, Manager", "Open an anomaly to see its evidence chart, contributors, baseline and the linked task."],
    ["UC-03 Manage investigation tasks", "Owner / GM, Manager", "Acknowledge, annotate, resolve or dismiss tasks; filter the board."],
    ["UC-04 View tomorrow outlook", "Owner / GM", "See the expected revenue/covers range, labour-hours cap and prep hints."],
    ["UC-05 Ask OpsPilot a question", "Owner / GM, Manager", "Ask a natural-language question; receive a grounded answer; optionally confirm a proposed task."],
    ["UC-06 Browse brief archive", "Owner / GM", "Read past briefs and email delivery status."],
    ["UC-07 Configure targets & thresholds", "Owner", "Edit site settings, recipients and thresholds."],
    ["UC-08 Simulate day / import POS CSV", "Owner", "Generate the next trading day (optionally with a scenario) or upload a CSV."],
    ["UC-09 Generate & email daily brief", "Cloud Scheduler", "Unattended 07:00 job (Daily Brief sequence diagram)."],
    ["UC-10 Follow up unresolved critical tasks", "Cloud Scheduler", "Unattended 16:00 job that nudges assignees."],
    ["UC-11 Send weekly recap", "Cloud Scheduler", "Unattended Monday 08:00 job."],
  ], [30, 20, 50]),
  ...table("User Characteristics", ["User class", "Characteristics", "Implications for requirements"], [
    ["Owner / GM", "Hospitality professional; commercially fluent (GP %, labour %) but not a data analyst; time-poor; often reads on a phone before service.", "Plain-English brief; mobile-first dashboard; email delivery; conclusions first with drill-down."],
    ["Shift / Duty Manager", "Runs the floor; limited admin time; accountable for their shift's discounts, voids and cash-up.", "Restricted role; fast task acknowledgement; no access to settings."],
    ["Cloud Scheduler (system actor)", "Unattended trigger; authenticates with an OIDC token.", "Idempotent, secured endpoints; job audit log."],
  ], [20, 42, 38]),

  H2("1.3 Development Methods and Contingencies"),
  H3("Design Strategies"),
  p("Two major software design strategies were used to take the requirements to implementation: function-oriented design and object-oriented design."),
  p("**Function-oriented design** was used to decompose the role into interacting units, each with one clearly defined function. The broad \"operations manager\" concept was first decomposed into two major functions:"),
  ...bullets(["OpsPilot tells the owner what happened and why, and", "OpsPilot makes sure something is done about it."]),
  p("These were further decomposed into: ingest the day's data; compute KPIs and baselines; detect and attribute anomalies; write a verified brief; open and chase investigation tasks; forecast tomorrow; answer questions; and notify on a schedule. In this manner all operations of the system were identified, and the design relied on how data flows through them (Level One Data Flow Diagram)."),
  p("**Object-oriented design** was used for the implementation. The main entities and services are modelled as classes (Section 3 and Section 4). Important object-oriented concepts applied:"),
  ...[
    "**Object** — every entity (Site, Order, Shift, Anomaly, Task, Brief …) is an object with attributes and methods.",
    "**Class** — generalised descriptions of objects with their attributes and operations (Section 4).",
    "**Encapsulation** — third-party services are hidden behind adapter classes (GeminiClient, WeatherClient, Mailer); API keys and password hashes are private and never leave the server.",
    "**Polymorphism** — every anomaly rule implements the AnomalyRule interface and every email provider implements the Mailer interface, so new rules or providers are added without changing callers.",
    "**Separation of computation and language** — numbers are produced only by deterministic classes (MetricsEngine, AnomalyEngine); the AI can only describe facts supplied by FactSheetBuilder, and NumberGuard enforces it.",
  ].map(arrowItem),
  H3("Design Approach"),
  p("A **top-down** approach was used: the agent was treated as one system and decomposed into subsystems, then into classes and operations, until the lowest level (individual methods with pre- and post-conditions) was reached. Requirements are prioritised with **MoSCoW** and identified uniquely (FR-<feature>-<nn>); each one is traced to a use case, screen, API and test in the Requirements Traceability Matrix (Appendix D)."),
  H3("Constraints and Assumptions"),
  ...bullets([
    "**Cost / free tiers:** all services must run on free tiers without paid usage. Gemini usage is budgeted at ≤ 60 requests per day; Cloud Scheduler is limited to 3 jobs.",
    "**Regulatory:** staff names and performance attributions are personal data under UK GDPR. Only first name and last initial are displayed, only first names are sent to the AI service, and data is used solely for operational management.",
    "**Criticality:** OpsPilot is advisory; it never changes POS, payroll or rota data. Failures must degrade to less insight, never to wrong figures.",
    "**Reliability:** the AI service is treated as unreliable; every AI-dependent output has a deterministic fallback.",
    "**Audit:** all scheduled jobs, AI calls and settings changes are logged.",
    "**Time:** delivery is within the assignment deadline, so v1 scope is limited to P0–P1 plus the low-cost P2 items.",
    "**Assumption:** a Gemini API key is available from Google AI Studio free tier and its limits are sufficient for ≤ 60 requests per day.",
    "**Assumption:** Open-Meteo remains free for non-commercial use without an API key (< 10,000 calls per day).",
    "**Assumption:** a SendGrid account with a verified single sender is available (the free offering is currently a time-limited trial).",
    "**Assumption:** Neon's free plan (~0.5 GB) is sufficient; simulated data is statistically realistic (weekday and daypart seasonality, weather effects, noise).",
  ]),
  H3("Contingencies"),
  p("Despite the approach taken, several contingencies could change the direction of the project. Each is listed with its workaround:"),
  ...numbered([
    "**GCP billing requirement:** Cloud Run and Cloud Scheduler may require a billing account even when usage is within the free tier. **Workaround:** cron endpoints are scheduler-agnostic, so GitHub Actions scheduled workflows (X-Cron-Secret) trigger the same jobs and the app is hosted on an alternative free host; requirements are unchanged.",
    "**Email provider limits:** the SendGrid free offering is time-limited or sender verification is delayed. **Workaround:** the Mailer interface allows swapping to Resend or the Gmail API in one class; the in-app brief remains available.",
    "**AI quota or regional restriction:** Gemini free-tier limits are reached or unavailable. **Workaround:** ≤ 60 requests/day budget, regeneration limits and the deterministic template brief (FR-BRF-06, FR-BRF-09).",
    "**AI hallucinated figures:** the model invents or recalculates numbers. **Workaround:** FactSheet-only input, structured output, Number Guard and template fallback.",
    "**Unrealistic synthetic data:** the demo looks artificial. **Workaround:** weekday/daypart seasonality, real historical weather, noise and injected scenarios.",
    "**Scope creep within the deadline:** **Workaround:** MoSCoW priorities; P2 items are built only after P0–P1 pass their tests.",
    "**Requirement changes after review:** **Workaround:** changes are recorded in the revision history and assessed against the traceability matrix before implementation.",
  ]),
);

// ----- 2 SYSTEM ARCHITECTURE -----
const sub = (t) => H3(t);
B.push(
  H1("2. SYSTEM ARCHITECTURE"),
  H2("2.1 Subsystem Decomposition"),
  p("OpsPilot is a single Next.js 15 (TypeScript) application containing the user interface and a layered backend (API routes → domain subsystems → Prisma), deployed as one container. Domain logic (metrics, anomalies, Number Guard) consists of pure, framework-independent functions. The component diagram below shows the subsystems; each is then described with its functional requirements. Requirements use \"shall\" for mandatory behaviour and MoSCoW priority."),
  ...figure("fig_component.png", "Component Diagram"),

  sub("Presentation Subsystem"),
  p("A responsive web UI (Next.js App Router, Tailwind CSS, Recharts), usable from 360 px (mobile) to 1440 px+ widths. Navigation is a left sidebar on desktop and a bottom bar on mobile; the Ask OpsPilot panel is available on every screen."),
  ...table("User Interface Screens", ["Screen", "Purpose", "Key content and interactions"], [
    ["SCR-01 Sign-in", "Authenticate", "Email/password; error on invalid credentials without revealing which field was wrong."],
    ["SCR-02 Morning Dashboard", "Answer \"how did we do and what needs attention?\" in 30 s", "Greeting and date selector; KPI cards (value, vs last week, vs 4-wk median, vs target, sparkline); AI brief card with source badge (AI verified / Standard) and cited facts; \"Needs attention\" list ranked by severity; Tomorrow Outlook card."],
    ["SCR-03 Anomaly Detail", "Explain one anomaly", "Observed vs expected; 28-day chart with baseline band; contributor breakdown (e.g. discounts by manager × daypart); linked task with quick actions; \"Ask OpsPilot about this\"."],
    ["SCR-04 Investigations", "Close the loop", "Kanban (Open, Acknowledged, Resolved, Dismissed) with filters; task drawer with note history."],
    ["SCR-05 Trends", "Explore", "Metric picker, date range, daypart filter, comparison overlay, weather overlay."],
    ["SCR-06 Ask OpsPilot", "Ad-hoc questions", "Streaming chat, suggested questions, tool-call transparency (\"Checked discounts by manager\"), confirmation cards."],
    ["SCR-07 Briefs Archive", "History", "List of briefs with source and delivery status; email preview."],
    ["SCR-08 Settings", "Configure", "Targets, thresholds, dayparts, coordinates, recipients; validation messages inline."],
    ["SCR-09 Data & Jobs", "Admin / demo", "Simulate next day (with scenario picker), CSV import with error report, job runs with Run now."],
  ], [20, 22, 58]),
  p("**UI rules:** conclusions first, numbers second, raw data on demand; green/red deltas are always accompanied by an arrow and a sign (not colour alone); AI-generated text is visibly labelled; all loading states use skeletons; every error message states what happened and what the user can do; money is shown as £ with no decimals above £1,000; ratios are shown to one decimal place."),

  sub("Ingestion Subsystem (F1)"),
  p("**Inputs:** seed configuration (site, start date, days, random seed, scenario schedule), simulation request, CSV file. **Outputs:** persisted orders, shifts, discounts, voids, cash-ups and weather; an import report."),
  ...reqTable("ING"),
  ...table("Demonstration Scenarios", ["Scenario", "Injected behaviour", "Expected detection"], [
    ["S1 Discount creep", "Manager \"Sam K.\" applies 2–3× normal discount value on Friday/Saturday dinner over two weeks.", "AR-01, attributed to Sam K. and Dinner"],
    ["S2 Over-staffed dinner", "Two extra servers rostered on a quiet Tuesday dinner.", "AR-03, attributed to the Dinner shift"],
    ["S3 Product decline", "\"Chicken Shawarma Wrap\" units fall ~35% from a given date (simulating a recipe change).", "AR-05, product"],
    ["S4 Cash shortfall", "Till 2 cash counted £62 below expected on one night.", "AR-07, critical, Till 2"],
    ["S5 Heatwave", "Real warm days in the weather history lift iced drinks and lower soup sales.", "AR-06 plus weather-sensitive products in the Outlook"],
  ], [20, 50, 30]),

  sub("Metrics Subsystem (F2)"),
  ...reqTable("MET"),
  ...table("KPI Definitions", ["KPI", "Formula", "Unit"], [
    ["Net revenue", "Σ(line price × qty) − discounts − voids (ex-VAT)", "£"],
    ["Orders / Covers", "count(orders) / Σ covers", "count"],
    ["Spend per cover", "Net revenue ÷ covers", "£"],
    ["Wet / Dry mix", "Revenue of wet (dry) categories ÷ net revenue", "%"],
    ["COGS %", "Σ(unit cost × qty) ÷ net revenue", "%"],
    ["GP %", "(Net revenue − COGS) ÷ net revenue", "%"],
    ["Labour cost", "Σ(shift hours × hourly rate × (1 + on-cost 13.8%))", "£"],
    ["Labour %", "Labour cost ÷ net revenue", "%"],
    ["Prime cost %", "(COGS + labour cost) ÷ net revenue", "%"],
    ["Covers per labour hour", "Covers ÷ Σ shift hours", "ratio"],
    ["Discount rate", "Σ discounts ÷ gross revenue", "%"],
    ["Void rate", "Σ void value ÷ gross revenue", "%"],
    ["Cash-up variance", "Counted − expected (cash, card, total)", "£"],
    ["Product units / revenue", "Per product, per day and daypart", "count / £"],
  ], [25, 60, 15]),

  sub("Anomaly Detection Subsystem (F3)"),
  ...reqTable("ANO"),
  ...table("Anomaly Rule Registry", ["Rule", "Name", "Trigger (default thresholds)", "Severity", "Attribution"], [
    ["AR-01", "Discount spike", "Discount rate > max(tolerance, baseline + 2σ)", "Warning; Critical if > 2× baseline", "Manager, daypart"],
    ["AR-02", "Void spike", "Void rate > baseline + 2σ and void value ≥ £25", "Warning", "Manager"],
    ["AR-03", "Labour over target", "Labour % > target + 3 pt", "Warning; Critical if ≥ +6 pt", "Shift / daypart; covers per labour hour"],
    ["AR-04", "Daypart revenue drop", "Daypart revenue < 85% of baseline", "Warning; Critical if < 70%", "Daypart"],
    ["AR-05", "Product decline", "Units < 70% of baseline (baseline ≥ 10 units/day)", "Info", "Product"],
    ["AR-06", "Product surge", "Units > 150% of baseline (baseline ≥ 10 units/day)", "Info (opportunity)", "Product; weather correlation"],
    ["AR-07", "Cash-up variance", "|Total variance| > threshold (default £20)", "Warning; Critical if > £50", "Till, closing manager"],
    ["AR-08", "COGS drift", "COGS % > baseline + 2 pt", "Warning", "Category"],
    ["AR-09", "Revenue drop", "Net revenue < 85% of baseline", "Warning", "Daypart with largest shortfall"],
  ], [9, 17, 34, 20, 20]),

  sub("AI Brief Subsystem (F4)"),
  p("The brief generator separates computation from language. The processing steps are:"),
  ...numbered([
    "Load DailyMetrics, comparisons, anomalies and the outlook for the date.",
    "Build the FactSheet (Appendix A.1): each fact has a stable id (e.g. rev.net, lab.pct.delta_wk) and a pre-formatted display string (e.g. \"£8,240\", \"31.2%\", \"+4.8 pt\").",
    "Call Gemini with the system instruction (\"Use only the facts provided; cite fact ids; do not calculate new numbers; lead with what needs attention\") and the response schema (Appendix A.2).",
    "Validate against the schema, then run the Number Guard.",
    "On failure, retry once with feedback; otherwise fall back to the template brief.",
    "Persist the brief and AiCallLog, and return or send.",
  ]),
  ...reqTable("BRF"),
  ...table("Abnormal Situations for Brief Generation", ["Condition", "System response"], [
    ["Gemini returns HTTP 429 (quota)", "No retry; template brief; AiCallLog status = quota; banner \"AI narrative unavailable — showing standard brief\"."],
    ["Gemini timeout (> 20 s) or 5xx", "One retry after 2 s; then template brief."],
    ["Schema-invalid JSON", "Counts as a guard failure (retry once, then template)."],
    ["Number Guard rejects a token", "Retry with the offending tokens listed; then template."],
    ["No metrics for the date", "No brief; JobRun status = skipped (no data); the owner is emailed a \"no trading data received\" notice."],
  ], [35, 65]),

  sub("Investigation Subsystem (F5)"),
  ...reqTable("TSK"),
  ...table("Task State Transitions", ["From", "To", "Allowed actor", "Condition"], [
    ["Open", "Acknowledged", "Owner, Manager", "—"],
    ["Open / Acknowledged", "Resolved", "Owner, Manager", "Note ≥ 10 characters"],
    ["Open / Acknowledged", "Dismissed", "Owner", "Reason + note"],
    ["Resolved / Dismissed", "Open", "Owner", "Reopen with note"],
  ], [25, 20, 25, 30]),

  sub("Outlook Subsystem (F6)"),
  ...reqTable("OUT"),

  sub("Conversational Subsystem (F7)"),
  ...reqTable("CHT"),
  ...table("Whitelisted Chat Tools", ["Tool", "Arguments", "Returns"], [
    ["get_kpis", "date_from, date_to, daypart?", "KPI values and comparisons"],
    ["compare_periods", "period_a, period_b, metrics[]", "Side-by-side values and deltas"],
    ["get_anomalies", "date_from, date_to, severity?, rule?", "Anomaly list with evidence"],
    ["get_product_performance", "date_from, date_to, sort, limit ≤ 20", "Units, revenue, GP and vs baseline per product"],
    ["get_daypart_breakdown", "date", "Revenue, covers and labour per daypart"],
    ["get_labour_breakdown", "date_from, date_to", "Hours and cost per role and shift; covers per labour hour"],
    ["get_discounts_breakdown", "date_from, date_to, group_by (manager | reason | daypart)", "Discount value and rate by group"],
    ["get_weather", "date_from, date_to", "Daily weather history or forecast"],
    ["get_tasks", "state?, severity?", "Task list"],
    ["create_task (confirmation required)", "title, anomaly_id?, assignee, due", "Proposed task card"],
  ], [30, 38, 32]),

  sub("Notification and Job Subsystem (F8)"),
  ...reqTable("NTF"),
  ...table("Cloud Scheduler Jobs (3 = free-tier limit)", ["Job", "Schedule (Europe/London)", "Endpoint", "Action"], [
    ["daily-brief", "Every day 07:00", "POST /api/cron/daily", "Metrics → anomalies → outlook → brief → email"],
    ["task-follow-up", "Every day 16:00", "POST /api/cron/followup", "Nudge for critical tasks open > 8 h"],
    ["weekly-recap", "Monday 08:00", "POST /api/cron/weekly", "Weekly recap email"],
  ], [18, 22, 25, 35]),

  sub("Settings Subsystem (F9)"),
  ...reqTable("SET"),

  H2("2.2 Hardware/ Software Mapping"),
  p("The deployment diagram maps software components to execution environments. OpsPilot runs as one container on Google Cloud Run (scale-to-zero); PostgreSQL is hosted by Neon; Gemini, Open-Meteo and SendGrid are external services reached over HTTPS; GitHub hosts the repository, CI and the fallback scheduler."),
  ...figure("fig_deployment.png", "Deployment Diagram"),
  ...table("Software Interfaces", ["Name (mnemonic)", "Version / endpoint", "Purpose", "Interface definition", "Free-tier limits used"], [
    ["Google Gemini API (GEM)", "v1beta generateContent; model gemini-2.5-flash", "Brief narrative; chat with function calling", "HTTPS JSON; x-goog-api-key header; responseSchema; tools.functionDeclarations", "AI Studio free tier (brief cites 15 RPM / 1,500 RPD); design budget ≤ 60 req/day"],
    ["Open-Meteo Forecast (OMF)", "api.open-meteo.com/v1/forecast", "Tomorrow's weather", "HTTPS GET; daily=temperature_2m_max, precipitation_sum, precipitation_probability_max, weather_code; timezone=Europe/London", "No key; < 10,000 calls/day (non-commercial)"],
    ["Open-Meteo Historical (OMH)", "archive-api.open-meteo.com/v1/archive", "Weather back-fill", "HTTPS GET; same daily variables; start_date / end_date", "As above"],
    ["Twilio SendGrid (SGM)", "v3 POST /v3/mail/send", "Brief, recap and nudge emails", "Bearer API key; JSON personalizations, from, subject, content[text/plain, text/html]", "Free trial allowance; ≤ 10 emails/day needed"],
    ["Neon PostgreSQL (DB)", "PostgreSQL 16", "System of record", "TLS connection string; Prisma ORM 6.x", "~0.5 GB storage free plan"],
    ["Google Cloud Run (RUN)", "Managed container", "Hosts the Next.js app and API", "HTTPS; container on port 8080; min-instances 0", "2M requests, 180k vCPU-s, 360k GiB-s / month"],
    ["Google Cloud Scheduler (SCH)", "v1", "Proactive triggers", "HTTP target with OIDC token (service account)", "3 jobs free"],
    ["Runtime / frameworks", "Node.js 20 LTS; Next.js 15; React 19; Prisma 6; NextAuth 4; Recharts 2", "Application platform", "npm packages", "Open source"],
  ], [17, 18, 16, 29, 20]),
  p("**Communications interfaces:** all client–server and server–third-party traffic uses HTTPS with TLS 1.2 or higher; the browser uses JSON over fetch, and chat responses stream over HTTP; email is delivered through the SendGrid HTTP API (no direct SMTP); Cloud Scheduler calls the API with an OIDC bearer token whose audience is the service URL."),
  p("**Hardware interfaces and limitations:** OpsPilot runs in a standard web browser and on managed cloud infrastructure; no POS terminals, printers or other devices are integrated in v1. Cloud Run instances are limited to 1 vCPU and 512 MiB–1 GiB and scale to zero, so heavy computation is done in SQL aggregations and no in-memory state is relied on between requests. The Neon free plan may suspend compute after inactivity (first-query latency of up to ~1 s)."),
  ...table("Free-Tier Budget", ["Service", "Free allowance", "Expected monthly use (1 site)", "Headroom"], [
    ["Gemini 2.5 Flash", "Per AI Studio free tier (daily cap)", "≤ 60 requests/day", "Budgeted well below the daily cap"],
    ["Open-Meteo", "< 10,000 calls/day", "~10 calls/day (cached)", "> 99%"],
    ["SendGrid", "Free trial allowance", "~40 emails/month", "Ample"],
    ["Neon Postgres", "~0.5 GB storage", "~40 MB (120 days, ~30k orders, ~90k lines)", "> 90%"],
    ["Cloud Run", "2M requests; 180k vCPU-s", "< 20k requests; < 20k vCPU-s", "> 85%"],
    ["Cloud Scheduler", "3 jobs", "3 jobs", "At limit by design"],
  ], [20, 25, 32, 23]),

  H2("2.3 Access Control"),
  p("Access is role-based. Owners have full control; Managers can see and act on operations but cannot change configuration or data; the scheduler's service account can only call the cron endpoints. Enforcement is layered: middleware checks the session, each route handler checks the role, and services re-validate ownership of the site."),
  ...figure("fig_access.png", "Access Control Diagram"),
  ...reqTable("AUTH"),
  p("**Security requirements:**"),
  ...bullets([
    "API keys and database credentials are stored in environment variables / Google Secret Manager, never committed or exposed to the client.",
    "Passwords are hashed with bcrypt; sessions use signed, HTTP-only, secure cookies.",
    "Role-based authorisation is enforced server-side on every route (FR-AUTH-04); cron endpoints require OIDC or a secret (FR-NTF-03).",
    "AI tool calls are restricted to whitelisted, argument-validated functions; the model cannot execute SQL or arbitrary code. User chat input is treated as untrusted and cannot alter the system instruction or tool list.",
    "Personal data is minimised: only staff first names reach Gemini; the data is not used for other purposes.",
    "Input validation (Zod schemas) is applied to every API request and to CSV rows; request bodies are limited to 5 MB.",
    "Integrity: metric recomputation is transactional, and financial totals are cross-checked (the sum of dayparts equals the day total) with any mismatch logged.",
  ]),

  H2("2.4 Quality Attributes"),
  ...table("Performance Requirements", ["ID", "Requirement"], [
    ["PR-01", "Dashboard API responses (metrics, anomalies, outlook) shall complete within 1.5 s at the 95th percentile for a warm instance and a 120-day dataset."],
    ["PR-02", "The daily brief job shall complete end-to-end (metrics → email hand-off) within 60 s for one site, including at most two Gemini calls."],
    ["PR-03", "The chat shall stream its first token within 5 s at the 95th percentile (excluding cold start)."],
    ["PR-04", "Metric re-computation for one trading day shall complete within 5 s; a full 120-day seed within 3 minutes."],
    ["PR-05", "The system shall support 5 concurrent interactive users and 3 sites in v1 without degradation beyond PR-01."],
    ["PR-06", "Gemini usage shall not exceed 60 requests per day in normal operation (1–3 per brief, ≤ 2 per chat turn, 1 per weekly recap)."],
    ["PR-07", "Cold start of the Cloud Run instance shall not exceed 10 s; scheduled jobs shall tolerate it (Scheduler attempt deadline 180 s)."],
  ], [12, 88]),
  p("**Availability:** the target availability of the interactive UI is 99% during 06:00–23:00 Europe/London (best effort on free tiers). Scheduled jobs are checkpointed through JobRun, so a failed or partial job can be re-run safely, and Cloud Scheduler retries up to 3 times with back-off. Degradation order: AI unavailable → template brief; weather unavailable → weekday-only outlook; email unavailable → in-app brief with a delivery-failed status. Core metrics never depend on third-party APIs."),
  p("**Maintainability:** anomaly rules are registered through a common interface, so a new rule requires no change to the brief, task or UI code; third-party services are accessed only through adapter classes, so a provider can be swapped in one file; prompts and response schemas are versioned constants stored with each brief; the target unit-test coverage is at least 80% for the metrics, anomalies and Number Guard modules."),
  p("**Transferability:** the application is written 100% in TypeScript on Node.js 20 LTS and packaged as a standard OCI container (Next.js standalone output). It can run on Cloud Run, any container host or Vercel without code changes; the database is standard PostgreSQL; scheduling is endpoint-based, so Cloud Scheduler, GitHub Actions cron or Vercel Cron are interchangeable."),
  p("**Standards compliance:** currency in GBP (£); dates as dd MMM yyyy; times in 24-hour Europe/London; percentages to one decimal place; ratio differences in percentage points; revenue reported net of VAT, discounts and voids; labour cost includes employer on-cost (13.8% default); money stored as integer pence. Audit trail: JobRun, AiCallLog and SettingsAudit are written for every relevant event and retained for 90 days. Code quality: ESLint + Prettier; Vitest unit tests for every metric formula, anomaly rule and the Number Guard."),
  ...table("Operations", ["Mode", "Description"], [
    ["Unattended", "Three scheduled jobs (Cloud Scheduler Jobs table). No user action is required for the owner to receive the daily brief, follow-ups and weekly recap."],
    ["Interactive", "Dashboard, investigation, chat and settings during the day; manual Run now and Regenerate for Owners."],
    ["Data processing support", "Metric recomputation on ingestion; daily weather cache refresh; nightly clean-up of logs older than 90 days (executed within the daily job)."],
    ["Backup and recovery", "Neon point-in-time restore (free-plan retention); the seed is deterministic, so demo data can be rebuilt with one command; migrations are managed with Prisma Migrate."],
  ], [25, 75]),
  p("**Site adaptation:** per-site timezone, coordinates (for weather), trading-day start hour, daypart boundaries, targets (labour %, COGS %), thresholds (discount tolerance, cash variance), employer on-cost %, recipients and brief time. The initial demo site is \"The Copper Pot\", an independent 80-cover restaurant in Manchester (53.4808, −2.2426), Europe/London, GBP. Future adaptation points: POS connectors (Square, Toast) implementing the same ingestion interface; rota connectors; additional currencies and locales."),
);

// ----- 3 OBJECT MODEL -----
B.push(
  H1("3. OBJECT MODEL"),
  H2("3.1 Class Diagram"),
  p("The object model is shown in two views: the domain model (persistent entities stored in PostgreSQL through Prisma) and the service model (the classes that implement the behaviour). Attribute and operation details are given in Section 4."),
  ...figure("fig_class_domain.png", "Class Diagram — Domain Model"),
  ...figure("fig_class_services.png", "Class Diagram — Services"),
  H2("3.2 Sequence Diagrams"),
  H3("Authentication"),
  ...figure("fig_seq_auth.png", "Sequence Diagram - Authentication"),
  H3("Daily Operations Brief"),
  p("The proactive 07:00 job, from the Cloud Scheduler trigger to the delivered email. Steps 12–13 show the Number Guard and fallback that keep AI text grounded in computed figures."),
  ...figure("fig_seq_daily.png", "Sequence Diagram - Daily Operations Brief"),
  H3("Ask OpsPilot"),
  p("A manager's question answered through Gemini function calling. The model can only call whitelisted tools, and a side-effecting action (create_task) is executed only after the user confirms it."),
  ...figure("fig_seq_chat.png", "Sequence Diagram - Ask OpsPilot"),
  H2("3.3 State Chart Diagram"),
  H3("Investigation Task"),
  ...figure("fig_state_task.png", "State-Chart Diagram - Investigation Task"),
  H3("Brief Generation"),
  ...figure("fig_state_brief.png", "State-Chart Diagram - Brief Generation"),
);

// ----- 4 DETAILED DESIGN -----
B.push(
  H1("4. DETAILED DESIGN"),
  p("Detailed design breaks the object model into its individual classes and specifies how each should behave. For every class the class box, the description of its attributes (type, visibility and invariant) and the description of its operations (visibility, return type, arguments, pre-condition and post-condition) are given. Persistent entities are implemented as Prisma models; services are TypeScript classes in src/server. Money is always integer pence."),
);
CLASSES.forEach((c) => {
  B.push(H3(c.name), p(c.desc));
  B.push(...classBox(c.name,
    c.attrs.map((a) => `${a[2] === "Public" ? "+" : "-"}${a[0]} : ${a[1]}`),
    c.ops.map((o) => `${o[1] === "Public" ? "+" : "-"}${o[0]}(${o[3] === "None" ? "" : o[3]}) : ${o[2]}`), c.stereo));
  if (c.attrs.length) B.push(...table(`Attribute Description for ${c.name} Class`, ["Attribute", "Type", "Visibility", "Invariant"], c.attrs, [20, 16, 13, 51]));
  if (c.ops.length) B.push(...table(`Operation Description for ${c.name} Class`, ["Operation", "Visibility", "Return Type", "Argument", "Pre-Condition", "Post-Condition"], c.ops, [15, 11, 13, 18, 20, 23]));
});
B.push(H2("Enumerated Tables"));
ENUMS.forEach(([name, desc, vals]) => {
  B.push(tableCaption(`${name} Enumeration Class`), p(desc));
  const w = [CW];
  B.push(new Table({ width: { size: CW, type: WidthType.DXA }, columnWidths: w, rows: [
    new TableRow({ children: [cell(name, CW, { bold: true, fill: HEAD_FILL, color: "FFFFFF" })] }),
    ...vals.map((v, i) => new TableRow({ children: [cell(v, CW, { fill: i % 2 ? ROW_B : ROW_A })] })),
  ] }), spacer(120));
});

// ----- APPENDICES -----
const tmRows = [];
Object.keys(REQ).forEach((k) => REQ[k].items.forEach((r, i) => tmRows.push([reqId(k, i), REQ[k].title, REQ[k].uc, REQ[k].scr, REQ[k].api, `T-${k}-${String(i + 1).padStart(2, "0")}`, ""])));
["PR-01", "PR-02", "PR-03", "PR-04", "PR-05", "PR-06", "PR-07"].forEach((id) => tmRows.push([id, "Performance", "—", "—", "—", `T-${id}`, ""]));
B.push(
  H1("APPENDICES"),
  H3("Software Design Development Tools"),
  p("For the design and development of the software, the following tools are used:"),
  ...bullets([
    "Diagrams authored as code (SVG generated by a Node.js script) and rendered with headless Google Chrome.",
    "This document generated with docx-js from a single requirements source, so the traceability matrix always matches Section 2.",
    "Visual Studio Code / Cursor and Claude Code for development; Prisma Studio for data inspection.",
    "Google AI Studio for prompt and schema prototyping; Postman for API testing.",
    "Vitest (unit), Playwright (smoke), Docker and the gcloud CLI for build and deployment.",
  ]),
  H2("Appendix A — AI Contracts"),
  p("This appendix is normative where referenced by FR-BRF-02 to FR-BRF-05."),
  H3("A.1 FactSheet (excerpt)"),
  ...code([
    "{",
    "  \"site\": \"The Copper Pot\", \"date\": \"2026-09-27\", \"weekday\": \"Saturday\",",
    "  \"facts\": [",
    "    { \"id\": \"rev.net\",           \"value\": 824000, \"unit\": \"pence\", \"display\": \"£8,240\" },",
    "    { \"id\": \"rev.net.vs_4wk\",    \"value\": -0.081, \"unit\": \"ratio\", \"display\": \"-8.1%\" },",
    "    { \"id\": \"lab.pct\",           \"value\": 0.312,  \"unit\": \"ratio\", \"display\": \"31.2%\" },",
    "    { \"id\": \"lab.pct.vs_target\", \"value\": 0.052,  \"unit\": \"pt\",    \"display\": \"+5.2 pt\" },",
    "    { \"id\": \"disc.rate.x_base\",  \"value\": 2.3,    \"unit\": \"x\",     \"display\": \"2.3×\" }",
    "  ],",
    "  \"anomalies\": [ { \"id\": \"an_812\", \"rule\": \"AR-01\", \"severity\": \"critical\",",
    "      \"contributor\": \"Sam K.\", \"share_display\": \"68%\", \"daypart\": \"Dinner\" } ],",
    "  \"outlook\": { \"tMax_display\": \"24°C\", \"rev_range_display\": \"£8,900–£9,700\",",
    "      \"labour_cap_display\": \"118 h\" }",
    "}",
  ]),
  spacer(),
  H3("A.2 Brief Response Schema"),
  ...code([
    "{ type: OBJECT, required: [headline, summary, sections, actions], properties: {",
    "  headline: { type: STRING },                    // <= 140 chars",
    "  summary:  { type: STRING },                    // <= 3 sentences",
    "  sections: { type: ARRAY, items: { type: OBJECT, properties: {",
    "      title: STRING, body: STRING, factIds: { type: ARRAY, items: STRING } } } },",
    "  actions:  { type: ARRAY, items: { type: OBJECT, properties: {",
    "      title: STRING, rationale: STRING, anomalyId: STRING,",
    "      priority: { type: STRING, enum: [high, medium, low] } } } } } }",
  ]),
  spacer(),
  H3("A.3 Number Guard Algorithm"),
  ...numbered([
    "Tokenise all AI text fields; extract numeric tokens with the pattern [£]?[-+]?\\d[\\d,]*(\\.\\d+)?\\s?(%|pt|×|x|h|°C)?",
    "Normalise each token (remove separators and currency; convert % to a ratio).",
    "Accept a token if it equals a FactSheet display string, or a FactSheet value within half of the last displayed digit, or a date/time in the context.",
    "Otherwise record it as a violation. Any violation causes the output to fail (FR-BRF-06).",
  ]),
  H2("Appendix B — Sample Daily Brief Email"),
  ...table(null, null, [[[
    "**Subject:** The Copper Pot · Sat 27 Sep — Revenue −8.1%, discounts 2.3× normal",
    "**Today's Operations Brief**",
    "Revenue was £8,240, 8.1% below the 4-week Saturday median, driven by a weaker Dinner.",
    "Labour ran at 31.2% of revenue, +5.2 pt over target, concentrated in the Dinner shift.",
    "Discounts were 2.3× the normal Saturday level; Sam K. accounts for 68% of the excess.",
    "**Needs attention:** ● Critical — discount spike (Sam K., Dinner) · ● Warning — labour over target (Dinner).",
    "**Tomorrow:** 24°C and dry; expect £8,900–£9,700; keep labour under 118 h; prep extra iced drinks.",
    "[Open dashboard]   [View investigations]",
  ]]], [1], { plainFirst: true }),
  H2("Appendix C — Delivery Plan"),
  ...table("Delivery Plan and Milestones", ["#", "Milestone", "Output", "Est."], [
    ["0", "SRS approval", "This document approved by Brain3.ai", "—"],
    ["1", "Scaffold", "Next.js + TS + Tailwind + Prisma/Neon + NextAuth; CI lint/test", "1 h"],
    ["2", "Data", "Schema, seed with scenarios S1–S5, weather back-fill, simulate-day, CSV import", "3 h"],
    ["3", "Metrics & anomalies", "KPI functions, baselines, rule registry, unit tests", "3 h"],
    ["4", "AI", "FactSheet, Gemini brief, Number Guard, template fallback, chat tools", "3 h"],
    ["5", "Outlook", "Forecast, weather factor, labour cap, prep hints", "1.5 h"],
    ["6", "Jobs & email", "Cron endpoints, JobRun, SendGrid templates, follow-up", "2 h"],
    ["7", "Frontend", "SCR-01 to SCR-09, responsive layout", "5 h"],
    ["8", "Deploy", "Dockerfile, Cloud Run, 3 Scheduler jobs (or GitHub Actions fallback), README", "2 h"],
    ["9", "Submission", "Demo video (problem → design → live demo → code walkthrough), repository link", "2 h"],
  ], [5, 20, 63, 12]),
  H2("Appendix D — Requirements Traceability Matrix"),
  p("Each requirement maps to at least one use case, screen or API and to a verification test. Tests prefixed T- are automated (Vitest/Playwright) where the requirement is deterministic, and manual demo checks where it involves an external service. The status column is completed during the build."),
  ...table("Requirements Traceability Matrix", ["Req. ID", "Feature", "Use case", "Screen", "API", "Test", "Status"], tmRows, [11, 25, 12, 12, 17, 12, 11]),
);

// ----- REFERENCES -----
B.push(
  H1("REFERENCES"),
  H3("Bibliography"),
  ...bullets([
    "IEEE Std 830-1998, Recommended Practice for Software Requirements Specifications. IEEE.",
    "Pressman, R. S., & Maxim, B. R. (2015). Software engineering: a practitioner's approach. McGraw-Hill Education.",
    "Brain3.ai (2026). AI Automation Assignment — Full Stack AI Web Developer (brief).",
  ]),
  H3("Web Resources"),
  ...bullets([
    "Gemini API documentation — generateContent, structured output, function calling: ai.google.dev/gemini-api/docs (accessed Sep 2026).",
    "Open-Meteo Forecast API and Historical Weather API: open-meteo.com/en/docs (accessed Sep 2026).",
    "Twilio SendGrid v3 Mail Send API: docs.sendgrid.com/api-reference/mail-send (accessed Sep 2026).",
    "Google Cloud Run, Cloud Scheduler and Free Tier documentation: cloud.google.com (accessed Sep 2026).",
    "Neon serverless Postgres documentation and free plan: neon.tech/docs (accessed Sep 2026).",
    "Next.js 15, Prisma ORM and NextAuth.js documentation: nextjs.org, prisma.io, next-auth.js.org (accessed Sep 2026).",
    "UK GDPR / Data Protection Act 2018 guidance for employers: ico.org.uk (accessed Sep 2026).",
  ]),
);

// ================= front matter (built after the body so the lists are complete) =================
const F = [];
F.push(
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 2400, after: 200 }, children: [run("Software Requirements Specification", { size: 32 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: [run("OpsPilot", { size: 64, bold: true, color: ACCENT })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 1600 }, children: [run("AI Operations Manager for Independent Restaurants", { size: 30, color: MUTED })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 }, children: [run(`${DOC_ID} · Version ${VERSION} · ${MONTH_YEAR}`, { size: 22, color: MUTED })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 }, children: [run(`Prepared by ${AUTHOR}`, { size: 22, color: MUTED })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [run("Prepared for Brain3.ai — AI Automation Assignment (Full Stack AI Web Developer)", { size: 22, color: MUTED })] }),

  H1("DOCUMENT CONTROL"),
  ...table(null, null, [
    ["Project / identification no.", `OpsPilot / ${DOC_ID}`],
    ["Version", `${VERSION} — for review and approval`],
    ["Date", MONTH_YEAR],
    ["Document maturity", "Draft for approval"],
    ["Keywords", "Restaurant operations; hospitality; AI agent; anomaly detection; labour cost; discounts and voids; cash-up variance; Gemini API; Open-Meteo; SendGrid; Cloud Scheduler; Cloud Run; Next.js; PostgreSQL"],
  ], [30, 70]),
  p("**Approval**", { run: { color: ACCENT } }),
  ...table(null, ["Author", "Reviewer / Approver", "Product Owner"], [[AUTHOR, "Kidus — Brain3.ai", "Brain3.ai"], ["Signature / date:", "Signature / date:", "Signature / date:"]], [1, 1, 1], { plainFirst: true }),
  p("**Revision History**", { run: { color: ACCENT } }),
  ...table(null, ["Version", "Date", "Author", "Change description"], [
    ["1.0", DATE, AUTHOR, "Initial version (IEEE 830 template)."],
    [VERSION, DATE, AUTHOR, "Same content reorganised into the design-specification format: object model, detailed class design and enumerations added."],
  ], [12, 20, 20, 48]),

  new Paragraph({ pageBreakBefore: true, spacing: { after: 200 }, children: [run("Table of Contents", { size: 32, color: ACCENT })] }),
  new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-3" }),
  p("(If page numbers are not shown, right-click the table and choose \"Update Field\".)", { run: { italics: true, size: 18, color: MUTED } }),

  H1("LIST OF TABLES"),
  ...TABLES.map((t, i) => new Paragraph({ spacing: { after: 40 }, indent: { left: 360 }, children: [run(`Table: ${i + 1} ${t}`, { size: 21 })] })),
  H1("LIST OF FIGURES"),
  ...FIGURES.map((t, i) => new Paragraph({ spacing: { after: 60 }, indent: { left: 360 }, children: [run(`Figure ${i + 1}: ${t}`, { size: 21 })] })),
);

// ---------- document ----------
const footer = new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ font: FONT, size: 20, children: [PageNumber.CURRENT] })] })] });
const emptyFooter = new Footer({ children: [new Paragraph({ children: [] })] });
const level0 = (text, fmt) => [{ level: 0, format: fmt, text, alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }];

const doc = new Document({
  creator: AUTHOR, title: "OpsPilot — Software Requirements Specification",
  description: "SRS for OpsPilot, an AI Operations Manager for independent restaurants",
  features: { updateFields: true },
  styles: {
    default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 32, font: FONT, color: ACCENT }, paragraph: { spacing: { before: 240, after: 240 }, indent: { left: 360 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 28, font: FONT, color: ACCENT }, paragraph: { spacing: { before: 300, after: 160 }, indent: { left: 720 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 24, font: FONT, color: ACCENT }, paragraph: { spacing: { before: 240, after: 120 }, indent: { left: 720 }, outlineLevel: 2 } },
    ],
  },
  numbering: { config: [
    { reference: "bullets", levels: level0("●", LevelFormat.BULLET) },
    { reference: "arrows", levels: level0("➢", LevelFormat.BULLET) },
    ...NUM_REFS.map((r) => ({ reference: r, levels: level0("%1.", LevelFormat.DECIMAL) })),
  ] },
  sections: [{
    properties: { titlePage: true, page: { size: { width: PAGE_W, height: PAGE_H }, margin: { top: 1247, bottom: 1247, left: MARGIN, right: MARGIN, footer: 600 }, pageNumbers: { start: 0 } } },
    footers: { default: footer, first: emptyFooter },
    children: [...F, ...B],
  }],
});

const out = path.join(__dirname, `OpsPilot_SRS_v${VERSION}.docx`);
Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(out, buf); console.log("Wrote", out, `| ${TABLES.length} tables, ${FIGURES.length} figures, ${tmRows.length} traced requirements`); });
