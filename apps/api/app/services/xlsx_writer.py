"""XLSX workbook writer (EXP-02, EXP-03, EXP-04)."""

import json
import logging
import zipfile
from collections.abc import Callable
from copy import copy, deepcopy
from io import BytesIO
from pathlib import Path  # noqa: F401
from typing import Any
from xml.etree import ElementTree as ET

import openpyxl
from openpyxl.worksheet.formula import ArrayFormula, DataTableFormula

_logger = logging.getLogger(__name__)

# TC-13-003: leading characters that spreadsheet apps (Excel, LibreOffice,
# Google Sheets) may interpret as the start of a formula / DDE expression.
# Includes the full-width variants some locales/IMEs produce, and tab/CR per
# the OWASP CSV-injection guidance.
FORMULA_TRIGGER_CHARS: tuple[str, ...] = (
    "=",
    "+",
    "-",
    "@",
    "\t",
    "\r",
    "\uff1d",
    "\uff0b",
    "\uff0d",
    "\uff20",
)


def is_formula_like(value: Any) -> bool:
    """True if ``value`` is a string a spreadsheet app could treat as a formula.

    Leading spaces are ignored for detection (conservative: " =1+1" is flagged).
    """
    if not isinstance(value, str) or not value:
        return False
    if value[0] in FORMULA_TRIGGER_CHARS:
        return True
    stripped = value.lstrip(" ")
    return bool(stripped) and stripped[0] in FORMULA_TRIGGER_CHARS


def cell_has_formula(cell: Any) -> bool:
    """True if ``cell`` currently holds an original (template) formula."""
    if getattr(cell, "data_type", None) == "f":
        return True
    return isinstance(getattr(cell, "value", None), (ArrayFormula, DataTableFormula))


def write_literal_text(cell: Any, text: Any) -> None:
    """Write ``text`` into ``cell`` as a literal string, never as a formula (TC-13-003).

    openpyxl turns any str starting with "=" into a formula cell; forcing the
    data type to "s" stores it as a plain (inline) string instead. Formula-like
    values additionally get Excel's quotePrefix flag (the hidden leading
    apostrophe) so re-editing the cell in Excel keeps it literal too. The
    visible text is never altered.
    """
    value = "" if text is None else str(text)
    cell.value = value
    cell.data_type = "s"
    if is_formula_like(value):
        cell.quotePrefix = True


def create_workbook() -> openpyxl.Workbook:
    """Create new workbook."""
    return openpyxl.Workbook()


def write_answers_to_sheet(ws: openpyxl.worksheet.worksheet.Worksheet, answers: list[dict]) -> None:
    """Write answers to sheet. answers: [{row, col, text}, ...]."""
    for a in answers:
        row, col = a.get("row", 1), a.get("col", 1)
        write_literal_text(ws.cell(row=row, column=col), a.get("text", ""))


def save_workbook(wb: openpyxl.Workbook) -> bytes:
    """Save workbook to bytes."""
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def load_workbook_from_bytes(data: bytes) -> openpyxl.Workbook:
    """Load workbook from bytes (EXP-03)."""
    return openpyxl.load_workbook(BytesIO(data), data_only=False)


def _copy_cell_style(source: openpyxl.cell.cell.Cell, target: openpyxl.cell.cell.Cell) -> None:
    """Copy visual formatting from the question cell to the answer cell (EXP-04).

    TC-13-003: formats are not blindly copied.
    - If the target cell already has its own formatting (the template's answer
      column styling), it is preserved untouched.
    - number_format and protection are never copied: a question cell's number
      format (date, percent, currency, ...) has no meaning for answer text,
      and copying "locked"/"hidden" protection could hide or lock answers.
    """
    if not source.has_style or target.has_style:
        return
    target.font = copy(source.font)
    target.border = copy(source.border)
    target.fill = copy(source.fill)
    target.alignment = copy(source.alignment)


def place_answers_into_workbook(
    wb: openpyxl.Workbook,
    placements: list[dict[str, Any]],
    answer_col_offset: int = 1,
    skipped: list[dict[str, Any]] | None = None,
) -> openpyxl.Workbook:
    """Place answers into workbook cells (EXP-03, EXP-04, TC-13-003).

    placements: list of {sheet, row, col, text}.
    row, col are 1-based (question cell from source_location).
    Answer is written to (row, col + answer_col_offset) by default (next column).
    Answers are always written as literal text (never formulas). A target cell
    that already holds an original template formula is NOT overwritten; the
    placement is skipped, logged, and appended to ``skipped`` if provided.
    Question-cell formatting is copied only onto unstyled targets, and never
    number_format/protection (see _copy_cell_style).
    """
    for p in placements:
        sheet_name = p.get("sheet")
        row = p.get("row", 1)
        col = p.get("col", 1)
        text = p.get("text", "")
        if not sheet_name or sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        answer_col = col + answer_col_offset
        question_cell = ws.cell(row=row, column=col)
        answer_cell = ws.cell(row=row, column=answer_col)
        if cell_has_formula(answer_cell):
            _logger.warning(
                "EXPORT: skipped answer placement; target holds original formula sheet=%r cell=%s",
                sheet_name,
                answer_cell.coordinate,
            )
            if skipped is not None:
                skipped.append(
                    {
                        "sheet": sheet_name,
                        "cell": answer_cell.coordinate,
                        "reason": "target_has_formula",
                    }
                )
            continue
        _copy_cell_style(question_cell, answer_cell)
        write_literal_text(answer_cell, text)
    return wb


def placements_from_questions_and_answers(
    questions: list[dict],
    question_to_answer: dict[int, str],
) -> list[dict[str, Any]]:
    """Build placement list from questions with source_location and answer map.

    questions: list of {id, source_location, ...}
    question_to_answer: {question_id: answer_text}
    """
    placements = []
    for q in questions:
        qid = q.get("id")
        if qid is None:
            continue
        text = question_to_answer.get(qid, "")
        loc_raw = q.get("source_location")
        if not loc_raw:
            continue
        try:
            loc = json.loads(loc_raw) if isinstance(loc_raw, str) else loc_raw
        except (json.JSONDecodeError, TypeError):
            continue
        placements.append(
            {
                "sheet": loc.get("sheet"),
                "row": loc.get("row", 1),
                "col": loc.get("col", 1),
                "text": text,
            }
        )
    return placements


class UnsupportedWorkbookStructure(ValueError):
    """The workbook contains parts this exporter would drop or rewrite."""

    def __init__(self, features: list[str]) -> None:
        self.features = tuple(dict.fromkeys(features))
        listed = ", ".join(self.features)
        super().__init__(
            "This workbook cannot be exported because it contains unsupported content "
            f"({listed}). That content would be dropped or rewritten. "
            "Remove it from the workbook and export again."
        )


_Package = tuple[list[str], dict[str, bytes]]
_Detector = Callable[[list[str], dict[str, bytes]], bool]

# Extension URIs openpyxl removes while reading a worksheet (see its EXT_TYPES).
_SPARKLINE_URI = "{05C60535-1F16-4FD2-B633-F4F36F0B64E0}"
_SLICER_URIS = (
    "{A8765BA9-456A-4DAB-B4F3-ACF838C121DE}",
    "{3A4CF648-6AED-40F4-86FF-DC5316D8AED3}",
)
_TIMELINE_URI = "{7E03D99C-DC04-49D9-9315-930204A7B6E9}"
_PROTECTED_RANGE_URI = "{FC87AEE6-9EDD-4A0A-B7FB-166176984837}"
_IGNORED_ERROR_URI = "{01252117-D84E-4E92-8308-4BE1C098FCBB}"
_WEB_EXTENSION_URI = "{F7C9EE02-42E1-4005-9D12-6889AFFD525C}"
_SHAPE_TAGS = frozenset({"sp", "cxnsp", "grpsp", "wsp"})
_VML_SHAPE_TAGS = frozenset(
    {"shape", "rect", "oval", "line", "polyline", "curve", "roundrect", "arc", "group"}
)
_CONTROL_TYPES = frozenset(
    {
        "button",
        "checkbox",
        "drop",
        "list",
        "radio",
        "scroll",
        "spin",
        "gbox",
        "label",
        "dialog",
        "edit",
    }
)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _root(blob: bytes) -> ET.Element | None:
    if not blob:
        return None
    try:
        return ET.fromstring(blob)
    except ET.ParseError:
        return None


def _named_blob(blobs: dict[str, bytes], part: str) -> bytes:
    for name, blob in blobs.items():
        if name.lower() == part:
            return blob
    return b""


def _worksheet_roots(blobs: dict[str, bytes]) -> list[ET.Element]:
    roots: list[ET.Element] = []
    for name, blob in blobs.items():
        low = name.lower()
        if not low.startswith("xl/worksheets/") or not low.endswith(".xml"):
            continue
        if "/_rels/" in low:
            continue
        root = _root(blob)
        if root is not None:
            roots.append(root)
    return roots


def _has_prefix(names: list[str], prefixes: tuple[str, ...]) -> bool:
    for name in names:
        low = name.lower()
        if any(low.startswith(prefix) for prefix in prefixes):
            return True
    return False


def _contains_uri(blobs: dict[str, bytes], uris: tuple[str, ...]) -> bool:
    needles = tuple(uri.upper().encode("ascii") for uri in uris)
    for blob in blobs.values():
        upper = blob.upper()
        if any(needle in upper for needle in needles):
            return True
    return False


def _content_types(blobs: dict[str, bytes]) -> bytes:
    for name, blob in blobs.items():
        if name.lower() == "[content_types].xml":
            return blob.lower()
    return b""


def _has_macros(names: list[str], blobs: dict[str, bytes]) -> bool:
    for name in names:
        low = name.lower()
        if "vbaproject" in low:
            return True
    content = _content_types(blobs)
    return b"vbaproject" in content or b"macroenabled" in content


def _vml_object_types(blob: bytes) -> list[str | None] | None:
    """ClientData ObjectType for each VML shape. None if the part is not XML."""
    root = _root(blob)
    if root is None:
        return None
    found: list[str | None] = []
    for el in root.iter():
        if _local(el.tag).lower() not in _VML_SHAPE_TAGS:
            continue
        obj: str | None = None
        for child in el.iter():
            if _local(child.tag).lower() != "clientdata":
                continue
            for key, value in child.attrib.items():
                if _local(key).lower() == "objecttype":
                    obj = value
        found.append(obj)
    return found


def _has_shapes(names: list[str], blobs: dict[str, bytes]) -> bool:
    for name, blob in blobs.items():
        low = name.lower()
        if "/drawings/" in low and low.endswith(".xml"):
            root = _root(blob)
            if root is None:
                return True
            for el in root.iter():
                if _local(el.tag).lower() in _SHAPE_TAGS:
                    return True
        if low.endswith(".vml"):
            types = _vml_object_types(blob)
            if types is None:
                return True
            for obj in types:
                if obj is None or obj.lower() not in _CONTROL_TYPES | {"note"}:
                    return True
    for root in _worksheet_roots(blobs):
        for el in root.iter():
            if _local(el.tag) in {"legacyDrawingHF", "drawingHF"}:
                return True
    return False


def _has_form_controls(names: list[str], blobs: dict[str, bytes]) -> bool:
    if _has_prefix(names, ("xl/ctrlprops/", "xl/activex/")):
        return True
    content = _content_types(blobs)
    if b"controlproperties" in content or b"activex" in content:
        return True
    for root in _worksheet_roots(blobs):
        for el in root.iter():
            if _local(el.tag) in {"controls", "control"}:
                return True
    for name, blob in blobs.items():
        if not name.lower().endswith(".vml"):
            continue
        types = _vml_object_types(blob)
        if not types:
            continue
        for obj in types:
            if obj and obj.lower() in _CONTROL_TYPES:
                return True
    return False


def _has_pivot_caches(names: list[str], blobs: dict[str, bytes]) -> bool:
    if _has_prefix(names, ("xl/pivotcache/", "xl/pivottables/")):
        return True
    workbook = _root(_named_blob(blobs, "xl/workbook.xml"))
    if workbook is None:
        return False
    return any(_local(el.tag) in {"pivotCaches", "pivotCache"} for el in workbook.iter())


def _has_external_links(names: list[str], blobs: dict[str, bytes]) -> bool:
    if _has_prefix(names, ("xl/externallinks/",)):
        return True
    for name, blob in blobs.items():
        if name.lower().endswith(".rels") and b"externallink" in blob.lower():
            return True
    return False


def _has_slicers(names: list[str], blobs: dict[str, bytes]) -> bool:
    if _has_prefix(names, ("xl/slicers/", "xl/slicercaches/")):
        return True
    return _contains_uri(blobs, _SLICER_URIS)


def _has_timelines(names: list[str], blobs: dict[str, bytes]) -> bool:
    if _has_prefix(names, ("xl/timelines/", "xl/timelinecaches/")):
        return True
    return _contains_uri(blobs, (_TIMELINE_URI,))


def _has_sparklines(names: list[str], blobs: dict[str, bytes]) -> bool:
    if _has_prefix(names, ("xl/sparklines/",)):
        return True
    if _contains_uri(blobs, (_SPARKLINE_URI,)):
        return True
    for root in _worksheet_roots(blobs):
        for el in root.iter():
            if _local(el.tag).lower() in {"sparkline", "sparklinegroup", "sparklinegroups"}:
                return True
    return False


def _has_embeddings(names: list[str], blobs: dict[str, bytes]) -> bool:
    if _has_prefix(names, ("xl/embeddings/",)):
        return True
    for root in _worksheet_roots(blobs):
        for el in root.iter():
            if _local(el.tag) in {"oleObjects", "oleObject"}:
                return True
    return False


def _has_connections(names: list[str], blobs: dict[str, bytes]) -> bool:
    for name in names:
        low = name.lower()
        if low == "xl/connections.xml" or low.startswith("xl/querytables/"):
            return True
    return False


def _has_web_extensions(names: list[str], blobs: dict[str, bytes]) -> bool:
    if _has_prefix(names, ("xl/webextensions/",)):
        return True
    return _contains_uri(blobs, (_WEB_EXTENSION_URI,))


def _has_custom_xml(names: list[str], blobs: dict[str, bytes]) -> bool:
    return _has_prefix(names, ("customxml/",))


def _has_protected_ranges(names: list[str], blobs: dict[str, bytes]) -> bool:
    if _contains_uri(blobs, (_PROTECTED_RANGE_URI,)):
        return True
    for root in _worksheet_roots(blobs):
        for el in root.iter():
            if _local(el.tag) in {"protectedRanges", "protectedRange"}:
                return True
    return False


def _has_custom_ribbon(names: list[str], blobs: dict[str, bytes]) -> bool:
    return _has_prefix(names, ("customui/",))


def _has_threaded_comments(names: list[str], blobs: dict[str, bytes]) -> bool:
    for name in names:
        low = name.lower()
        if low.startswith("xl/threadedcomments/") or low == "xl/persons.xml":
            return True
    return False


def _has_sheet_backgrounds(names: list[str], blobs: dict[str, bytes]) -> bool:
    for root in _worksheet_roots(blobs):
        for el in root.iter():
            if _local(el.tag) == "picture":
                return True
    return False


def _has_ignored_errors(names: list[str], blobs: dict[str, bytes]) -> bool:
    if _contains_uri(blobs, (_IGNORED_ERROR_URI,)):
        return True
    for root in _worksheet_roots(blobs):
        for el in root.iter():
            if _local(el.tag) in {"ignoredErrors", "ignoredError"}:
                return True
    return False


_DETECTORS: tuple[tuple[str, _Detector], ...] = (
    ("macros", _has_macros),
    ("shapes", _has_shapes),
    ("form controls", _has_form_controls),
    ("pivot tables", _has_pivot_caches),
    ("external links", _has_external_links),
    ("slicers", _has_slicers),
    ("timelines", _has_timelines),
    ("sparklines", _has_sparklines),
    ("embedded objects", _has_embeddings),
    ("data connections", _has_connections),
    ("web extensions", _has_web_extensions),
    ("custom XML parts", _has_custom_xml),
    ("protected ranges", _has_protected_ranges),
    ("custom ribbon", _has_custom_ribbon),
    ("threaded comments", _has_threaded_comments),
    ("sheet backgrounds", _has_sheet_backgrounds),
    ("ignored errors", _has_ignored_errors),
)


def _read_ooxml_package(data: bytes) -> _Package | None:
    """Return part names and XML/VML bytes, or None when this is not an OOXML zip."""
    try:
        if not zipfile.is_zipfile(BytesIO(data)):
            return None
        with zipfile.ZipFile(BytesIO(data)) as zf:
            names = [name.replace("\\", "/") for name in zf.namelist()]
            blobs: dict[str, bytes] = {}
            for name in names:
                low = name.lower()
                if low.endswith((".xml", ".vml", ".rels")):
                    blobs[name] = zf.read(name)
    except zipfile.BadZipFile:
        return None
    return names, blobs


def unsupported_workbook_features(data: bytes) -> list[str]:
    """Labels for workbook parts the exporter would drop or rewrite.

    Comment-note VML (ObjectType Note) is not listed: cell-comment text is kept
    and only the note drawing is regenerated. calcChain and printer settings are
    caches the viewer rebuilds, so they are not listed either.
    """
    package = _read_ooxml_package(data)
    if package is None:
        return []
    names, blobs = package
    if not any(name.lower() == "xl/workbook.xml" for name in names):
        return []
    found: list[str] = []
    for label, detector in _DETECTORS:
        if detector(names, blobs):
            found.append(label)
    return found


def reject_unsupported_workbook(data: bytes) -> None:
    """Raise when exporting would drop or rewrite workbook structure."""
    features = unsupported_workbook_features(data)
    if features:
        raise UnsupportedWorkbookStructure(features)


_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_EMBED_ATTR = f"{{{_OFFICE_REL_NS}}}embed"
_IMAGE_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
}


def _zip_files(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(BytesIO(data)) as zf:
        return {name.replace("\\", "/"): zf.read(name) for name in zf.namelist()}


def _resolve_target(base_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    base_dir = base_part.rsplit("/", 1)[0]
    parts: list[str] = []
    for piece in f"{base_dir}/{target}".split("/"):
        if piece == "..":
            if parts:
                parts.pop()
        elif piece not in {"", "."}:
            parts.append(piece)
    return "/".join(parts)


def _picture_specs(files: dict[str, bytes]) -> list[dict[str, Any]]:
    """Picture anchors and the media parts they embed."""
    specs: list[dict[str, Any]] = []
    for name, blob in files.items():
        low = name.lower()
        if not (low.startswith("xl/drawings/") and low.endswith(".xml")):
            continue
        root = _root(blob)
        if root is None:
            continue
        parent, leaf = name.rsplit("/", 1)
        rels_name = f"{parent}/_rels/{leaf}.rels"
        rels_root = _root(files.get(rels_name, b""))
        targets: dict[str, str] = {}
        if rels_root is not None:
            for rel in rels_root:
                if _local(rel.tag) != "Relationship":
                    continue
                if not rel.attrib.get("Type", "").endswith("/image"):
                    continue
                targets[rel.attrib.get("Id", "")] = rel.attrib.get("Target", "")
        for anchor in list(root):
            if not any(_local(el.tag) == "pic" for el in anchor.iter()):
                continue
            embed = None
            for el in anchor.iter():
                if _EMBED_ATTR in el.attrib:
                    embed = el.attrib[_EMBED_ATTR]
                    break
            if not embed or embed not in targets:
                continue
            media = _resolve_target(name, targets[embed])
            if media not in files:
                continue
            specs.append(
                {
                    "drawing": name,
                    "rels": rels_name,
                    "anchor": anchor,
                    "media": media,
                    "bytes": files[media],
                }
            )
    return specs


def _next_rid(used: set[str]) -> str:
    number = 1
    while f"rId{number}" in used:
        number += 1
    rid = f"rId{number}"
    used.add(rid)
    return rid


def _used_rids(root: ET.Element | None) -> set[str]:
    used: set[str] = set()
    if root is None:
        return used
    for el in root.iter():
        for key, value in el.attrib.items():
            if _local(key) in {"id", "embed"} and value.startswith("rId"):
                used.add(value)
        if _local(el.tag) == "Relationship" and el.attrib.get("Id", "").startswith("rId"):
            used.add(el.attrib["Id"])
    return used


def _sheet_for_drawing(files: dict[str, bytes], drawing: str) -> str | None:
    for name, blob in files.items():
        low = name.lower()
        if not (low.startswith("xl/worksheets/_rels/") and low.endswith(".rels")):
            continue
        root = _root(blob)
        if root is None:
            continue
        for rel in root:
            if _local(rel.tag) != "Relationship":
                continue
            if not rel.attrib.get("Type", "").endswith("/drawing"):
                continue
            target = _resolve_target(name, rel.attrib.get("Target", ""))
            if target == drawing:
                sheet = name.replace("/_rels/", "/").replace(".rels", "")
                # xl/worksheets/_rels/sheet1.xml.rels -> xl/worksheets/sheet1.xml
                return sheet
    return None


def _ensure_content_type(
    files: dict[str, bytes],
    extension: str,
    part: str | None,
    part_type: str | None,
) -> None:
    blob = _named_blob(files, "[Content_Types].xml")
    root = _root(blob)
    if root is None:
        return
    ns = _CONTENT_TYPES_NS
    extensions = set()
    parts = set()
    for el in root:
        if _local(el.tag) == "Default":
            extensions.add(el.attrib.get("Extension", "").lower())
        elif _local(el.tag) == "Override":
            parts.add(el.attrib.get("PartName", ""))
    if extension.lower() not in extensions and extension.lower() in _IMAGE_CONTENT_TYPES:
        node = ET.Element(f"{{{ns}}}Default")
        node.set("Extension", extension.lower())
        node.set("ContentType", _IMAGE_CONTENT_TYPES[extension.lower()])
        root.insert(0, node)
    if part and part_type and part not in parts and f"/{part}" not in parts:
        node = ET.Element(f"{{{ns}}}Override")
        node.set("PartName", "/" + part.lstrip("/"))
        node.set("ContentType", part_type)
        root.append(node)
    files["[Content_Types].xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _ensure_sheet_drawing(files: dict[str, bytes], sheet: str, drawing: str) -> None:
    rels_name = sheet.rsplit("/", 1)[0] + "/_rels/" + sheet.rsplit("/", 1)[1] + ".rels"
    rels_root = _root(files.get(rels_name, b""))
    if rels_root is None:
        rels_root = ET.Element(f"{{{_PKG_REL_NS}}}Relationships")
    used = _used_rids(rels_root)
    linked = False
    for rel in rels_root:
        if _local(rel.tag) != "Relationship":
            continue
        if not rel.attrib.get("Type", "").endswith("/drawing"):
            continue
        if _resolve_target(rels_name, rel.attrib.get("Target", "")) == drawing:
            linked = True
            rid = rel.attrib.get("Id", "")
            break
    else:
        rid = ""
    if not linked:
        rid = _next_rid(used)
        rel = ET.SubElement(rels_root, f"{{{_PKG_REL_NS}}}Relationship")
        rel.set("Id", rid)
        rel.set("Type", _OFFICE_REL_NS + "/drawing")
        rel.set("Target", "/" + drawing)
    files[rels_name] = ET.tostring(rels_root, encoding="utf-8", xml_declaration=True)
    sheet_root = _root(files.get(sheet, b""))
    if sheet_root is None or any(_local(el.tag) == "drawing" for el in sheet_root):
        return
    if sheet_root.tag.startswith("{"):
        ns = sheet_root.tag[1:].split("}", 1)[0]
        tag = f"{{{ns}}}drawing"
    else:
        tag = "drawing"
    drawing_el = ET.SubElement(sheet_root, tag)
    drawing_el.set(f"{{{_OFFICE_REL_NS}}}id", rid)
    files[sheet] = ET.tostring(sheet_root, encoding="utf-8", xml_declaration=True)


def _restore_dropped_pictures(original: bytes, saved: bytes) -> bytes:
    """Copy picture anchors openpyxl dropped back into ``saved``.

    openpyxl writes embedded pictures only when Pillow is installed. The
    supported subset includes images, and Pillow is not part of the runtime
    install, so a missing picture is copied from the original package.
    """
    try:
        original_files = _zip_files(original)
        saved_files = _zip_files(saved)
    except zipfile.BadZipFile:
        return saved
    specs = _picture_specs(original_files)
    if not specs:
        return saved
    already_kept = all(
        spec["media"] in saved_files and saved_files[spec["media"]] == spec["bytes"]
        for spec in specs
    )
    if already_kept:
        return saved
    by_drawing: dict[str, list[dict[str, Any]]] = {}
    for spec in specs:
        by_drawing.setdefault(spec["drawing"], []).append(spec)
    for drawing, group in by_drawing.items():
        drawing_root = _root(saved_files.get(drawing, b""))
        if drawing_root is None:
            drawing_root = ET.Element(
                "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}wsDr"
            )
        rels_name = group[0]["rels"]
        rels_root = _root(saved_files.get(rels_name, b""))
        if rels_root is None:
            rels_root = ET.Element(f"{{{_PKG_REL_NS}}}Relationships")
        used = _used_rids(drawing_root) | _used_rids(rels_root)
        for spec in group:
            rid = _next_rid(used)
            anchor = deepcopy(spec["anchor"])
            for el in anchor.iter():
                if _EMBED_ATTR in el.attrib:
                    el.attrib[_EMBED_ATTR] = rid
            drawing_root.append(anchor)
            rel = ET.SubElement(rels_root, f"{{{_PKG_REL_NS}}}Relationship")
            rel.set("Id", rid)
            rel.set("Type", _OFFICE_REL_NS + "/image")
            rel.set("Target", "/" + spec["media"])
            saved_files[spec["media"]] = spec["bytes"]
            extension = spec["media"].rsplit(".", 1)[-1]
            _ensure_content_type(
                saved_files,
                extension,
                drawing if drawing not in saved_files else None,
                "application/vnd.openxmlformats-officedocument.drawing+xml",
            )
        saved_files[drawing] = ET.tostring(drawing_root, encoding="utf-8", xml_declaration=True)
        saved_files[rels_name] = ET.tostring(rels_root, encoding="utf-8", xml_declaration=True)
        if drawing not in _zip_files(saved):
            sheet = _sheet_for_drawing(original_files, drawing)
            if sheet and sheet in saved_files:
                _ensure_sheet_drawing(saved_files, sheet, drawing)
            _ensure_content_type(
                saved_files,
                "",
                drawing,
                "application/vnd.openxmlformats-officedocument.drawing+xml",
            )
    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, blob in saved_files.items():
            zf.writestr(name, blob)
    return out.getvalue()


def create_export_from_questionnaire(
    xlsx_bytes: bytes,
    questions: list[dict],
    question_to_answer: dict[int, str],
    answer_col_offset: int = 1,
    skipped: list[dict[str, Any]] | None = None,
) -> bytes:
    """Load original XLSX, place answers, return modified XLSX bytes (EXP-03).

    Original formulas elsewhere in the workbook are preserved (loaded with
    data_only=False); answers are written as literal text (TC-13-003).
    Workbooks whose parts would be dropped or rewritten are rejected first.
    """
    reject_unsupported_workbook(xlsx_bytes)
    wb = load_workbook_from_bytes(xlsx_bytes)
    placements = placements_from_questions_and_answers(questions, question_to_answer)
    wb = place_answers_into_workbook(wb, placements, answer_col_offset, skipped=skipped)
    # openpyxl keeps embedded pictures only when Pillow is installed. Copy any
    # picture it dropped back into the package so the supported subset survives
    # without adding a dependency.
    return _restore_dropped_pictures(xlsx_bytes, save_workbook(wb))
