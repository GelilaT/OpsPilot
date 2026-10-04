// Shared SVG helpers for the specification diagrams.
const C = {
  navy: "#1F3A5F", blue: "#2F5597", teal: "#0F766E", amber: "#B45309", slate: "#475569", purple: "#6D28D9",
  ink: "#0F172A", line: "#64748B", bgNavy: "#EAF0F7", bgBlue: "#DAE3F3", bgTeal: "#E6F4F1", bgPurple: "#F1EBFD",
  bgAmber: "#FDF3E7", bgGrey: "#F1F5F9", white: "#FFFFFF", red: "#B91C1C", green: "#15803D", bgRed: "#FDECEC",
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
  if (lab) s += label(o.lx ?? (x1 + x2) / 2, o.ly ?? (y1 + y2) / 2 - 6, lab, { anchor: o.anchor, size: o.size });
  return s;
}
function path(d, lab, o = {}) {
  let s = `<path d="${d}" fill="none" stroke="${o.teal ? C.teal : C.line}" stroke-width="2" marker-end="url(#${o.teal ? "arrT" : "arr"})" ${o.dash ? "stroke-dasharray='6 5'" : ""}/>`;
  if (lab) s += label(o.lx, o.ly, lab, { anchor: o.anchor, size: o.size });
  return s;
}
function actor(x, y, lab) {
  return `<g stroke="${C.navy}" stroke-width="3" fill="none"><circle cx="${x}" cy="${y}" r="16"/><line x1="${x}" y1="${y + 16}" x2="${x}" y2="${y + 60}"/>
    <line x1="${x - 26}" y1="${y + 32}" x2="${x + 26}" y2="${y + 32}"/><line x1="${x}" y1="${y + 60}" x2="${x - 22}" y2="${y + 92}"/><line x1="${x}" y1="${y + 60}" x2="${x + 22}" y2="${y + 92}"/></g>` + text(x, y + 118, lab, { size: 16, bold: true });
}
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
// node box that returns geometry
function node(x, y, w, h, title, sub, o) { return { svg: box(x, y, w, h, title, sub || [], o || {}), cx: x + w / 2, cy: y + h / 2, w, h, shape: "rect", x, y }; }

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
  return { svg: s, cx: x + w / 2, cy: y + h / 2, w, h, x, y, shape: "rect" };
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
// msgs: [from, to, text, isReturn] | {frame, label, from, to, rows} | {gap}
function sequence(lanes, ext, msgs, W, H) {
  let b = "", body = "";
  const X = lanes.map((_, i) => 110 + i * ((W - 220) / (lanes.length - 1)));
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
const stateNode = (x, y, w, h, t, sub, o = {}) => node(x, y, w, h, t, sub ? (Array.isArray(sub) ? sub : [sub]) : [], { rx: 24, fill: o.fill || C.bgBlue, stroke: o.stroke || C.blue, fs: o.fs || 17, ss: 13, lh: 19 });
const startDot = (x, y) => `<circle cx="${x}" cy="${y}" r="13" fill="${C.ink}"/>`;
const endDot = (x, y) => `<circle cx="${x}" cy="${y}" r="15" fill="none" stroke="${C.ink}" stroke-width="2.5"/><circle cx="${x}" cy="${y}" r="9" fill="${C.ink}"/>`;

module.exports = { C, esc, FONT, svg, text, label, box, arrow, path, actor, edge, conn, node, uml, rel, sequence, stateNode, startDot, endDot };
