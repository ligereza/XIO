#!/usr/bin/env python3
"""Safely identify the HyperOS portable-hotspot switch from a UI dump.

The probe is deliberately conservative: it returns a switch only when a
hotspot-related label and exactly one enabled/checkable node occur in the same
small UI subtree. It never chooses the first checkbox and never supplies a
fallback coordinate.

Input:  uiautomator XML on stdin
Output: STATE|CENTER_X|CENTER_Y|LABEL, or UNKNOWN
"""

from __future__ import annotations

import re
import sys
import unicodedata
import xml.etree.ElementTree as ET


HINTS = (
    "portable hotspot",
    "punto de acceso portatil",
    "hotspot",
    "punto de acceso",
    "zona wi fi portatil",
    "compartir internet",
    "anclaje",
    "tethering",
)
BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("-", " ").replace("_", " ")
    return " ".join(value.casefold().split())


def label(node: ET.Element) -> str:
    return " ".join(
        part.strip()
        for part in (
            node.attrib.get("text", ""),
            node.attrib.get("content-desc", ""),
            node.attrib.get("resource-id", ""),
        )
        if part and part.strip()
    )


def contains_hint(node: ET.Element) -> str | None:
    for descendant in node.iter("node"):
        text = normalize(label(descendant))
        for hint in HINTS:
            if hint in text:
                return hint
    return None


def parse_bounds(value: str) -> tuple[int, int, int, int] | None:
    match = BOUNDS_RE.fullmatch(value or "")
    if not match:
        return None
    x1, y1, x2, y2 = map(int, match.groups())
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def checkable_nodes(node: ET.Element) -> list[ET.Element]:
    result = []
    for descendant in node.iter("node"):
        if descendant.attrib.get("checkable") != "true":
            continue
        if descendant.attrib.get("enabled", "true") != "true":
            continue
        if parse_bounds(descendant.attrib.get("bounds", "")) is None:
            continue
        result.append(descendant)
    return result


def subtree_size(node: ET.Element) -> int:
    return sum(1 for _ in node.iter("node"))


def main() -> int:
    xml_text = sys.stdin.read()
    if not xml_text.strip():
        print("UNKNOWN")
        return 2
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        print("UNKNOWN")
        return 2

    candidates: dict[tuple[str, str], tuple[int, ET.Element, str]] = {}
    for node in root.iter("node"):
        hint = contains_hint(node)
        if hint is None:
            continue
        checks = checkable_nodes(node)
        if len(checks) != 1:
            continue
        switch = checks[0]
        key = (switch.attrib.get("bounds", ""), switch.attrib.get("checked", ""))
        candidates[key] = (subtree_size(node), switch, hint)

    if not candidates:
        print("UNKNOWN")
        return 1

    ordered = sorted(candidates.values(), key=lambda item: item[0])
    smallest_size = ordered[0][0]
    smallest = [item for item in ordered if item[0] == smallest_size]
    if len(smallest) != 1:
        print("UNKNOWN")
        return 1

    _, switch, hint = smallest[0]
    bounds = parse_bounds(switch.attrib.get("bounds", ""))
    checked = switch.attrib.get("checked")
    if bounds is None or checked not in {"true", "false"}:
        print("UNKNOWN")
        return 1
    x1, y1, x2, y2 = bounds
    label_value = normalize(hint).replace("|", " ")
    print(f"{'ON' if checked == 'true' else 'OFF'}|{(x1 + x2) // 2}|{(y1 + y2) // 2}|{label_value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
