"""Synthetic text-PDF locator corpus (TC-01-003a / TC-01-003-AC2).

No locator corpus exists in the package or repo at baseline, so this one is
built deterministically from ``app.services.synthetic_pdf``. All content is
synthetic. Each case records what a correct PDF text locator must report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.services.synthetic_pdf import Page, TextItem, build_pdf, text_block

FIXTURE_PDF = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "security_policy.pdf"


@dataclass
class Case:
    name: str
    pdf: bytes | None = None
    path: Path | None = None
    # page number (1-based) -> marker strings that must appear on that page only
    page_markers: dict[int, list[str]] = field(default_factory=dict)
    # pages that must be reported as having no text
    empty_pages: list[int] = field(default_factory=list)
    # sequences of markers that must appear in this relative order within their page
    ordered: list[list[str]] = field(default_factory=list)
    # each inner list must appear on one line, in order (table rows)
    same_line: list[list[str]] = field(default_factory=list)
    # each marker must be on its own line, unmerged with other markers
    own_line: list[str] = field(default_factory=list)
    # expected outcome: "text", "no_text", "unreadable", "encrypted"
    outcome: str = "text"
    # questionnaire expectations: (question substring, page, section)
    questions: list[tuple[str, int, str | None]] = field(default_factory=list)


def _multipage_blank() -> Case:
    pages = [
        Page(
            texts=text_block(
                72, 90, ["MARK-P1-ALPHA Access control policy.", "MARK-P1-BETA Reviewed yearly."]
            )
        ),
        Page(),  # blank page: page numbering must not shift
        Page(texts=text_block(72, 90, ["MARK-P3-GAMMA Encryption at rest uses AES-256."])),
        Page(texts=text_block(72, 700, ["MARK-P4-DELTA Footer-positioned text."])),
    ]
    return Case(
        "multipage_blank_page",
        build_pdf(pages),
        page_markers={
            1: ["MARK-P1-ALPHA", "MARK-P1-BETA"],
            3: ["MARK-P3-GAMMA"],
            4: ["MARK-P4-DELTA"],
        },
        empty_pages=[2],
        ordered=[["MARK-P1-ALPHA", "MARK-P1-BETA"]],
        own_line=["MARK-P1-ALPHA", "MARK-P1-BETA"],
    )


def _spans() -> Case:
    lines = [
        f"SPAN-{i:02d} synthetic control statement number {i} for offsets." for i in range(1, 21)
    ]
    return Case(
        "spans_and_offsets",
        build_pdf([Page(texts=text_block(60, 60, lines, size=10, leading=13))]),
        page_markers={1: [f"SPAN-{i:02d}" for i in range(1, 21)]},
        ordered=[[f"SPAN-{i:02d}" for i in range(1, 21)]],
        own_line=[f"SPAN-{i:02d}" for i in range(1, 21)],
    )


def _two_column(reverse_stream: bool) -> Case:
    left = text_block(50, 80, [f"LEFT-{i} left column sentence {i}." for i in range(1, 7)])
    right = text_block(320, 80, [f"RIGHT-{i} right column sentence {i}." for i in range(1, 7)])
    texts = right + left if reverse_stream else left + right
    name = "two_column_stream_right_first" if reverse_stream else "two_column"
    return Case(
        name,
        build_pdf([Page(texts=texts)]),
        page_markers={1: [f"LEFT-{i}" for i in range(1, 7)] + [f"RIGHT-{i}" for i in range(1, 7)]},
        ordered=[[f"LEFT-{i}" for i in range(1, 7)], [f"RIGHT-{i}" for i in range(1, 7)]],
        own_line=[f"LEFT-{i}" for i in range(1, 7)] + [f"RIGHT-{i}" for i in range(1, 7)],
    )


def _table() -> Case:
    rows = [["CTRL-ID", "CTRL-OWNER", "CTRL-FREQ"]] + [
        [f"T{r}C1-CC{r}.1", f"T{r}C2-Owner{r}", f"T{r}C3-Quarterly"] for r in range(1, 4)
    ]
    xs, y0, rh = [60, 220, 380, 540], 100, 24
    texts, lines = [], []
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            texts.append(TextItem(xs[c] + 6, y0 + r * rh + 16, cell, 10))
    for r in range(len(rows) + 1):
        lines.append((xs[0], y0 + r * rh, xs[-1], y0 + r * rh))
    for x in xs:
        lines.append((x, y0, x, y0 + len(rows) * rh))
    return Case(
        "table_grid",
        build_pdf([Page(texts=texts, lines=lines)]),
        page_markers={1: [c for row in rows for c in row]},
        ordered=[[row[0] for row in rows]],
        same_line=rows,
    )


def _questionnaire() -> Case:
    p1 = text_block(
        60,
        80,
        [
            "SECTION A: ACCESS CONTROL",
            "Do you enforce multi-factor authentication for all administrators?",
            "How often are user access reviews performed?",
            "Our team will respond with evidence.",
            "SECTION B: ENCRYPTION",
            "Is customer data encrypted at rest using AES-256?",
        ],
    )
    p2 = text_block(
        60,
        80,
        [
            "SECTION C: INCIDENT RESPONSE",
            "Do you have a documented incident response plan?",
            "Describe how security incidents are reported to customers.",
        ],
    )
    return Case(
        "questionnaire_two_pages",
        build_pdf([Page(texts=p1), Page(texts=p2)]),
        page_markers={
            1: ["multi-factor", "access reviews", "AES-256"],
            2: ["incident response plan"],
        },
        questions=[
            ("multi-factor authentication", 1, "SECTION A: ACCESS CONTROL"),
            ("access reviews", 1, "SECTION A: ACCESS CONTROL"),
            ("encrypted at rest", 1, "SECTION B: ENCRYPTION"),
            ("incident response plan", 2, "SECTION C: INCIDENT RESPONSE"),
            ("security incidents are reported", 2, "SECTION C: INCIDENT RESPONSE"),
        ],
    )


def _questionnaire_numbered() -> Case:
    """Numbered questions. The baseline treats "1. Do ..." lines as section headers
    (question_detector quirk, pre-existing); kept so parity with the baseline is checked."""
    return Case(
        "questionnaire_numbered",
        build_pdf(
            [
                Page(
                    texts=text_block(
                        60,
                        80,
                        [
                            "SECTION A: ACCESS CONTROL",
                            "1. Do you enforce multi-factor authentication for all administrators?",
                            "2. How often are user access reviews performed?",
                            "Is there a formal joiner/mover/leaver process?",
                        ],
                    )
                )
            ]
        ),
        page_markers={1: ["1. Do you enforce", "2. How often", "joiner/mover/leaver"]},
    )


def _questionnaire_table() -> Case:
    """Question cell plus answer cells on the same baseline (table-style questionnaire)."""
    rows = [
        ("Do you encrypt backups at rest?", "Yes", "No"),
        ("Is MFA required for remote access?", "Yes", "No"),
    ]
    texts = [TextItem(60, 80, "SECTION D: OPERATIONS")]
    for r, (q, a, b) in enumerate(rows):
        y = 110 + r * 20
        texts += [TextItem(60, y, q), TextItem(400, y, a), TextItem(460, y, b)]
    return Case(
        "questionnaire_table_cells",
        build_pdf([Page(texts=texts)]),
        page_markers={1: ["encrypt backups", "MFA required"]},
        questions=[
            ("encrypt backups at rest", 1, "SECTION D: OPERATIONS"),
            ("mfa required for remote access", 1, "SECTION D: OPERATIONS"),
        ],
    )


def _latin1() -> Case:
    return Case(
        "latin1_punctuation",
        build_pdf(
            [
                Page(
                    texts=text_block(
                        60,
                        80,
                        [
                            "LAT-1 Caf\u00e9 na\u00efve r\u00e9sum\u00e9 \u2013 en dash",
                            "LAT-2 \u201cquoted\u201d \u2018single\u2019 \u20ac100 \u00a7 4.2",
                        ],
                    )
                )
            ]
        ),
        page_markers={
            1: [
                "LAT-1 Caf\u00e9 na\u00efve r\u00e9sum\u00e9 \u2013 en dash",
                "LAT-2 \u201cquoted\u201d \u2018single\u2019 \u20ac100 \u00a7 4.2",
            ]
        },
    )


def _image_only() -> Case:
    return Case(
        "image_only_scan",
        build_pdf([Page(image=(50, 50, 495, 700)), Page(image=(50, 50, 495, 700))]),
        empty_pages=[1, 2],
        outcome="no_text",
    )


def _vector_only() -> Case:
    return Case(
        "vector_only_no_text",
        build_pdf([Page(lines=[(50, 50, 500, 50), (50, 50, 50, 500)])]),
        empty_pages=[1],
        outcome="no_text",
    )


def _whitespace_only() -> Case:
    return Case(
        "whitespace_only_text",
        build_pdf([Page(texts=[TextItem(72, 72, "   ")])]),
        empty_pages=[1],
        outcome="no_text",
    )


def _corrupt() -> Case:
    return Case("corrupt_not_pdf", b"this is not a pdf file\n" * 20, outcome="unreadable")


def _truncated() -> Case:
    good = build_pdf([Page(texts=text_block(72, 90, ["TRUNC-1 text"]))])
    return Case("truncated_pdf", good[:60], outcome="unreadable")


def _existing_fixture() -> Case:
    return Case(
        "repo_fixture_security_policy",
        path=FIXTURE_PDF,
        page_markers={1: ["Information Security Policy", "Incident Response"]},
    )


def encrypted_cases() -> list[Case]:
    """Encrypted variants (built with pypdf, which is the chosen dependency)."""
    import io

    from pypdf import PdfReader, PdfWriter

    base = build_pdf([Page(texts=text_block(72, 90, ["ENC-1 encrypted synthetic text"]))])
    out = []
    for name, user_pw, outcome in (
        ("encrypted_owner_only_empty_user_pw", "", "text"),
        ("encrypted_user_password_required", "secret-synthetic", "encrypted"),
    ):
        w = PdfWriter()
        for p in PdfReader(io.BytesIO(base)).pages:
            w.add_page(p)
        w.encrypt(user_password=user_pw, owner_password="owner-synthetic", algorithm="RC4-128")
        buf = io.BytesIO()
        w.write(buf)
        out.append(
            Case(
                name,
                buf.getvalue(),
                page_markers={1: ["ENC-1"]} if outcome == "text" else {},
                outcome=outcome,
            )
        )
    return out


def corpus(include_encrypted: bool = True) -> list[Case]:
    cases = [
        _multipage_blank(),
        _spans(),
        _two_column(False),
        _two_column(True),
        _table(),
        _questionnaire(),
        _questionnaire_numbered(),
        _questionnaire_table(),
        _latin1(),
        _image_only(),
        _vector_only(),
        _whitespace_only(),
        _corrupt(),
        _truncated(),
        _existing_fixture(),
    ]
    if include_encrypted:
        cases += encrypted_cases()
    return cases


def write_case(case: Case, directory: Path) -> Path:
    if case.path is not None:
        return case.path
    p = directory / f"{case.name}.pdf"
    p.write_bytes(case.pdf or b"")
    return p
