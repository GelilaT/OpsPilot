"""Number Guard (FR-RCA-07, FR-BRF-02): AI text may only contain numbers present in its facts.

A number written in the text is accepted when some fact value, rounded to the number of decimals the text
uses, equals it ("18.0%" matches a fact of -18.04 or 18.0; "7,410" matches 7410.12). Signs are ignored
(text says "down 18%" for a fact of -18). Evidence and cause texts are checked against the facts of the
node they cite; the finding and next action against all nodes.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

NUMBER = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])-?\d+(?:\.\d+)?")


def numbers_in(text: str) -> list[tuple[Decimal, int]]:
    """(absolute value, decimals) for every number in `text`."""
    out = []
    for raw in NUMBER.findall(text or ""):
        clean = raw.replace(",", "").lstrip("-")
        try:
            value = Decimal(clean)
        except InvalidOperation:
            continue
        decimals = len(clean.split(".")[1]) if "." in clean else 0
        out.append((value, decimals))
    return out


def _fact_values(value: Any, out: list[Decimal]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float, Decimal)):
        out.append(abs(Decimal(str(value))))
    elif isinstance(value, str):
        out.extend(v for v, _ in numbers_in(value))
    elif isinstance(value, dict):
        for v in value.values():
            _fact_values(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _fact_values(v, out)


def fact_values(nodes: list[dict[str, Any]]) -> list[Decimal]:
    out: list[Decimal] = []
    for node in nodes:
        _fact_values(node.get("facts", {}), out)
        _fact_values(node.get("label", ""), out)
    return out


def _matches(value: Decimal, decimals: int, facts: list[Decimal]) -> bool:
    q = Decimal(1).scaleb(-decimals)
    return any(f.quantize(q) == value.quantize(q) for f in facts)


def violations(text: str, nodes: list[dict[str, Any]]) -> list[str]:
    facts = fact_values(nodes)
    return [f"{v}" for v, d in numbers_in(text) if not _matches(v, d, facts)]


def check_narrative(narrative: dict[str, Any], nodes: list[dict[str, Any]]) -> list[str]:
    """All Number Guard violations of an A.3 narrative against the evidence graph nodes."""
    by_id = {n["id"]: n for n in nodes}
    problems: list[str] = []
    for field in ("finding", "next_action"):
        problems += [f"{field}: {v}" for v in violations(narrative.get(field, ""), nodes)]
    for ev in narrative.get("evidence", []):
        node = by_id.get(ev.get("node_id"))
        if node is None:
            problems.append(f"evidence cites unknown node {ev.get('node_id')!r}")
            continue
        problems += [f"evidence {node['id']}: {v}" for v in violations(ev.get("text", ""), [node])]
    for cause in narrative.get("causes", []):
        node = by_id.get(cause.get("confidence_node_id"))
        if node is None:
            problems.append(f"cause cites unknown node {cause.get('confidence_node_id')!r}")
            continue
        problems += [f"cause {node['id']}: {v}" for v in violations(cause.get("text", ""), [node])]
    return problems
