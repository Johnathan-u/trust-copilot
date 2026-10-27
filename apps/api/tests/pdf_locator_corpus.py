"""Synthetic text-PDF locator corpus (TC-01-003a / TC-01-003-AC2).

No locator corpus exists in the package or repo at baseline, so this one is
built deterministically from ``app.services.synthetic_pdf``. All content is
synthetic. Each case records what a correct PDF text locator must report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.services.synthetic_pdf import Page, TextItem, bt_row, build_pdf, text_block, tj_row

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "documents" / "security_policy.pdf"


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
    # TC-01-003b expected output: the parser's full question list, in order, as
    # (normalized text, page, section); None means "not asserted"
    exact_questions: list[tuple[str, int, str | None]] | None = None
    # TC-01-003b expected cell splits: every row split into >1 cell, in page order
    split_rows: list[tuple[str, ...]] | None = None


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
    sec = "SECTION D: OPERATIONS"
    return Case(
        "questionnaire_table_cells",
        build_pdf([Page(texts=texts)]),
        page_markers={1: ["encrypt backups", "MFA required"]},
        questions=[
            ("encrypt backups at rest", 1, sec),
            ("mfa required for remote access", 1, sec),
        ],
        exact_questions=[
            ("do you encrypt backups at rest", 1, sec),
            ("is mfa required for remote access", 1, sec),
        ],
        split_rows=[tuple(r) for r in rows],
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


# --- TC-01-003b: same-line table rows -------------------------------------------------
# Not part of corpus(): corpus() is the TC-01-003a set with a recorded PyMuPDF baseline
# (tests/fixtures/pdf_locator/baseline_pymupdf.json) and 149 scored checks.


def _rows_one_bt_per_row() -> Case:
    """Whole row in one BT block (Td moves), header row, Yes/No/N/A and checkbox cells."""
    sec = "SECTION E: DATA PROTECTION"
    xs = [60, 380, 430, 480]
    rows = [
        ("Question", "Yes", "No", "N/A"),
        ("Do you encrypt backups at rest?", "Yes", "No", "N/A"),
        ("Are encryption keys rotated at least annually?", "[X]", "[ ]", "[ ]"),
    ]
    raw = [bt_row(110 + r * 20, list(zip(xs, row))) for r, row in enumerate(rows)]
    raw.append(bt_row(170, [(60, "Describe how backup restores are tested.")]))
    return Case(
        "table_rows_one_bt_yes_no_na",
        build_pdf([Page(texts=[TextItem(60, 80, sec)], raw=b"\n".join(raw))]),
        page_markers={1: ["encrypt backups", "rotated at least annually", "restores are tested"]},
        exact_questions=[
            ("do you encrypt backups at rest", 1, sec),
            ("are encryption keys rotated at least annually", 1, sec),
            ("describe how backup restores are tested", 1, sec),
        ],
        split_rows=[tuple(c for c in row if c.strip()) for row in rows],
    )


def _rows_tj_kerning() -> Case:
    """Cells placed by TJ kerning; questions of different lengths, so answer columns do not
    line up and only the wide-gap rule (>= 3 em) applies. Word-level kerning inside a
    question (0.4 em) must not split it."""
    sec = "SECTION F: IDENTITY"
    raw = [
        tj_row(60, 110, ["Is MFA required for remote access?", -20000, "Yes", -3000, "No"]),
        tj_row(60, 130, ["Is SSO enforced for all staff?", -24000, "Yes", -3500, "No"]),
        tj_row(60, 150, ["Do", -400, "you", -400, "log", -400, "administrator", -400, "actions?"]),
    ]
    return Case(
        "table_rows_tj_kerning",
        build_pdf([Page(texts=[TextItem(60, 80, sec)], raw=b"\n".join(raw))]),
        page_markers={1: ["MFA required", "SSO enforced", "administrator"]},
        exact_questions=[
            ("is mfa required for remote access", 1, sec),
            ("is sso enforced for all staff", 1, sec),
            ("do you log administrator actions", 1, sec),
        ],
        split_rows=[
            ("Is MFA required for remote access?", "Yes", "No"),
            ("Is SSO enforced for all staff?", "Yes", "No"),
        ],
    )


def _rows_answers_first() -> Case:
    """Answer cells come before the question cell in the content stream (same baseline)."""
    sec = "SECTION G: LOGGING"
    rows = [
        ("Are audit logs retained for at least one year?", "Yes", "No"),
        ("Is log access restricted to the security team?", "Yes", "No"),
    ]
    texts = [TextItem(60, 80, sec)]
    for r, (q, a, b) in enumerate(rows):
        y = 110 + r * 20
        texts += [TextItem(400, y, a), TextItem(460, y, b), TextItem(60, y, q)]
    return Case(
        "table_rows_answers_first_in_stream",
        build_pdf([Page(texts=texts)]),
        page_markers={1: ["audit logs retained", "log access restricted"]},
        exact_questions=[
            ("are audit logs retained for at least one year", 1, sec),
            ("is log access restricted to the security team", 1, sec),
        ],
        # pypdf's plain text has no space before the question here ("Yes NoAre ..."), a
        # pre-existing pypdf quirk left as is in evidence text; the cut is still made at
        # the run boundary, so no characters move between cells.
        split_rows=[(a, b, q) for q, a, b in rows],
    )


def _rows_prefilled_answers() -> Case:
    """A filled-in free-text answer column to the right of the question column."""
    sec = "SECTION H: VENDORS"
    rows = [
        ("Is customer data encrypted in transit?", "Yes - TLS 1.2 or later on all endpoints."),
        ("How are vendor risks assessed?", "Annual review against the vendor policy."),
    ]
    texts = [TextItem(60, 80, sec)]
    for r, (q, a) in enumerate(rows):
        texts += [TextItem(60, 110 + r * 20, q), TextItem(330, 110 + r * 20, a)]
    return Case(
        "table_rows_prefilled_answers",
        build_pdf([Page(texts=texts)]),
        page_markers={1: ["encrypted in transit", "vendor risks"]},
        exact_questions=[
            ("is customer data encrypted in transit", 1, sec),
            ("how are vendor risks assessed", 1, sec),
        ],
        split_rows=rows,
    )


def _rows_two_question_cells() -> Case:
    """Two question columns on shared baselines, written row by row (left, right, left, ...).
    Plain text joins each pair on one line; both questions must be kept, in stream order."""
    sec = "SECTION J: PHYSICAL SECURITY"
    left = ["Are data centre visitors escorted?", "Is CCTV footage kept for 90 days?"]
    right = ["Do badges expire after 12 months?", "Are server racks locked?"]
    texts = [TextItem(60, 80, sec)]
    for r in range(2):
        texts += [TextItem(60, 110 + r * 20, left[r]), TextItem(320, 110 + r * 20, right[r])]
    return Case(
        "table_rows_two_question_columns",
        build_pdf([Page(texts=texts)]),
        page_markers={1: ["visitors escorted", "CCTV", "badges expire", "racks locked"]},
        exact_questions=[
            ("are data centre visitors escorted", 1, sec),
            ("do badges expire after 12 months", 1, sec),
            ("is cctv footage kept for 90 days", 1, sec),
            ("are server racks locked", 1, sec),
        ],
        split_rows=[(left[0], right[0]), (left[1], right[1])],
    )


def _rows_numbered() -> Case:
    """Question-number cell, question cell, answer cell. Joined, "1.1 Do ..." was read as a
    section header (question_detector quirk); cell by cell the question is kept."""
    sec = "SECTION K: ASSETS"
    rows = [
        ("1.1", "Do you maintain an asset inventory?", "Yes"),
        ("1.2", "Are assets assigned an owner?", "No"),
    ]
    raw = [bt_row(110 + r * 20, list(zip([60, 90, 400], row))) for r, row in enumerate(rows)]
    return Case(
        "table_rows_numbered",
        build_pdf([Page(texts=[TextItem(60, 80, sec)], raw=b"\n".join(raw))]),
        page_markers={1: ["asset inventory", "assigned an owner"]},
        exact_questions=[
            ("do you maintain an asset inventory", 1, sec),
            ("are assets assigned an owner", 1, sec),
        ],
        split_rows=rows,
    )


def _rows_not_split() -> Case:
    """Guards: nothing here may be split or lose text.

    * a justified question (0.8 em word gaps, one text object per word);
    * a lone row whose second cell is 2 em away and lines up with nothing (below the
      3 em lone-gap rule): stays joined, so the trailing text stays in the question;
    * aligned rows whose cells are not questions on their own but whose joined line is:
      the joined line is used.
    """
    sec = "SECTION L: GUARDS"
    texts = [TextItem(60, 80, sec)]
    x = 60.0
    for w in "Is the backup encryption key rotated annually?".split():
        texts.append(TextItem(x, 110, w))
        x += {
            "Is": 9.2,
            "the": 16.5,
            "backup": 37.3,
            "encryption": 53.2,
            "key": 18.3,
            "rotated": 37.3,
            "annually?": 48.9,
        }[w] + 0.8 * 11
    texts.append(TextItem(60, 130, "Describe your incident response process"))
    texts.append(TextItem(60 + 198.7 + 22, 130, "See IR-1"))  # 2 em after the question
    texts += [TextItem(60, 150, "Backups tested"), TextItem(300, 150, "(yes/no)?")]
    texts += [TextItem(60, 170, "Restores logged"), TextItem(300, 170, "(yes/no)?")]
    return Case(
        "table_rows_guards_not_split",
        build_pdf([Page(texts=texts)]),
        page_markers={1: ["backup encryption key", "IR-1", "Backups tested"]},
        exact_questions=[
            ("is the backup encryption key rotated annually", 1, sec),
            ("describe your incident response process see ir-1", 1, sec),
            ("backups tested (yes/no)", 1, sec),
            ("restores logged (yes/no)", 1, sec),
        ],
        split_rows=[("Backups tested", "(yes/no)?"), ("Restores logged", "(yes/no)?")],
    )


def _rows_two_column_blocks() -> Case:
    """Two-column questionnaire written column by column on shared baselines: reading
    order must stay left column then right column, sections per column."""
    left = text_block(
        50,
        80,
        [
            "SECTION M: NETWORK",
            "Are firewalls reviewed quarterly?",
            "Is network traffic segmented?",
        ],
    )
    right = text_block(
        320,
        80,
        [
            "SECTION N: PEOPLE",
            "Do staff receive security training?",
            "Are background checks performed?",
        ],
    )
    return Case(
        "table_rows_two_column_blocks",
        build_pdf([Page(texts=left + right)]),
        page_markers={1: ["firewalls reviewed", "segmented", "security training", "background"]},
        ordered=[["firewalls reviewed", "segmented", "security training", "background"]],
        exact_questions=[
            ("are firewalls reviewed quarterly", 1, "SECTION M: NETWORK"),
            ("is network traffic segmented", 1, "SECTION M: NETWORK"),
            ("do staff receive security training", 1, "SECTION N: PEOPLE"),
            ("are background checks performed", 1, "SECTION N: PEOPLE"),
        ],
        split_rows=[],
    )


def table_row_corpus() -> list[Case]:
    """TC-01-003b cases: same-line table rows with expected questions and cell splits."""
    return [
        _questionnaire_table(),
        _rows_one_bt_per_row(),
        _rows_tj_kerning(),
        _rows_answers_first(),
        _rows_prefilled_answers(),
        _rows_two_question_cells(),
        _rows_numbered(),
        _rows_not_split(),
        _rows_two_column_blocks(),
    ]


def write_case(case: Case, directory: Path) -> Path:
    if case.path is not None:
        return case.path
    p = directory / f"{case.name}.pdf"
    p.write_bytes(case.pdf or b"")
    return p
