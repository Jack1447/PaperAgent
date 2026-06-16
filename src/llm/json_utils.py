"""Utilities for extracting and normalizing JSON from LLM responses."""
from __future__ import annotations

import json
import re
from typing import Any


def extract_json_value(raw: str) -> Any:
    """Extract a JSON object or array from a possibly fenced LLM response."""

    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    candidates = [
        _extract_balanced(text, "[", "]"),
        _extract_balanced(text, "{", "}"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    raise ValueError("No valid JSON object or array found in LLM response")


def normalize_planner_subtopics(value: Any, fallback_query: str = "") -> list[dict[str, Any]]:
    """Normalize planner JSON into a list of valid subtopic dictionaries."""

    if isinstance(value, dict):
        if isinstance(value.get("subtopics"), list):
            value = value["subtopics"]
        else:
            value = [value]

    if not isinstance(value, list):
        return _fallback_subtopics(fallback_query)

    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("title") or "").strip()
        description = str(item.get("description") or "").strip()
        keywords = item.get("keywords") or item.get("queries") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        if not isinstance(keywords, list):
            keywords = []

        clean_keywords = []
        for keyword in keywords:
            keyword = str(keyword).strip()
            if keyword and keyword not in clean_keywords:
                clean_keywords.append(keyword)

        if not name and clean_keywords:
            name = clean_keywords[0]
        if not name:
            continue
        if not clean_keywords:
            clean_keywords = [name]

        normalized.append({
            "name": name[:120],
            "description": description[:500],
            "keywords": clean_keywords[:3],
        })

    if not normalized:
        return _fallback_subtopics(fallback_query)

    return normalized


def _fallback_subtopics(fallback_query: str) -> list[dict[str, Any]]:
    query = fallback_query.strip()
    if not query:
        raise ValueError("Planner output must contain at least one valid subtopic")
    return [{
        "name": "main topic",
        "description": query,
        "keywords": [query],
    }]


def _extract_balanced(text: str, open_char: str, close_char: str) -> str | None:
    start = text.find(open_char)
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        char = text[idx]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return text[start: idx + 1]
    return None
