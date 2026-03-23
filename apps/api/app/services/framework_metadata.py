"""High-precision framework identification metadata (v2026-03-22).

Loaded once at import time. Deterministic scoring runs synchronously before
any LLM fan-out.  All regexes are pre-compiled.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Policy & thresholds
# ---------------------------------------------------------------------------

SPEC_VERSION = "2026-03-22"
CLASSIFIER_MODE = "fail_closed"

@dataclass(frozen=True)
class ConfidenceThresholds:
    high_min: float = 0.82
    medium_min: float = 0.68
    low_min: float = 0.55
    min_gap_over_runner_up_for_high: float = 0.12

CONFIDENCE = ConfidenceThresholds()

CHANNEL_WEIGHTS: dict[str, float] = {
    "title_or_filename_explicit": 0.34,
    "intro_or_preamble_explicit": 0.18,
    "section_heading_match": 0.14,
    "official_control_id_or_code_pattern": 0.18,
    "domain_distribution_match": 0.08,
    "terminology_density_match": 0.08,
}

HIGH_CONFIDENCE_REQUIRES_MIN_CHANNELS = 2
HIGH_CONFIDENCE_MUST_INCLUDE_ONE_OF = frozenset({
    "title_or_filename_explicit",
    "intro_or_preamble_explicit",
    "official_control_id_or_code_pattern",
})

FINAL_FRAMEWORK_KEYS = frozenset({
    "SOC2", "HIPAA", "ISO27001",
    "NIST_CSF_2_0", "NIST_SP_800_53_REV5", "NIST_SP_800_171_REV3",
    "SIG", "CAIQ",
})

FALLBACK_LABELS = frozenset({
    "UNKNOWN", "MULTI_FRAMEWORK",
    "GENERAL_VENDOR_SECURITY_QUESTIONNAIRE",
    "GENERAL_CLOUD_SECURITY_QUESTIONNAIRE",
})

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

ALIAS_MAP: dict[str, str] = {
    "soc ii": "soc 2",
    "soc2": "soc 2",
    "iso/iec27001": "iso/iec 27001",
    "iso27001": "iso/iec 27001",
    "hipaa security rule": "hipaa",
    "nist csf": "nist csf",
    "cybersecurity framework": "nist csf",
    "80053": "800-53",
    "800171": "800-171",
    "caiq lite": "caiq",
    "ccm": "cloud controls matrix",
    "sig lite": "sig",
}

_COLLAPSE_WS = re.compile(r"\s+")
_STRIP_PUNCT = re.compile(r"[^\w\s\-/.]")


def normalize_text(raw: str) -> str:
    """Lowercase, normalize unicode, strip punctuation, collapse whitespace, apply aliases."""
    t = raw.lower()
    t = unicodedata.normalize("NFKC", t)
    t = _STRIP_PUNCT.sub(" ", t)
    t = _COLLAPSE_WS.sub(" ", t).strip()
    for alias, canonical in ALIAS_MAP.items():
        t = t.replace(alias, canonical)
    return t


# ---------------------------------------------------------------------------
# Global negative rules
# ---------------------------------------------------------------------------

GENERIC_SECURITY_TERMS: frozenset[str] = frozenset({
    "access control", "least privilege", "mfa", "logging", "monitoring",
    "encryption", "backup", "incident response", "disaster recovery",
    "vulnerability management", "patching",
})

DIRECT_EVIDENCE_REQUIRED_SPECIALIZED: frozenset[str] = frozenset({
    "container_security", "kubernetes_security", "dlp", "email_security",
    "dns_security", "web_filtering", "casb", "cspm", "cwpp", "sbom",
    "secrets_management", "data_tokenization", "phishing_protection",
    "endpoint_detection_and_response", "secure_email_gateway",
    "network_detection_and_response", "zero_trust_architecture",
    "ai_governance", "model_security", "prompt_injection_protection",
})

# ---------------------------------------------------------------------------
# Framework definitions
# ---------------------------------------------------------------------------

@dataclass
class FrameworkDef:
    key: str
    family: str
    display_label: str
    scope: str
    detect_evidence: bool = True
    detect_questionnaires: bool = True
    final_label_allowed: bool = True
    strong_title_markers: list[str] = field(default_factory=list)
    strong_intro_markers: list[str] = field(default_factory=list)
    structure_markers: list[str] = field(default_factory=list)
    code_patterns: list[re.Pattern[str]] = field(default_factory=list)
    terminology_positive: list[str] = field(default_factory=list)
    terminology_negative: list[str] = field(default_factory=list)
    preferred_subjects: list[str] = field(default_factory=list)
    questionnaires_likely: list[str] = field(default_factory=list)
    hard_disqualifiers: list[str] = field(default_factory=list)
    common_false_positives: list[str] = field(default_factory=list)
    disambiguation_rules: list[str] = field(default_factory=list)
    scoring_boosts: dict[str, float] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def _fw(key: str, family: str, display: str, scope: str, **kw: Any) -> FrameworkDef:
    if "code_patterns" in kw:
        kw["code_patterns"] = _compile_patterns(kw["code_patterns"])
    return FrameworkDef(key=key, family=family, display_label=display, scope=scope, **kw)


FRAMEWORKS: dict[str, FrameworkDef] = {}

# -- SOC 2 --
FRAMEWORKS["SOC2"] = _fw(
    "SOC2", "SOC", "SOC 2",
    "AICPA SOC 2 examinations and related preparedness/reporting content.",
    strong_title_markers=[
        "soc 2", "soc2", "trust services criteria", "tsp section 100",
        "service organization controls", "system and organization controls",
        "type i", "type ii", "type 1", "type 2", "service auditor",
        "independent service auditor", "description criteria", "system description",
    ],
    strong_intro_markers=[
        "relevant to security availability processing integrity confidentiality or privacy",
        "trust services criteria", "service commitments and system requirements",
        "service organization", "subservice organization",
        "complementary user entity controls", "carve-out method", "inclusive method",
        "points of focus",
    ],
    structure_markers=[
        "section i independent service auditor's report", "management's assertion",
        "description of the system", "tests of controls", "results of tests",
        "complementary user entity controls", "complementary subservice organization controls",
        "trust services categories",
    ],
    code_patterns=[
        r"\bcc[1-9](\.[0-9]+)?\b", r"\ba[1-9](\.[0-9]+)?\b",
        r"\bpi[1-9](\.[0-9]+)?\b", r"\bc[1-9](\.[0-9]+)?\b",
        r"\bp[1-9](\.[0-9]+)?\b",
    ],
    terminology_positive=[
        "control environment", "risk assessment", "monitoring activities",
        "logical and physical access controls", "system operations", "change management",
        "risk mitigation", "availability", "processing integrity", "confidentiality",
        "privacy", "service commitments", "system requirements",
    ],
    terminology_negative=[
        "covered entity", "business associate", "ephi", "phi", "isms", "annex a",
        "statement of applicability", "nist csf", "ac-2", "au-6",
        "cloud controls matrix", "shared assessments",
    ],
    preferred_subjects=[
        "governance_risk_compliance", "access_control", "logging_monitoring",
        "vulnerability_management", "incident_response", "change_management",
        "availability_resilience", "business_continuity_disaster_recovery",
        "privacy_data_governance", "confidentiality_data_protection",
        "processing_integrity", "vendor_risk", "workforce_security_training",
        "physical_security",
    ],
    questionnaires_likely=[
        "trust questionnaire", "security questionnaire", "customer security review",
        "due diligence questionnaire", "soc 2 readiness checklist",
        "service organization questionnaire",
    ],
    hard_disqualifiers=[
        "No explicit SOC/SOC2/TSC/service-organization marker anywhere AND no SOC-style control IDs.",
    ],
    common_false_positives=["ISO27001", "NIST_CSF_2_0", "GENERAL_VENDOR_SECURITY_QUESTIONNAIRE"],
    disambiguation_rules=[
        "If ISMS, Annex A, Statement of Applicability, management review, certification, or ISO/IEC 27001 appears, prefer ISO27001.",
        "If PHI/ePHI/covered entity/business associate appears, prefer HIPAA.",
        "If document is explicitly a service auditor report, management assertion, or system description, strongly prefer SOC2.",
        "If content uses CC#, A#, PI#, C#, or P# style control references, boost SOC2 strongly.",
    ],
    scoring_boosts={
        "explicit_soc2_in_title": 0.45,
        "trust_services_phrase": 0.28,
        "soc_report_structure": 0.22,
        "cuec_or_subservice_org": 0.18,
    },
)

# -- HIPAA --
FRAMEWORKS["HIPAA"] = _fw(
    "HIPAA", "HIPAA", "HIPAA",
    "HIPAA privacy, security, breach-notification content, PHI/ePHI handling.",
    strong_title_markers=[
        "hipaa", "hipaa security rule", "hipaa privacy rule",
        "breach notification rule", "protected health information", "phi", "ephi",
        "business associate agreement", "baa", "covered entity", "business associate",
        "ocr", "hitech",
    ],
    strong_intro_markers=[
        "protected health information", "electronic protected health information",
        "covered entities and business associates",
        "administrative physical and technical safeguards", "uses and disclosures",
        "minimum necessary", "notice of privacy practices",
        "breach of unsecured phi", "accounting of disclosures", "designated record set",
    ],
    structure_markers=[
        "administrative safeguards", "physical safeguards", "technical safeguards",
        "privacy rule", "breach notification", "use and disclosure", "patient rights",
        "notice of privacy practices", "business associate agreement",
        "security incident procedures", "contingency plan", "facility access controls",
        "audit controls", "transmission security", "integrity",
        "person or entity authentication",
    ],
    code_patterns=[
        r"\b45\s*cfr\s*164\b", r"\b164\.3\d{2}\b", r"\b164\.4\d{2}\b",
        r"\b160\b", r"\bpart 160\b", r"\bpart 164\b",
    ],
    terminology_positive=[
        "phi", "ephi", "covered entity", "business associate", "minimum necessary",
        "notice of privacy practices", "authorization", "de-identification",
        "accounting of disclosures", "access to records", "amendment requests",
        "breach notification", "risk analysis", "risk management", "sanction policy",
        "workforce security", "information access management",
        "security awareness and training", "contingency plan", "facility access controls",
        "workstation use", "device and media controls", "audit controls", "integrity",
        "transmission security",
    ],
    terminology_negative=[
        "trust services criteria", "service organization", "annex a",
        "statement of applicability", "nist csf", "cloud controls matrix",
        "csp", "saas", "iaas", "shared assessments",
    ],
    preferred_subjects=[
        "privacy_data_governance", "access_control", "identity_authentication",
        "logging_monitoring", "incident_response", "breach_notification",
        "risk_assessment", "business_continuity_disaster_recovery", "backup_restore",
        "workforce_security_training", "physical_security", "vendor_risk",
        "data_retention_disposal", "confidentiality_data_protection",
    ],
    questionnaires_likely=[
        "hipaa security assessment", "healthcare security questionnaire",
        "business associate security questionnaire", "phi handling questionnaire",
        "healthcare privacy assessment",
    ],
    hard_disqualifiers=[
        "Generic healthcare or clinical vocabulary without HIPAA/PHI/ePHI/covered-entity/business-associate markers is not enough.",
    ],
    common_false_positives=["GENERAL_VENDOR_SECURITY_QUESTIONNAIRE", "SOC2", "ISO27001"],
    disambiguation_rules=[
        "Do not map generic RBAC/logging/encryption language to HIPAA unless PHI/ePHI or HIPAA-specific context is explicit.",
        "If healthcare context exists but HIPAA markers are absent, return UNKNOWN or GENERAL_VENDOR_SECURITY_QUESTIONNAIRE.",
        "If the questionnaire asks about patient rights, notices, authorizations, minimum necessary, BAAs, or breach notification, boost HIPAA strongly.",
    ],
    scoring_boosts={
        "explicit_hipaa_in_title": 0.45,
        "phi_or_ephi_markers": 0.32,
        "covered_entity_or_business_associate": 0.24,
        "admin_physical_technical_safeguards_structure": 0.20,
    },
)

# -- ISO 27001 --
FRAMEWORKS["ISO27001"] = _fw(
    "ISO27001", "ISO", "ISO/IEC 27001",
    "ISO/IEC 27001 ISMS requirements and ISO/IEC 27002-style control-oriented content.",
    strong_title_markers=[
        "iso 27001", "iso/iec 27001", "iso 27001:2022", "iso/iec 27001:2022",
        "iso 27002", "iso/iec 27002", "isms", "information security management system",
        "statement of applicability", "soa", "annex a", "internal audit",
        "management review", "surveillance audit", "certification body",
    ],
    strong_intro_markers=[
        "establish implement maintain and continually improve an information security management system",
        "interested parties", "scope of the isms", "information security objectives",
        "risk treatment", "risk acceptance", "documented information",
        "nonconformity and corrective action", "continual improvement", "annex a controls",
    ],
    structure_markers=[
        "context of the organization", "leadership", "planning", "support", "operation",
        "performance evaluation", "improvement", "statement of applicability",
        "control objective", "internal audit", "management review", "corrective action",
        "organizational controls", "people controls", "physical controls",
        "technological controls",
    ],
    code_patterns=[
        r"\ba\.[0-9]+\b", r"\b5\.[0-9]+\b", r"\b6\.[0-9]+\b",
        r"\b7\.[0-9]+\b", r"\b8\.[0-9]+\b",
    ],
    terminology_positive=[
        "isms", "statement of applicability", "applicable controls", "annex a",
        "risk treatment plan", "risk owner", "documented information", "internal audit",
        "management review", "corrective action", "continual improvement",
        "organizational controls", "people controls", "physical controls",
        "technological controls", "certification", "surveillance",
    ],
    terminology_negative=[
        "service organization", "trust services criteria", "covered entity",
        "business associate", "csp", "cloud controls matrix", "shared assessments",
        "csf 2.0", "ac-2", "au-6",
    ],
    preferred_subjects=[
        "governance_risk_compliance", "asset_inventory", "access_control", "cryptography",
        "logging_monitoring", "incident_response", "business_continuity_disaster_recovery",
        "supplier_relationships", "change_management", "secure_sdlc",
        "vulnerability_management", "physical_security", "workforce_security_training",
        "data_classification", "data_retention_disposal",
    ],
    questionnaires_likely=[
        "iso 27001 gap assessment", "isms internal audit questionnaire",
        "annex a control review", "iso certification readiness assessment",
    ],
    hard_disqualifiers=[
        "Generic policy language without ISMS/ISO/Annex A/SoA/internal-audit/management-review/certification signals is not enough.",
    ],
    common_false_positives=["SOC2", "NIST_CSF_2_0", "GENERAL_VENDOR_SECURITY_QUESTIONNAIRE"],
    disambiguation_rules=[
        "If trust services criteria, service organization, management assertion, or type ii report language appears, prefer SOC2.",
        "If CSF functions or NIST control IDs appear, prefer NIST subtype.",
        "If cloud-provider questionnaire structure with CSA/CCM/STAR markers appears, prefer CAIQ.",
    ],
    scoring_boosts={
        "explicit_iso27001_in_title": 0.45,
        "isms_or_statement_of_applicability": 0.30,
        "clauses_4_to_10_structure": 0.18,
        "annex_a_or_27002_control_themes": 0.20,
    },
)

# -- NIST umbrella (not a final label) --
FRAMEWORKS["NIST"] = _fw(
    "NIST", "NIST", "NIST",
    "Umbrella only. Must resolve to a specific NIST subtype or return MULTI_FRAMEWORK/UNKNOWN.",
    final_label_allowed=False,
    children=["NIST_CSF_2_0", "NIST_SP_800_53_REV5", "NIST_SP_800_171_REV3"],
)

# -- NIST CSF 2.0 --
FRAMEWORKS["NIST_CSF_2_0"] = _fw(
    "NIST_CSF_2_0", "NIST", "NIST CSF 2.0",
    "NIST Cybersecurity Framework 2.0 — functions, categories, subcategories, profiles, tiers.",
    strong_title_markers=[
        "nist csf", "nist cybersecurity framework", "cybersecurity framework 2.0",
        "csf 2.0", "nist csf 2.0", "organizational profile", "community profile",
    ],
    strong_intro_markers=[
        "govern identify protect detect respond recover",
        "implementation tiers", "current profile", "target profile",
        "subcategories", "outcomes",
    ],
    structure_markers=[
        "govern", "identify", "protect", "detect", "respond", "recover",
        "profile", "implementation tier",
    ],
    code_patterns=[
        r"\bgv\.[a-z]{2}-\d{2}\b", r"\bid\.[a-z]{2}-\d{2}\b",
        r"\bpr\.[a-z]{2}-\d{2}\b", r"\bde\.[a-z]{2}-\d{2}\b",
        r"\brs\.[a-z]{2}-\d{2}\b", r"\brc\.[a-z]{2}-\d{2}\b",
    ],
    terminology_positive=[
        "govern", "identify", "protect", "detect", "respond", "recover",
        "implementation tiers", "profiles", "cybersecurity outcomes",
        "community profile",
    ],
    terminology_negative=[
        "ac-2", "au-6", "cm-2", "sa-11", "cui", "controlled unclassified information",
        "annex a", "trust services criteria", "shared assessments", "cloud controls matrix",
    ],
    preferred_subjects=[
        "governance_risk_compliance", "asset_inventory", "access_control",
        "logging_monitoring", "vulnerability_management", "incident_response",
        "business_continuity_disaster_recovery", "supplier_relationships",
        "detection_response", "resilience",
    ],
    common_false_positives=["NIST_SP_800_53_REV5", "ISO27001", "SOC2"],
    disambiguation_rules=[
        "If control family IDs like AC-2, AU-6, CM-2, SC-7 are present, prefer NIST_SP_800_53_REV5.",
        "If CUI/nonfederal/800-171 markers appear, prefer NIST_SP_800_171_REV3.",
        "If only functions appear with no control IDs, prefer NIST_CSF_2_0.",
    ],
    scoring_boosts={
        "explicit_csf_in_title": 0.42,
        "six_functions_present": 0.30,
        "profile_or_tier_language": 0.18,
    },
)

# -- NIST SP 800-53 Rev. 5 --
FRAMEWORKS["NIST_SP_800_53_REV5"] = _fw(
    "NIST_SP_800_53_REV5", "NIST", "NIST SP 800-53 Rev. 5",
    "NIST SP 800-53 Rev. 5 catalog-style control references, family IDs, baselines.",
    strong_title_markers=[
        "800-53", "nist sp 800-53", "nist 800-53", "sp 800-53 rev 5", "rev 5",
        "security and privacy controls for information systems and organizations",
        "800-53b", "control baseline",
    ],
    strong_intro_markers=[
        "security and privacy controls", "control baselines",
        "low moderate high baselines", "system and organization controls",
        "risk management framework", "privacy controls",
    ],
    structure_markers=[
        "access control", "awareness and training", "audit and accountability",
        "assessment authorization and monitoring", "configuration management",
        "contingency planning", "identification and authentication",
        "incident response", "maintenance", "media protection",
        "physical and environmental protection", "planning", "program management",
        "personnel security", "pii processing and transparency", "risk assessment",
        "system and services acquisition", "system and communications protection",
        "system and information integrity", "supply chain risk management",
    ],
    code_patterns=[
        r"\bac-\d+\b", r"\bat-\d+\b", r"\bau-\d+\b", r"\bca-\d+\b",
        r"\bcm-\d+\b", r"\bcp-\d+\b", r"\bia-\d+\b", r"\bir-\d+\b",
        r"\bma-\d+\b", r"\bmp-\d+\b", r"\bpe-\d+\b", r"\bpl-\d+\b",
        r"\bpm-\d+\b", r"\bps-\d+\b", r"\bpt-\d+\b", r"\bra-\d+\b",
        r"\bsa-\d+\b", r"\bsc-\d+\b", r"\bsi-\d+\b", r"\bsr-\d+\b",
    ],
    terminology_positive=[
        "control enhancement", "baseline", "fedramp", "authorizing official",
        "security categorization", "privacy risk", "assessment procedures",
    ],
    terminology_negative=[
        "implementation tiers", "current profile", "target profile", "cui",
        "annex a", "trust services criteria", "cloud controls matrix",
        "shared assessments",
    ],
    preferred_subjects=[
        "governance_risk_compliance", "access_control", "identity_authentication",
        "logging_monitoring", "incident_response", "configuration_management",
        "contingency_planning", "risk_assessment", "secure_sdlc",
        "system_communications_protection", "integrity_monitoring",
        "supply_chain_risk", "privacy_data_governance",
    ],
    common_false_positives=["NIST_CSF_2_0", "ISO27001"],
    disambiguation_rules=[
        "If NIST content uses control families and control IDs, prefer 800-53 over CSF.",
        "If content is outcome/profile-based without control IDs, prefer CSF.",
        "If CUI or nonfederal-system language dominates, evaluate 800-171 first.",
    ],
    scoring_boosts={
        "explicit_80053_in_title": 0.45,
        "control_family_ids_present": 0.34,
        "baseline_or_fedramp_language": 0.18,
    },
)

# -- NIST SP 800-171 Rev. 3 --
FRAMEWORKS["NIST_SP_800_171_REV3"] = _fw(
    "NIST_SP_800_171_REV3", "NIST", "NIST SP 800-171 Rev. 3",
    "NIST SP 800-171 Rev. 3 — protecting CUI in nonfederal systems.",
    strong_title_markers=[
        "800-171", "nist sp 800-171", "nist 800-171",
        "protecting controlled unclassified information", "cui",
        "controlled unclassified information", "nonfederal systems",
        "nonfederal organizations",
    ],
    strong_intro_markers=[
        "controlled unclassified information", "nonfederal systems and organizations",
        "federal contract information", "assessment objectives", "security requirements",
    ],
    structure_markers=[
        "access control", "awareness and training", "audit and accountability",
        "configuration management", "identification and authentication",
        "incident response", "maintenance", "media protection", "physical protection",
        "personnel security", "risk assessment", "security assessment",
        "system and communications protection", "system and information integrity",
        "planning", "system and services acquisition", "supply chain risk management",
    ],
    code_patterns=[
        r"\b3\.1\.\d+\b", r"\b3\.2\.\d+\b", r"\b3\.3\.\d+\b", r"\b3\.4\.\d+\b",
        r"\b3\.5\.\d+\b", r"\b3\.6\.\d+\b", r"\b3\.7\.\d+\b", r"\b3\.8\.\d+\b",
        r"\b3\.9\.\d+\b", r"\b3\.10\.\d+\b", r"\b3\.11\.\d+\b", r"\b3\.12\.\d+\b",
        r"\b3\.13\.\d+\b", r"\b3\.14\.\d+\b", r"\b3\.15\.\d+\b", r"\b3\.16\.\d+\b",
        r"\b3\.17\.\d+\b",
    ],
    terminology_positive=[
        "cui", "controlled unclassified information", "nonfederal systems",
        "nonfederal organizations", "security requirements", "assessment objectives",
        "federal contract information", "supplier risk",
    ],
    terminology_negative=[
        "current profile", "target profile", "trust services criteria", "annex a",
        "cloud controls matrix", "shared assessments",
    ],
    preferred_subjects=[
        "access_control", "identity_authentication", "logging_monitoring",
        "incident_response", "risk_assessment", "system_communications_protection",
        "integrity_monitoring", "supply_chain_risk", "configuration_management",
        "media_protection", "personnel_security",
    ],
    common_false_positives=["NIST_SP_800_53_REV5", "NIST_CSF_2_0"],
    disambiguation_rules=[
        "If CUI/nonfederal language is explicit, strongly prefer 800-171.",
        "If AC-2/AU-6 style family IDs dominate instead of 3.x.x control numbering, prefer 800-53.",
    ],
    scoring_boosts={
        "explicit_800171_in_title": 0.45,
        "cui_markers": 0.30,
        "3x_control_numbering": 0.24,
    },
)

# -- SIG --
FRAMEWORKS["SIG"] = _fw(
    "SIG", "SharedAssessments", "Shared Assessments SIG",
    "Shared Assessments SIG vendor-risk questionnaire and close derivatives.",
    detect_evidence=False,
    strong_title_markers=[
        "sig", "standardized information gathering", "shared assessments",
        "sig questionnaire", "shared assessments sig",
        "third party risk questionnaire", "vendor risk questionnaire",
        "vendor due diligence questionnaire",
    ],
    strong_intro_markers=[
        "third-party risk", "third party risk", "vendor assessment",
        "supplier assessment", "outsourcer", "service provider risk",
        "due diligence", "inherent risk", "residual risk", "scoping questionnaire",
    ],
    structure_markers=[
        "company profile", "legal and regulatory", "cybersecurity", "privacy",
        "operational resilience", "business continuity", "incident management",
        "subcontractors", "fourth party", "physical security", "human resources",
        "audit and assurance", "ai governance", "data governance",
    ],
    code_patterns=[r"\bsig\b", r"\bshared assessments\b"],
    terminology_positive=[
        "vendor risk", "third party risk", "due diligence", "outsourcer",
        "vendor questionnaire", "supplier risk", "control validation", "sca",
        "operational resilience", "regulatory compliance", "ai governance",
        "privacy program",
    ],
    terminology_negative=[
        "cloud controls matrix", "caiq", "star registry", "iaas", "paas", "saas",
        "service organization", "trust services criteria", "annex a", "cui",
    ],
    preferred_subjects=[
        "vendor_risk", "governance_risk_compliance", "privacy_data_governance",
        "incident_response", "business_continuity_disaster_recovery",
        "physical_security", "workforce_security_training", "access_control",
        "secure_sdlc", "logging_monitoring", "legal_regulatory", "ai_governance",
        "supply_chain_risk",
    ],
    questionnaires_likely=[
        "vendor due diligence assessment", "third-party risk management questionnaire",
        "supplier security review", "sig lite derivative",
    ],
    hard_disqualifiers=[
        "If cloud-provider self-assessment markers (CSA/CCM/CAIQ/STAR) dominate, prefer CAIQ.",
        "Do not classify company policy documents as SIG.",
    ],
    common_false_positives=["GENERAL_VENDOR_SECURITY_QUESTIONNAIRE", "CAIQ"],
    disambiguation_rules=[
        "If the questionnaire is generic vendor risk and does not explicitly mention Shared Assessments/SIG, prefer GENERAL_VENDOR_SECURITY_QUESTIONNAIRE unless SIG-specific structure is strong.",
        "If cloud shared-responsibility, CSA, CCM, STAR, IaaS/PaaS/SaaS, or yes/no cloud control mapping markers dominate, prefer CAIQ.",
    ],
    scoring_boosts={
        "explicit_sig_or_shared_assessments_in_title": 0.48,
        "third_party_risk_language": 0.24,
        "vendor_due_diligence_structure": 0.16,
    },
)

# -- CAIQ --
FRAMEWORKS["CAIQ"] = _fw(
    "CAIQ", "CSA", "CSA CAIQ",
    "Cloud Security Alliance Consensus Assessments Initiative Questionnaire.",
    detect_evidence=False,
    strong_title_markers=[
        "caiq", "consensus assessments initiative questionnaire", "csa caiq",
        "cloud controls matrix", "ccm", "csa star", "star registry",
        "csp self assessment", "cloud security alliance",
    ],
    strong_intro_markers=[
        "yes no questions", "cloud service provider", "iaas", "paas", "saas",
        "cloud controls matrix", "cloud service customer", "shared responsibility",
        "star level 1",
    ],
    structure_markers=[
        "a&a", "audit & assurance", "ais", "application & interface security",
        "bcr", "business continuity mgmt & op resilience",
        "ccc", "change control & configuration management",
        "cek", "cryptography encryption & key management",
        "dcs", "datacenter security", "dsp", "data security & privacy",
        "grc", "governance risk management & compliance",
        "hrs", "human resources security", "iam", "identity & access management",
        "ipy", "interoperability & portability",
        "ivs", "infrastructure & virtualization security",
        "log", "logging & monitoring",
        "sef", "security incident management e-discovery & cloud forensics",
        "sta", "supply chain management transparency & accountability",
        "tvm", "threat & vulnerability management",
        "uem", "universal endpoint management",
    ],
    code_patterns=[
        r"\ba&a\b", r"\bais\b", r"\bbcr\b", r"\bccc\b", r"\bcek\b",
        r"\bdcs\b", r"\bdsp\b", r"\bgrc\b", r"\bhrs\b", r"\biam\b",
        r"\bipy\b", r"\bivs\b", r"\blog\b", r"\bsef\b", r"\bsta\b",
        r"\btvm\b", r"\buem\b",
    ],
    terminology_positive=[
        "cloud service provider", "cloud service customer", "csp", "csc",
        "shared responsibility", "cloud assurance", "yes no questionnaire",
        "csa star", "ccm mapping", "cloud controls matrix",
        "infrastructure as a service", "platform as a service",
        "software as a service",
    ],
    terminology_negative=[
        "shared assessments", "vendor due diligence", "trust services criteria",
        "annex a", "covered entity", "cui",
    ],
    preferred_subjects=[
        "cloud_security", "access_control", "application_security", "cryptography",
        "data_security_privacy", "governance_risk_compliance", "logging_monitoring",
        "incident_response", "vulnerability_management",
        "interoperability_portability", "virtualization_security",
        "endpoint_security", "supply_chain_risk", "audit_assurance",
    ],
    questionnaires_likely=[
        "cloud provider security questionnaire", "csp self-assessment",
        "star submission questionnaire", "cloud assurance questionnaire",
    ],
    hard_disqualifiers=[
        "If no explicit CSA/CCM/CAIQ/STAR/cloud-provider marker appears, do not classify as CAIQ.",
    ],
    common_false_positives=["SIG", "GENERAL_CLOUD_SECURITY_QUESTIONNAIRE"],
    disambiguation_rules=[
        "CAIQ requires CSA/CCM/CAIQ/STAR or unmistakable cloud-domain structure.",
        "If third-party risk / vendor due diligence language dominates without CSA/CCM markers, prefer SIG or GENERAL_VENDOR_SECURITY_QUESTIONNAIRE.",
    ],
    scoring_boosts={
        "explicit_caiq_or_ccm_or_star_in_title": 0.50,
        "ccm_domain_structure": 0.26,
        "cloud_service_provider_yes_no_language": 0.18,
    },
)

# ---------------------------------------------------------------------------
# Non-framework (fallback) labels
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NonFrameworkLabel:
    key: str
    scope: str
    strong_markers: list[str] = field(default_factory=list)


NON_FRAMEWORK_LABELS: dict[str, NonFrameworkLabel] = {
    "GENERAL_VENDOR_SECURITY_QUESTIONNAIRE": NonFrameworkLabel(
        "GENERAL_VENDOR_SECURITY_QUESTIONNAIRE",
        "Generic vendor/customer security questionnaires not attributable to a specific framework.",
        ["vendor questionnaire", "security questionnaire", "due diligence",
         "trust questionnaire", "customer security review", "supplier questionnaire"],
    ),
    "GENERAL_CLOUD_SECURITY_QUESTIONNAIRE": NonFrameworkLabel(
        "GENERAL_CLOUD_SECURITY_QUESTIONNAIRE",
        "Cloud-focused questionnaires lacking explicit CSA/CAIQ/CCM/STAR markers.",
    ),
    "UNKNOWN": NonFrameworkLabel("UNKNOWN", "Framework cannot be identified safely."),
    "MULTI_FRAMEWORK": NonFrameworkLabel(
        "MULTI_FRAMEWORK",
        "Mixed content with strong evidence for multiple frameworks.",
    ),
}

# ---------------------------------------------------------------------------
# Display label lookup
# ---------------------------------------------------------------------------

NAMING: dict[str, str] = {
    "SOC2": "SOC 2",
    "HIPAA": "HIPAA",
    "ISO27001": "ISO/IEC 27001",
    "NIST_CSF_2_0": "NIST CSF 2.0",
    "NIST_SP_800_53_REV5": "NIST SP 800-53 Rev. 5",
    "NIST_SP_800_171_REV3": "NIST SP 800-171 Rev. 3",
    "SIG": "Shared Assessments SIG",
    "CAIQ": "CSA CAIQ",
    "UNKNOWN": "Unknown",
    "MULTI_FRAMEWORK": "Multi-Framework",
    "GENERAL_VENDOR_SECURITY_QUESTIONNAIRE": "General Vendor Security Questionnaire",
    "GENERAL_CLOUD_SECURITY_QUESTIONNAIRE": "General Cloud Security Questionnaire",
}


def display_label(key: str) -> str:
    return NAMING.get(key, key)


# ---------------------------------------------------------------------------
# Cross-framework disambiguation rules (pairwise)
# ---------------------------------------------------------------------------

CROSS_FRAMEWORK_DISAMBIGUATION: list[dict[str, str]] = [
    {
        "name": "soc2_vs_iso27001",
        "rule": "If content is generic policy/control language, do not choose either. "
                "SOC2 requires service-organization/trust-services/auditor-report markers; "
                "ISO27001 requires ISMS/Annex A/SoA/internal audit/management review/certification markers.",
    },
    {
        "name": "soc2_vs_nist",
        "rule": "SOC2 uses trust-services and service-organization language; "
                "NIST uses function labels, control-family IDs, or publication numbers.",
    },
    {
        "name": "hipaa_vs_generic_healthcare",
        "rule": "Healthcare context alone is not HIPAA. Require PHI/ePHI, covered entity, "
                "business associate, HIPAA rule, BAA, or patient-rights markers.",
    },
    {
        "name": "caiq_vs_sig",
        "rule": "CAIQ is cloud-provider/CSA/CCM/STAR-centric. SIG is vendor-risk/outsourcer/"
                "due-diligence/third-party-risk-centric.",
    },
    {
        "name": "nist_csf_vs_80053",
        "rule": "If functions, profiles, and tiers dominate, prefer CSF 2.0. "
                "If control-family IDs and catalog language dominate, prefer 800-53.",
    },
    {
        "name": "nist_80053_vs_800171",
        "rule": "If CUI/nonfederal systems/3.x.x numbering dominates, prefer 800-171. "
                "If AC-2/AU-6/SC-7 family IDs or federal baseline language dominate, prefer 800-53.",
    },
]

# ---------------------------------------------------------------------------
# Subject definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SubjectDef:
    key: str
    display_label: str
    aliases: tuple[str, ...]
    direct_evidence_required: bool


def _subj(key: str, label: str, aliases: list[str], *, req: bool = False) -> SubjectDef:
    return SubjectDef(key=key, display_label=label, aliases=tuple(aliases), direct_evidence_required=req)


SUBJECTS: dict[str, SubjectDef] = {}

_RAW_SUBJECTS: list[tuple[str, str, list[str], bool]] = [
    ("governance_risk_compliance", "Governance & Risk Compliance",
     ["governance", "grc", "policy governance", "risk management", "compliance management", "internal controls"], False),
    ("asset_inventory", "Asset Inventory",
     ["asset management", "inventory", "cmdb", "inventory of assets", "configuration item inventory"], False),
    ("access_control", "Access Control",
     ["access management", "access restriction", "authorization", "least privilege", "segregation of duties"], False),
    ("identity_authentication", "Identity & Authentication",
     ["iam", "authentication", "mfa", "sso", "federation", "identity proofing", "privileged authentication"], False),
    ("privileged_access", "Privileged Access",
     ["pam", "privileged access management", "admin access", "privileged accounts", "break glass"], True),
    ("cryptography", "Cryptography",
     ["encryption", "key management", "kms", "hsm", "tls", "at rest encryption", "in transit encryption"], False),
    ("data_classification", "Data Classification",
     ["classification", "labeling", "information classification", "data categories"], False),
    ("confidentiality_data_protection", "Confidentiality & Data Protection",
     ["data protection", "confidentiality", "data handling", "sensitive data handling"], False),
    ("privacy_data_governance", "Privacy & Data Governance",
     ["privacy", "consent", "notice", "data subject rights", "data minimization", "retention", "deletion"], False),
    ("data_retention_disposal", "Data Retention & Disposal",
     ["retention", "records retention", "deletion", "destruction", "disposal", "media sanitization"], False),
    ("logging_monitoring", "Logging & Monitoring",
     ["audit logs", "logging", "monitoring", "siem", "alerting", "security events", "observability"], False),
    ("vulnerability_management", "Vulnerability Management",
     ["vuln management", "scanning", "patching", "remediation", "penetration testing"], False),
    ("incident_response", "Incident Response",
     ["incident management", "ir", "security incidents", "forensics", "escalation"], False),
    ("breach_notification", "Breach Notification",
     ["notification", "breach reporting", "regulator notification", "affected individuals"], True),
    ("business_continuity_disaster_recovery", "Business Continuity & Disaster Recovery",
     ["bcp", "dr", "resilience", "recovery", "failover", "rto", "rpo", "continuity"], True),
    ("availability_resilience", "Availability & Resilience",
     ["availability", "uptime", "high availability", "redundancy", "fault tolerance"], True),
    ("backup_restore", "Backup & Restore",
     ["backup", "restore", "restoration", "snapshots", "immutable backup"], False),
    ("change_management", "Change Management",
     ["change control", "release management", "deployment approval", "emergency change"], False),
    ("configuration_management", "Configuration Management",
     ["baseline configuration", "hardening", "configuration control", "drift detection"], False),
    ("secure_sdlc", "Secure SDLC",
     ["sdlc", "secure development", "code review", "threat modeling", "devsecops", "change assurance"], True),
    ("application_security", "Application Security",
     ["appsec", "application security", "secure coding", "dependency scanning", "sast", "dast"], True),
    ("cloud_security", "Cloud Security",
     ["cloud security", "shared responsibility", "cloud provider", "tenancy", "cloud controls"], False),
    ("system_communications_protection", "System & Communications Protection",
     ["network security", "segmentation", "boundary protection", "secure communications"], False),
    ("integrity_monitoring", "Integrity Monitoring",
     ["integrity", "file integrity", "tamper detection", "change detection"], True),
    ("physical_security", "Physical Security",
     ["facility security", "datacenter security", "physical access", "environmental controls"], False),
    ("workforce_security_training", "Workforce Security & Training",
     ["security awareness", "training", "screening", "onboarding", "termination"], False),
    ("vendor_risk", "Vendor Risk",
     ["third party risk", "supplier risk", "vendor management", "due diligence"], False),
    ("supplier_relationships", "Supplier Relationships",
     ["supplier controls", "vendor oversight", "subcontractors", "downstream providers"], False),
    ("supply_chain_risk", "Supply Chain Risk",
     ["supply chain", "software supply chain", "third-party software risk", "provenance"], True),
    ("audit_assurance", "Audit & Assurance",
     ["audit", "assurance", "assessment", "attestation", "evidence review"], False),
    ("interoperability_portability", "Interoperability & Portability",
     ["portability", "interoperability", "exit", "data export", "migration", "lock-in"], True),
    ("endpoint_security", "Endpoint Security",
     ["endpoint protection", "mdm", "uem", "edr", "device posture"], True),
    ("e_discovery_forensics", "E-Discovery & Forensics",
     ["forensics", "legal hold", "e-discovery", "chain of custody"], True),
    ("ai_governance", "AI Governance",
     ["ai governance", "model governance", "ai risk", "ai oversight"], True),
    ("container_security", "Container Security",
     ["containers", "kubernetes", "k8s", "pod security", "image scanning", "runtime policy"], True),
    ("dlp", "Data Loss Prevention",
     ["data loss prevention", "dlp", "exfiltration prevention"], True),
    ("email_security", "Email Security",
     ["email security", "secure email gateway", "anti-phishing", "spam filtering", "dmarc", "dkim", "spf"], True),
    ("dns_security", "DNS Security",
     ["dns security", "dns filtering", "protective dns", "dns sinkhole"], True),
    ("web_filtering", "Web Filtering",
     ["web filtering", "url filtering", "safe browsing", "proxy filtering"], True),
    ("legal_regulatory", "Legal & Regulatory",
     ["legal", "regulatory", "compliance", "contractual"], False),
    ("risk_assessment", "Risk Assessment",
     ["risk assessment", "risk analysis", "threat assessment"], False),
    ("media_protection", "Media Protection",
     ["media protection", "removable media", "media disposal"], True),
    ("personnel_security", "Personnel Security",
     ["personnel security", "background checks", "employee screening"], False),
    ("contingency_planning", "Contingency Planning",
     ["contingency plan", "contingency planning", "emergency planning"], True),
    ("processing_integrity", "Processing Integrity",
     ["processing integrity", "data accuracy", "completeness", "validity"], False),
    ("detection_response", "Detection & Response",
     ["detection", "response", "threat detection", "security response"], False),
    ("resilience", "Resilience",
     ["resilience", "operational resilience", "cyber resilience"], False),
    ("data_security_privacy", "Data Security & Privacy",
     ["data security", "data privacy", "information security"], False),
    ("virtualization_security", "Virtualization Security",
     ["virtualization", "hypervisor", "virtual machine security"], True),
]

for _k, _lbl, _al, _req in _RAW_SUBJECTS:
    SUBJECTS[_k] = _subj(_k, _lbl, _al, req=_req)

# Reverse lookup: alias -> subject key
SUBJECT_ALIAS_INDEX: dict[str, str] = {}
for _s in SUBJECTS.values():
    SUBJECT_ALIAS_INDEX[_s.key] = _s.key
    for _a in _s.aliases:
        SUBJECT_ALIAS_INDEX[_a.lower()] = _s.key
