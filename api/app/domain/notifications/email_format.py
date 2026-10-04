"""Plain-text and HTML bodies styled like the OpsPilot web app (inline CSS, table layout)."""

from dataclasses import dataclass, field
from html import escape
from typing import Literal

# Match web/app/globals.css (light theme)
BG = "#f0f4ff"
SURFACE = "#ffffff"
TEXT = "#1c1c1a"
MUTED = "#6b6b66"
BORDER = "#e4e4df"
ACCENT = "#5be49b"
CHIP = "#efefea"
WARNING_BG = "#fdf3e2"
WARNING = "#a15c07"
INFO_BG = "#e8f0fb"
INFO = "#1d5fa8"
POSITIVE_BG = "#e6f4ec"
POSITIVE = "#1d7a46"
NEGATIVE_BG = "#fdecea"
NEGATIVE = "#b42318"

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


@dataclass(frozen=True)
class Metric:
    label: str
    value: str
    sub: str


@dataclass(frozen=True)
class Highlight:
    title: str
    detail: str
    tone: Literal["warning", "info", "neutral"] = "neutral"


@dataclass(frozen=True)
class RiskItem:
    title: str
    impact: str
    severity: str


@dataclass(frozen=True)
class Section:
    title: str
    lines: list[str] = field(default_factory=list)
    metrics: list[Metric] | None = None
    highlights: list[Highlight] | None = None
    risks: list[RiskItem] | None = None


def _badge(label: str, bg: str, fg: str) -> str:
    style = f"display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600;background:{bg};color:{fg};"
    return f'<span style="{style}">{escape(label)}</span>'


def _severity_badge(severity: str) -> str:
    s = severity.lower()
    if s == "critical":
        return _badge(severity, NEGATIVE_BG, NEGATIVE)
    if s == "warning":
        return _badge(severity, WARNING_BG, WARNING)
    return _badge(severity, INFO_BG, INFO)


def _section_text(title: str, lines: list[str]) -> list[str]:
    if not lines:
        return []
    return [title, *[f"- {line.lstrip('- ')}" for line in lines], ""]


def _card_open(title: str) -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:0 0 20px;border:1px solid {BORDER};border-radius:12px;overflow:hidden;background:{SURFACE};">'
        f'<tr><td style="padding:12px 16px;border-bottom:1px solid {BORDER};background:{SURFACE};">'
        f'<span style="font-size:13px;font-weight:600;color:{TEXT};">{escape(title)}</span></td></tr>'
        f'<tr><td style="padding:16px;">'
    )


def _card_close() -> str:
    return "</td></tr></table>"


def _metrics_html(metrics: list[Metric]) -> str:
    cells = []
    for m in metrics:
        cells.append(
            f'<td width="50%" valign="top" style="padding:6px;">'
            f'<div style="border:1px solid {BORDER};border-radius:12px;padding:14px 16px;background:{SURFACE};">'
            f'<div style="font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;color:{MUTED};">'
            f"{escape(m.label)}</div>"
            f'<div style="margin-top:6px;font-size:22px;font-weight:600;color:{TEXT};line-height:1.2;">{escape(m.value)}</div>'
            f'<div style="margin-top:6px;font-size:13px;color:{MUTED};">{escape(m.sub)}</div>'
            f"</div></td>"
        )
    rows = ""
    for i in range(0, len(cells), 2):
        pair = cells[i : i + 2]
        if len(pair) == 1:
            pair.append(f'<td width="50%" style="padding:6px;"></td>')
        rows += f"<tr>{''.join(pair)}</tr>"
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table>'


def _highlights_html(items: list[Highlight]) -> str:
    out = ""
    for h in items:
        if h.tone == "warning":
            bg, border, accent = WARNING_BG, WARNING, WARNING
        elif h.tone == "info":
            bg, border, accent = INFO_BG, INFO, INFO
        else:
            bg, border, accent = CHIP, BORDER, MUTED
        box = (
            f"margin:0 0 10px;padding:14px 16px;border-radius:10px;border:1px solid {border};"
            f"border-left:4px solid {accent};background:{bg};"
        )
        out += (
            f'<div style="{box}">'
            f'<div style="font-size:15px;font-weight:600;color:{TEXT};">{escape(h.title)}</div>'
            f'<div style="margin-top:4px;font-size:13px;line-height:1.5;color:{MUTED};">{escape(h.detail)}</div>'
            f"</div>"
        )
    return out


def _risks_html(items: list[RiskItem]) -> str:
    if not items:
        return f'<p style="margin:0;font-size:14px;color:{MUTED};">No open risks.</p>'
    out = ""
    for r in items:
        out += (
            f'<div style="margin:0 0 10px;padding:12px 14px;border:1px solid {BORDER};border-radius:10px;">'
            f'<div style="font-size:14px;font-weight:600;color:{TEXT};">{escape(r.title)}</div>'
            f'<div style="margin-top:8px;font-size:13px;color:{MUTED};">{escape(r.impact)}</div>'
            f'<div style="margin-top:8px;">{_severity_badge(r.severity)}</div></div>'
        )
    return out


def _lines_html(lines: list[str]) -> str:
    out = ""
    for line in lines:
        out += (
            f'<div style="margin:0 0 8px;padding:10px 12px;border:1px solid {BORDER};border-radius:8px;'
            f'font-size:14px;line-height:1.5;color:{TEXT};">{escape(line.lstrip("- "))}</div>'
        )
    return out


def _section_html(section: Section) -> str:
    inner = ""
    if section.metrics:
        inner += _metrics_html(section.metrics)
    if section.highlights:
        inner += _highlights_html(section.highlights)
    if section.risks is not None:
        inner += _risks_html(section.risks)
    if section.lines:
        inner += _lines_html(section.lines)
    if not inner.strip():
        return ""
    return _card_open(section.title) + inner + _card_close()


def _shell(*, nav_title: str, headline: str, intro: str, body: str, footer: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<title>{escape(headline)}</title>
</head>
<body style="margin:0;padding:0;background:{BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG};padding:28px 12px 40px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">
<tr><td style="padding:0 4px 12px;font-family:{FONT};">
<span style="font-size:18px;font-weight:700;letter-spacing:-0.02em;color:{TEXT};">OpsPilot</span>
</td></tr>
<tr><td>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{SURFACE};border:1px solid {BORDER};border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(28,28,26,0.06);">
<tr><td style="padding:0;background:{ACCENT};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td style="padding:24px 28px;font-family:{FONT};">
<div style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;color:{TEXT};opacity:0.75;">{escape(nav_title)}</div>
<h1 style="margin:8px 0 0;font-size:26px;font-weight:600;line-height:1.25;color:{TEXT};">{escape(headline)}</h1>
</td></tr></table>
</td></tr>
<tr><td style="padding:24px 28px 8px;font-family:{FONT};">
<p style="margin:0;font-size:15px;line-height:1.6;color:{MUTED};">{escape(intro)}</p>
</td></tr>
<tr><td style="padding:8px 20px 24px;font-family:{FONT};">
{body}
</td></tr>
<tr><td style="padding:16px 28px;border-top:1px solid {BORDER};background:#fafafa;font-family:{FONT};font-size:12px;line-height:1.5;color:{MUTED};">
{escape(footer)}
</td></tr>
</table>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def render_email(*, nav_title: str, headline: str, intro: str, sections: list[Section],
                 footer: str | None = None) -> tuple[str, str]:
    foot = footer or "Sent by OpsPilot · AI restaurant operations"
    text_parts = [headline, intro, ""]
    for s in sections:
        if s.metrics:
            text_parts.extend(_section_text(s.title, [f"{m.label}: {m.value} ({m.sub})" for m in s.metrics]))
        elif s.highlights:
            text_parts.extend(_section_text(s.title, [f"{h.title} — {h.detail}" for h in s.highlights]))
        elif s.risks is not None:
            text_parts.extend(_section_text(s.title, [f"{r.title} · {r.impact} ({r.severity})" for r in s.risks] or ["No open risks."]))
        else:
            text_parts.extend(_section_text(s.title, s.lines))
    text_parts.append(foot)
    text = "\n".join(text_parts).strip()
    html = _shell(nav_title=nav_title, headline=headline, intro=intro,
                  body="".join(_section_html(s) for s in sections), footer=foot)
    return text, html


def render_table_section(title: str, headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(
        f'<th style="padding:12px 14px;text-align:left;font-size:11px;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:0.05em;color:{MUTED};background:{CHIP};border-bottom:1px solid {BORDER};">{escape(h)}</th>'
        for h in headers
    )
    body = ""
    for i, row in enumerate(rows):
        bg = SURFACE if i % 2 == 0 else "#fafbff"
        cells = "".join(
            f'<td style="padding:12px 14px;font-size:14px;color:{TEXT};background:{bg};border-bottom:1px solid {BORDER};">'
            f"{escape(c)}</td>" for c in row
        )
        body += f"<tr>{cells}</tr>"
    table = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
        f'border:1px solid {BORDER};border-radius:10px;overflow:hidden;"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )
    return _card_open(title) + table + _card_close()


def render_po_email(*, greeting: str, intro: str, table_headers: list[str], table_rows: list[list[str]],
                    summary_lines: list[str], footer: str) -> tuple[str, str]:
    text_lines = [greeting, "", intro, ""]
    for row in table_rows:
        text_lines.append("  · ".join(row))
    text_lines.extend(["", *summary_lines, "", footer])
    text = "\n".join(text_lines)

    summary_html = "".join(
        f'<p style="margin:0 0 8px;font-size:14px;color:{TEXT};">{escape(line)}</p>' for line in summary_lines
    )
    body = (
        f'<p style="margin:0 0 16px;font-size:16px;font-weight:500;color:{TEXT};">{escape(greeting)}</p>'
        f'<p style="margin:0 0 20px;font-size:14px;line-height:1.6;color:{MUTED};">{escape(intro)}</p>'
        + render_table_section("Order lines", table_headers, table_rows)
        + f'<div style="margin-top:16px;padding:16px;border-radius:12px;background:{CHIP};">{summary_html}</div>'
    )
    html = _shell(nav_title="Purchase order", headline="New order to fulfil", intro="Please confirm receipt of this order.", body=body, footer=footer)
    return text, html
