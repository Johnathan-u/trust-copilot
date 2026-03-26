"""Trust verification scoring engine.

Scores an individual claim against a list of evidence items on a 0-100 scale.

Factors evaluated:
  1. Source authority   (primary > official > independent > public > self-reported)
  2. Recency            (recent evidence is weighted higher)
  3. Relevance          (direct > supporting > tangential)
  4. Corroboration      (multiple independent sources boost confidence)
  5. Consistency        (contradictions and inconsistencies lower confidence)
  6. Integrity          (tampering indicators cause severe penalties)
  7. Completeness       (missing critical evidence reduces the score)

Each evidence item is a dict with keys:
  description   : str   -- human-readable label
  source_type   : str   -- "primary" | "official" | "independent" | "public" | "self_reported"
  recency_days  : int   -- days between evidence date and submission date (0 = same day, -1 = unknown)
  relevance     : str   -- "direct" | "supporting" | "tangential"
  is_duplicate  : bool  -- True if this duplicates another item (default False)
  contradicts   : bool  -- True if this evidence contradicts the claim (default False)
  negative_signal: bool -- True if this is a negative operational signal (default False)
  tampering     : bool  -- True if document tampering is suspected (default False)
  inconsistency : bool  -- True if there's a minor mismatch (e.g. transliteration) (default False)
"""

from __future__ import annotations

_SCALE = 92

_SOURCE_WEIGHT: dict[str, float] = {
    "primary": 1.0,
    "official": 0.9,
    "independent": 0.8,
    "public": 0.5,
    "self_reported": 0.45,
}

_RELEVANCE_WEIGHT: dict[str, float] = {
    "direct": 1.0,
    "supporting": 0.6,
    "tangential": 0.2,
}

_GRADE_THRESHOLDS: list[tuple[int, str]] = [
    (85, "high"),
    (65, "moderate"),
    (40, "low"),
    (20, "insufficient"),
    (0, "fail"),
]


def _recency_weight(days: int) -> float:
    """Map evidence age in days to a 0-1 recency factor."""
    if days < 0:
        return 0.5
    if days <= 30:
        return 1.0
    if days <= 90:
        return 0.95
    if days <= 180:
        return 0.85
    if days <= 365:
        return 0.65
    if days <= 730:
        return 0.50
    return 0.40


def _item_quality(item: dict) -> float:
    """Score a single evidence item on a 0-1 scale."""
    if item.get("is_duplicate") or item.get("negative_signal"):
        return 0.0
    sw = _SOURCE_WEIGHT.get(item.get("source_type", ""), 0.3)
    rw = _RELEVANCE_WEIGHT.get(item.get("relevance", ""), 0.2)
    rec = _recency_weight(item.get("recency_days", -1))
    q = sw * rw * rec
    if item.get("inconsistency"):
        q *= 0.50
    return q


def _grade(score: int) -> str:
    for threshold, label in _GRADE_THRESHOLDS:
        if score >= threshold:
            return label
    return "fail"


def compute_trust_score(
    evidence: list[dict],
    missing_critical: list[str] | None = None,
) -> dict:
    """Compute a trust score (0-100) for a claim given its evidence.

    Returns::

        {
            "score": int,
            "grade": str,         # high / moderate / low / insufficient / fail
            "breakdown": { ... }, # per-factor contribution for transparency
        }
    """
    missing_critical = missing_critical or []

    positive = [
        e for e in evidence
        if not e.get("is_duplicate")
        and not e.get("negative_signal")
        and not e.get("contradicts")
    ]

    if not positive:
        neg_count = sum(1 for e in evidence if e.get("negative_signal"))
        raw = max(0, 10 - neg_count * 4)
        return {
            "score": raw,
            "grade": _grade(raw),
            "breakdown": {
                "base": 0,
                "corroboration": 0,
                "contradiction_penalty": 0,
                "tampering_penalty": 0,
                "negative_signal_penalty": neg_count * 4,
                "missing_penalty": 0,
                "duplicate_penalty": 0,
            },
        }

    quals = sorted([_item_quality(e) for e in positive], reverse=True)
    best = quals[0]
    top3 = quals[: min(3, len(quals))]
    top3_avg = sum(top3) / len(top3)

    base = (best * 0.5 + top3_avg * 0.5) * _SCALE

    # --- corroboration (independent source count) ---
    ind_count = sum(
        1 for e in positive if e.get("source_type") != "self_reported"
    )
    has_tampering = any(e.get("tampering") for e in evidence)

    corr_adj = 0.0
    if has_tampering:
        corr_adj = 0  # tampering penalty is sufficient; don't stack
    elif ind_count >= 5:
        corr_adj = 5
    elif ind_count >= 4:
        corr_adj = 3
    elif ind_count >= 3:
        corr_adj = 1
    elif ind_count >= 2:
        corr_adj = 0
    elif ind_count == 1:
        corr_adj = -(base * 0.50)
    else:
        corr_adj = -(base * 0.20)
    base += corr_adj

    # --- contradiction penalty ---
    contradict_penalty = 0.0
    contradict_items = [e for e in evidence if e.get("contradicts")]
    for ci in contradict_items:
        sw = _SOURCE_WEIGHT.get(ci.get("source_type", ""), 0.5)
        rec = _recency_weight(ci.get("recency_days", -1))
        contradict_penalty += (sw ** 2) * rec * 20

    if contradict_items and positive:
        support_days = [
            e.get("recency_days", 999)
            for e in positive
            if e.get("recency_days", -1) >= 0
        ]
        best_support_recency = min(support_days) if support_days else 999
        for ci in contradict_items:
            ci_days = ci.get("recency_days", 999)
            if 0 <= ci_days < best_support_recency:
                contradict_penalty += 20

    base -= contradict_penalty

    # --- tampering penalty ---
    tamper_penalty = 0.0
    tampered = [e for e in evidence if e.get("tampering")]
    if tampered:
        ratio = len(tampered) / max(len(positive), 1)
        tamper_penalty = 28 + 32 * ratio
    base -= tamper_penalty

    # --- negative signal penalty ---
    neg_count = sum(1 for e in evidence if e.get("negative_signal"))
    neg_penalty = neg_count * 4
    base -= neg_penalty

    # --- missing critical evidence penalty ---
    miss_penalty = len(missing_critical) * 2
    base -= miss_penalty

    # --- duplicate inflation penalty ---
    dup_penalty = 0.0
    if ind_count > 1:
        dup_count = sum(1 for e in evidence if e.get("is_duplicate"))
        total = len(evidence)
        if total > 1 and dup_count / total > 0.5:
            dup_penalty = 5
    base -= dup_penalty

    score = max(0, min(100, round(base)))
    return {
        "score": score,
        "grade": _grade(score),
        "breakdown": {
            "base": round((best * 0.5 + top3_avg * 0.5) * _SCALE, 1),
            "corroboration": round(corr_adj, 1),
            "contradiction_penalty": round(contradict_penalty, 1),
            "tampering_penalty": round(tamper_penalty, 1),
            "negative_signal_penalty": neg_penalty,
            "missing_penalty": miss_penalty,
            "duplicate_penalty": dup_penalty,
        },
    }
