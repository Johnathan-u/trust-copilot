"""Deterministic multi-channel framework classifier (v2026-03-22).

Runs entirely in-process with no LLM calls.  Produces a ``ClassificationResult``
that downstream callers can use directly (HIGH confidence) or feed into a
targeted LLM tiebreak (MEDIUM / LOW).

Algorithm follows ``recommended_classifier_algorithm`` from the spec:
  1. Normalize title, filename, headings, preamble, body
  2. Score explicit framework markers by channel
  3. Score structure markers and control-ID patterns
  4. Score subject distribution independently
  5. Apply cross-framework disambiguation rules
  6. If nothing crosses threshold, emit fallback
  7. Only then (caller responsibility) call LLM with top-2 candidates
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from app.services.framework_metadata import (
    CHANNEL_WEIGHTS,
    CONFIDENCE,
    CROSS_FRAMEWORK_DISAMBIGUATION,
    DIRECT_EVIDENCE_REQUIRED_SPECIALIZED,
    FALLBACK_LABELS,
    FINAL_FRAMEWORK_KEYS,
    FRAMEWORKS,
    GENERIC_SECURITY_TERMS,
    HIGH_CONFIDENCE_MUST_INCLUDE_ONE_OF,
    HIGH_CONFIDENCE_REQUIRES_MIN_CHANNELS,
    NON_FRAMEWORK_LABELS,
    SUBJECTS,
    SUBJECT_ALIAS_INDEX,
    FrameworkDef,
    display_label,
    normalize_text,
)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ClassificationResult:
    framework: str
    display_label: str
    confidence: float
    confidence_level: str  # "high" | "medium" | "low" | "none"
    subjects: list[str] = field(default_factory=list)
    runner_up: str | None = None
    runner_up_score: float = 0.0
    channels_matched: list[str] = field(default_factory=list)
    needs_llm_tiebreak: bool = False


# ---------------------------------------------------------------------------
# Text region extraction
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(
    r"^(?:#{1,4}\s+|[A-Z][A-Z0-9 /&]{3,60}$|Section\s+\d|Chapter\s+\d)",
    re.MULTILINE,
)


@dataclass
class _TextRegions:
    title: str
    intro: str
    headings: str
    body: str


def _extract_regions(text: str, filename: str) -> _TextRegions:
    norm = normalize_text(text)
    fn = normalize_text(filename)

    lines = norm.split("\n")
    title_part = fn
    if lines:
        title_part = f"{fn} {lines[0]}"

    intro_cutoff = max(1, len(norm) * 15 // 100)
    intro = norm[:intro_cutoff]

    heading_lines: list[str] = []
    for line in lines:
        if _HEADING_RE.match(line.strip()):
            heading_lines.append(line.strip())
    headings = " ".join(heading_lines)

    return _TextRegions(title=title_part, intro=intro, headings=headings, body=norm)


# ---------------------------------------------------------------------------
# Per-channel scoring
# ---------------------------------------------------------------------------

def _marker_hits(text: str, markers: Sequence[str]) -> int:
    count = 0
    for m in markers:
        if m in text:
            count += 1
    return count


def _pattern_hits(text: str, patterns: Sequence[re.Pattern[str]]) -> int:
    count = 0
    for p in patterns:
        if p.search(text):
            count += 1
    return count


def _channel_score_title(fw: FrameworkDef, regions: _TextRegions) -> float:
    hits = _marker_hits(regions.title, fw.strong_title_markers)
    if not hits:
        return 0.0
    return min(1.0, hits * 0.5)


def _channel_score_intro(fw: FrameworkDef, regions: _TextRegions) -> float:
    hits = _marker_hits(regions.intro, fw.strong_intro_markers)
    if not hits:
        return 0.0
    return min(1.0, hits * 0.35)


def _channel_score_headings(fw: FrameworkDef, regions: _TextRegions) -> float:
    hits = _marker_hits(regions.headings, fw.structure_markers)
    total = len(fw.structure_markers) or 1
    return min(1.0, hits / max(total * 0.3, 1))


def _channel_score_control_ids(fw: FrameworkDef, regions: _TextRegions) -> float:
    if not fw.code_patterns:
        return 0.0
    hits = _pattern_hits(regions.body, fw.code_patterns)
    if not hits:
        return 0.0
    return min(1.0, hits * 0.15)


def _channel_score_domain(fw: FrameworkDef, regions: _TextRegions) -> float:
    if not fw.preferred_subjects:
        return 0.0
    hit = 0
    for subj_key in fw.preferred_subjects:
        subj = SUBJECTS.get(subj_key)
        if not subj:
            continue
        for alias in subj.aliases:
            if alias in regions.body:
                hit += 1
                break
    return min(1.0, hit / max(len(fw.preferred_subjects) * 0.4, 1))


def _channel_score_terminology(fw: FrameworkDef, regions: _TextRegions) -> float:
    if not fw.terminology_positive:
        return 0.0
    pos = _marker_hits(regions.body, fw.terminology_positive)
    neg = _marker_hits(regions.body, fw.terminology_negative)
    raw = (pos - neg * 0.5) / max(len(fw.terminology_positive) * 0.4, 1)
    return max(0.0, min(1.0, raw))


_CHANNEL_SCORERS = {
    "title_or_filename_explicit": _channel_score_title,
    "intro_or_preamble_explicit": _channel_score_intro,
    "section_heading_match": _channel_score_headings,
    "official_control_id_or_code_pattern": _channel_score_control_ids,
    "domain_distribution_match": _channel_score_domain,
    "terminology_density_match": _channel_score_terminology,
}


def _score_framework(fw: FrameworkDef, regions: _TextRegions) -> tuple[float, list[str]]:
    """Return (weighted_score, list_of_active_channels)."""
    total = 0.0
    active: list[str] = []
    for channel_name, scorer in _CHANNEL_SCORERS.items():
        ch_score = scorer(fw, regions)
        weight = CHANNEL_WEIGHTS[channel_name]
        total += ch_score * weight
        if ch_score > 0.15:
            active.append(channel_name)
    return total, active


# ---------------------------------------------------------------------------
# Negative-rule penalty
# ---------------------------------------------------------------------------

def _generic_term_penalty(regions: _TextRegions) -> float:
    """How many generic security terms appear — used to penalize frameworks
    that would be assigned solely from this vocabulary."""
    hits = sum(1 for t in GENERIC_SECURITY_TERMS if t in regions.body)
    return hits / max(len(GENERIC_SECURITY_TERMS), 1)


# ---------------------------------------------------------------------------
# Disambiguation (pairwise)
# ---------------------------------------------------------------------------

_ISO_MARKERS = frozenset({"isms", "annex a", "statement of applicability",
                           "management review", "certification", "iso/iec 27001"})
_SOC_MARKERS = frozenset({"trust services criteria", "service organization",
                           "management assertion", "type ii", "type 2",
                           "service auditor"})
_HIPAA_MARKERS = frozenset({"phi", "ephi", "covered entity", "business associate",
                             "hipaa"})
_CSF_MARKERS = frozenset({"govern", "identify", "protect", "detect", "respond",
                           "recover", "implementation tiers", "current profile",
                           "target profile"})
_80053_ID_RE = re.compile(r"\b(ac|at|au|ca|cm|cp|ia|ir|ma|mp|pe|pl|pm|ps|pt|ra|sa|sc|si|sr)-\d+\b", re.I)
_800171_ID_RE = re.compile(r"\b3\.\d{1,2}\.\d+\b")
_CUI_MARKERS = frozenset({"cui", "controlled unclassified information",
                           "nonfederal systems", "nonfederal organizations"})
_CSA_MARKERS = frozenset({"csa", "caiq", "ccm", "star registry",
                           "cloud controls matrix", "cloud security alliance"})
_SIG_MARKERS = frozenset({"shared assessments", "sig", "standardized information gathering"})
_VENDOR_MARKERS = frozenset({"vendor questionnaire", "security questionnaire",
                              "due diligence", "supplier questionnaire",
                              "customer security review"})
_CLOUD_MARKERS = frozenset({"cloud service provider", "iaas", "paas", "saas",
                             "shared responsibility"})


def _disambiguate(scores: dict[str, float], regions: _TextRegions) -> dict[str, float]:
    """Apply pairwise disambiguation, suppressing weaker candidates."""
    body = regions.body
    out = dict(scores)

    iso_signal = sum(1 for m in _ISO_MARKERS if m in body)
    soc_signal = sum(1 for m in _SOC_MARKERS if m in body)
    hipaa_signal = sum(1 for m in _HIPAA_MARKERS if m in body)
    csf_signal = sum(1 for m in _CSF_MARKERS if m in body)
    id_80053 = len(_80053_ID_RE.findall(body))
    id_800171 = len(_800171_ID_RE.findall(body))
    cui_signal = sum(1 for m in _CUI_MARKERS if m in body)
    csa_signal = sum(1 for m in _CSA_MARKERS if m in body)
    sig_signal = sum(1 for m in _SIG_MARKERS if m in body)

    # SOC2 vs ISO27001
    if iso_signal >= 2 and soc_signal < 2:
        out["SOC2"] = out.get("SOC2", 0) * 0.5
    if soc_signal >= 2 and iso_signal < 2:
        out["ISO27001"] = out.get("ISO27001", 0) * 0.5

    # SOC2/ISO vs HIPAA
    if hipaa_signal >= 2:
        out["SOC2"] = out.get("SOC2", 0) * 0.6
        out["ISO27001"] = out.get("ISO27001", 0) * 0.6

    # NIST CSF vs 800-53
    if id_80053 >= 3 and csf_signal < 3:
        out["NIST_CSF_2_0"] = out.get("NIST_CSF_2_0", 0) * 0.4
    if csf_signal >= 4 and id_80053 < 2:
        out["NIST_SP_800_53_REV5"] = out.get("NIST_SP_800_53_REV5", 0) * 0.4

    # 800-53 vs 800-171
    if cui_signal >= 2 and id_800171 >= 2:
        out["NIST_SP_800_53_REV5"] = out.get("NIST_SP_800_53_REV5", 0) * 0.5
    if id_80053 >= 3 and cui_signal < 1:
        out["NIST_SP_800_171_REV3"] = out.get("NIST_SP_800_171_REV3", 0) * 0.4

    # CAIQ vs SIG
    if csa_signal >= 2 and sig_signal < 2:
        out["SIG"] = out.get("SIG", 0) * 0.4
    if sig_signal >= 2 and csa_signal < 2:
        out["CAIQ"] = out.get("CAIQ", 0) * 0.4

    return out


# ---------------------------------------------------------------------------
# Subject scoring (independent track)
# ---------------------------------------------------------------------------

def _score_subjects(regions: _TextRegions) -> list[str]:
    """Return subject keys sorted by match strength."""
    scores: list[tuple[str, int]] = []
    for key, subj in SUBJECTS.items():
        hits = 0
        all_terms = [key.replace("_", " ")] + list(subj.aliases)
        for term in all_terms:
            if term in regions.body:
                hits += 1
        if hits > 0:
            scores.append((key, hits))
    scores.sort(key=lambda x: -x[1])
    return [k for k, _ in scores[:10]]


# ---------------------------------------------------------------------------
# Fallback resolution
# ---------------------------------------------------------------------------

def _resolve_fallback(regions: _TextRegions) -> str:
    vendor_hits = sum(1 for m in _VENDOR_MARKERS if m in regions.body)
    cloud_hits = sum(1 for m in _CLOUD_MARKERS if m in regions.body)
    if cloud_hits >= 2 and vendor_hits < 2:
        return "GENERAL_CLOUD_SECURITY_QUESTIONNAIRE"
    if vendor_hits >= 2:
        return "GENERAL_VENDOR_SECURITY_QUESTIONNAIRE"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_document(text: str, filename: str) -> ClassificationResult:
    """Classify an evidence document or questionnaire by framework + subjects."""
    regions = _extract_regions(text, filename)
    return _classify(regions, is_questionnaire=False)


def classify_question(
    text: str,
    questionnaire_framework: str | None = None,
) -> ClassificationResult:
    """Classify a single questionnaire question."""
    regions = _extract_regions(text, "")
    result = _classify(regions, is_questionnaire=True)
    # Questionnaire-level framework provides a prior
    if questionnaire_framework and questionnaire_framework in FINAL_FRAMEWORK_KEYS:
        if result.confidence < CONFIDENCE.medium_min:
            result.framework = questionnaire_framework
            result.display_label = display_label(questionnaire_framework)
            result.confidence = max(result.confidence, CONFIDENCE.low_min)
            result.confidence_level = "low"
    return result


def _classify(regions: _TextRegions, *, is_questionnaire: bool) -> ClassificationResult:
    generic_ratio = _generic_term_penalty(regions)

    raw_scores: dict[str, float] = {}
    channels_by_fw: dict[str, list[str]] = {}

    for key, fw in FRAMEWORKS.items():
        if not fw.final_label_allowed:
            continue
        if is_questionnaire and not fw.detect_questionnaires:
            continue
        if not is_questionnaire and not fw.detect_evidence:
            continue
        score, active = _score_framework(fw, regions)
        # Penalize if score is driven mostly by generic security vocabulary
        if generic_ratio > 0.5 and len(active) <= 1:
            score *= 0.5
        raw_scores[key] = score
        channels_by_fw[key] = active

    if not raw_scores:
        fb = _resolve_fallback(regions)
        return ClassificationResult(
            framework=fb,
            display_label=display_label(fb),
            confidence=0.0,
            confidence_level="none",
            subjects=_score_subjects(regions),
        )

    # Disambiguation pass
    scores = _disambiguate(raw_scores, regions)

    # Rank
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    top_key, top_score = ranked[0]
    runner_key = ranked[1][0] if len(ranked) > 1 else None
    runner_score = ranked[1][1] if len(ranked) > 1 else 0.0
    gap = top_score - runner_score

    channels = channels_by_fw.get(top_key, [])
    subjects = _score_subjects(regions)

    # Confidence level
    has_strong_channel = bool(set(channels) & HIGH_CONFIDENCE_MUST_INCLUDE_ONE_OF)
    enough_channels = len(channels) >= HIGH_CONFIDENCE_REQUIRES_MIN_CHANNELS

    if (top_score >= CONFIDENCE.high_min
            and gap >= CONFIDENCE.min_gap_over_runner_up_for_high
            and has_strong_channel
            and enough_channels):
        conf_level = "high"
    elif top_score >= CONFIDENCE.medium_min:
        conf_level = "medium"
    elif top_score >= CONFIDENCE.low_min:
        conf_level = "low"
    else:
        conf_level = "none"

    # Multi-framework check: top two within 0.12 and no strong distinguishing marker
    if runner_key and gap < CONFIDENCE.min_gap_over_runner_up_for_high and top_score >= CONFIDENCE.low_min:
        if not has_strong_channel:
            return ClassificationResult(
                framework="MULTI_FRAMEWORK",
                display_label=display_label("MULTI_FRAMEWORK"),
                confidence=top_score,
                confidence_level="low",
                subjects=subjects,
                runner_up=runner_key,
                runner_up_score=runner_score,
                channels_matched=channels,
                needs_llm_tiebreak=True,
            )

    # Below threshold -> fallback
    if conf_level == "none":
        fb = _resolve_fallback(regions)
        return ClassificationResult(
            framework=fb,
            display_label=display_label(fb),
            confidence=top_score,
            confidence_level="none",
            subjects=subjects,
            runner_up=runner_key,
            runner_up_score=runner_score,
            channels_matched=channels,
            needs_llm_tiebreak=top_score >= CONFIDENCE.low_min * 0.7,
        )

    needs_tiebreak = conf_level in ("medium", "low")

    return ClassificationResult(
        framework=top_key,
        display_label=display_label(top_key),
        confidence=top_score,
        confidence_level=conf_level,
        subjects=subjects,
        runner_up=runner_key,
        runner_up_score=runner_score,
        channels_matched=channels,
        needs_llm_tiebreak=needs_tiebreak,
    )
