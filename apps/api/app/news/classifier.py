"""News headline and summary event category classification for V6.

Supported categories:
- OIL_SUPPLY
- TRADE_RESTRICTION
- SANCTION
- CONFLICT
- CENTRAL_BANK
- DIPLOMACY

Requirements:
- Persist classification and provenance.
- Distinguish model/rule-inferred categories from source-provided categories.
- Preserve original headline, source, and publication timestamp.
- Handle uncertain classifications without forcing a category.
"""

from __future__ import annotations

import re
from typing import Any

# Supported geopolitical and trade policy categories
SUPPORTED_EVENT_CATEGORIES: set[str] = {
    "OIL_SUPPLY",
    "TRADE_RESTRICTION",
    "SANCTION",
    "CONFLICT",
    "CENTRAL_BANK",
    "DIPLOMACY",
}

# Compiled keyword and phrase regexes
_PATTERNS: dict[str, list[re.Pattern]] = {
    "OIL_SUPPLY": [
        re.compile(r"\b(crude\s+oil|brent\s+crude|wti\s+crude)\b", re.IGNORECASE),
        re.compile(r"\b(opec(?:\+)?|oil\s+output|oil\s+production|petroleum\s+output)\b", re.IGNORECASE),
        re.compile(r"\b(oil\s+suppl(?:y|ies)|fuel\s+suppl(?:y|ies)|crude\s+inventor(?:y|ies))\b", re.IGNORECASE),
        re.compile(r"\b(oil\s+reserves|strategic\s+petroleum\s+reserve|spr\s+release)\b", re.IGNORECASE),
        re.compile(r"\b(oil\s+tanker|refinery\s+capacity|refinery\s+shutdown|oil\s+glut|oil\s+embargo)\b", re.IGNORECASE),
    ],
    "TRADE_RESTRICTION": [
        re.compile(r"\b(tariff|tariffs|trade\s+dut(?:y|ies)|customs\s+dut(?:y|ies))\b", re.IGNORECASE),
        re.compile(r"\b(import\s+curb|import\s+ban|export\s+ban|export\s+curb|export\s+curbs)\b", re.IGNORECASE),
        re.compile(r"\b(anti[\s-]?dumping\s+dut(?:y|ies)|trade\s+barrier|trade\s+restrictions?)\b", re.IGNORECASE),
        re.compile(r"\b(quota\s+restriction|protectionism|trade\s+dispute|trade\s+penalty)\b", re.IGNORECASE),
    ],
    "SANCTION": [
        re.compile(r"\b(sanctions?|sanctioning|sanctioned)\b", re.IGNORECASE),
        re.compile(r"\b(trade\s+embargo|economic\s+embargo|blacklisted\s+entit(?:y|ies))\b", re.IGNORECASE),
        re.compile(r"\b(asset\s+freeze|financial\s+sanctions?|secondary\s+sanctions?)\b", re.IGNORECASE),
    ],
    "CONFLICT": [
        re.compile(r"\b(air\s?strike|military\s+strike|missile\s+attack|naval\s+blockade)\b", re.IGNORECASE),
        re.compile(r"\b(red\s+sea\s+attacks?|drone\s+strike|hostilities|ceasefire|invasion)\b", re.IGNORECASE),
        re.compile(r"\b(armed\s+conflict|military\s+escalation|war\s+zone|geopolitical\s+conflict)\b", re.IGNORECASE),
    ],
    "CENTRAL_BANK": [
        re.compile(r"\b(reserve\s+bank\s+of\s+india|federal\s+reserve|the\s+fed|european\s+central\s+bank|bank\s+of\s+england)\b", re.IGNORECASE),
        re.compile(r"\b(monetary\s+policy\s+committee|rbi\s+mpc|fomc|repo\s+rate|reverse\s+repo)\b", re.IGNORECASE),
        re.compile(r"\b(rate\s+hike|rate\s+cut|basis\s+points\s+hike|basis\s+points\s+cut|policy\s+rate)\b", re.IGNORECASE),
        re.compile(r"\b(central\s+bank\s+(?:rate|policy|governor|meeting|decision))\b", re.IGNORECASE),
    ],
    "DIPLOMACY": [
        re.compile(r"\b(free\s+trade\s+agreement|bilateral\s+trade\s+talks?|trade\s+pact|trade\s+treaty)\b", re.IGNORECASE),
        re.compile(r"\b(diplomatic\s+summit|diplomatic\s+treaty|peace\s+accord|peace\s+talks?)\b", re.IGNORECASE),
        re.compile(r"\b(ministerial\s+delegation|g20\s+summit|brics\s+summit|bilateral\s+pact)\b", re.IGNORECASE),
    ],
}

# Negative lookahead exclusions to prevent false positives
# e.g., 'Central Bank of India' is a commercial retail bank, not monetary policy
_EXCLUSIONS: list[re.Pattern] = [
    re.compile(r"\bCentral\s+Bank\s+of\s+India\b", re.IGNORECASE),
    re.compile(r"\bFederal\s+Bank\b", re.IGNORECASE),
]


def classify_text(text: str) -> tuple[str | None, float]:
    """Classify a headline or summary into a supported event category.

    Returns:
        (category, confidence): category is one of SUPPORTED_EVENT_CATEGORIES or None.
        Confidence is 0.0 to 1.0.
    """
    if not text or not isinstance(text, str):
        return None, 0.0

    clean = " ".join(text.split())
    if not clean:
        return None, 0.0

    # Check for commercial bank name exclusions before checking central bank
    is_commercial_bank_named = any(exc.search(clean) for exc in _EXCLUSIONS)

    matched_categories: list[tuple[str, int]] = []
    for category, patterns in _PATTERNS.items():
        if category == "CENTRAL_BANK" and is_commercial_bank_named:
            # Only trigger CENTRAL_BANK if explicit policy keywords appear outside the commercial name
            has_explicit_policy = any(
                p.search(clean) for p in _PATTERNS["CENTRAL_BANK"]
                if "central bank" not in p.pattern and "federal" not in p.pattern
            )
            if not has_explicit_policy:
                continue

        hits = sum(1 for p in patterns if p.search(clean))
        if hits > 0:
            matched_categories.append((category, hits))

    if not matched_categories:
        return None, 0.0

    # Pick category with most pattern matches
    matched_categories.sort(key=lambda x: x[1], reverse=True)
    best_cat, best_hits = matched_categories[0]

    # Calculate confidence based on hits
    confidence = min(0.95, 0.70 + (best_hits * 0.10))
    return best_cat, confidence


def classify_news_item(item: dict[str, Any]) -> dict[str, Any]:
    """Classify a single news item, preserving provenance and existing fields.

    Never overwrites an existing SOURCE_PROVIDED event_category.
    """
    if not isinstance(item, dict):
        return item

    updated = dict(item)

    # 1. Preserve source-provided category if already valid
    source_cat = updated.get("event_category")
    if source_cat and source_cat in SUPPORTED_EVENT_CATEGORIES and updated.get("classification_provenance") == "SOURCE_PROVIDED":
        updated["classification_confidence"] = updated.get("classification_confidence", 1.0)
        return updated

    # 2. Extract text from claim and summary
    claim = str(updated.get("claim") or "")
    summary = str(updated.get("summary") or "")
    combined = f"{claim} {summary}".strip()

    category, conf = classify_text(combined)

    if category is not None:
        updated["event_category"] = category
        updated["classification_provenance"] = "RULE_INFERRED"
        updated["classification_confidence"] = conf
    else:
        # Uncertain / ambiguous: do not force a category
        updated["event_category"] = None
        updated["classification_provenance"] = "UNCLASSIFIED"
        updated["classification_confidence"] = 0.0

    return updated


def classify_all_news_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classify a list of news items immutably."""
    return [classify_news_item(item) for item in items]
