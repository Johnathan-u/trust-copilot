"""Workbook export keeps the supported OOXML subset and rejects the rest.

Synthetic workbooks only. One checked-in fixture was saved by LibreOffice
headless (see ``libreoffice_supported_subset.xlsx``); the other is built here
with openpyxl. No database, network, storage or model calls except the worker
tests, which stub storage.
"""

from __future__ import annotations

import io
import json
import re
import struct
import zipfile
import zlib
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.formula import ArrayFormula

from app.services.xlsx_writer import (
    UnsupportedWorkbookStructure,
    create_export_from_questionnaire,
    unsupported_workbook_features,
)

_LO_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "questionnaires"
    / "libreoffice_supported_subset.xlsx"
)
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_BUILTIN_NUM_FMTS = {
    0: "General",
    1: "0",
    2: "0.00",
    9: "0%",
    10: "0.00%",
    11: "0.00E+00",
    14: "mm-dd-yy",
}
_ANSWERS = {"Security": {"B2"}}


def _png_bytes() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    width, height = 8, 8
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


_IMAGE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
_DRAWING_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"


def _embed_png(package: bytes, png: bytes, *, col: int, row: int) -> bytes:
    """Add a PNG picture without Pillow. ``col`` and ``row`` are zero-based."""
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(package)) as zf:
        for name in zf.namelist():
            files[name] = zf.read(name)
    files["xl/media/image1.png"] = png
    content = files["[Content_Types].xml"]
    if b'Extension="png"' not in content:
        needle = b'<Default Extension="xml" ContentType="application/xml"/>'
        content = content.replace(
            needle,
            needle + b'<Default Extension="png" ContentType="image/png"/>',
            1,
        )
        files["[Content_Types].xml"] = content
    drawing_name = "xl/drawings/drawing1.xml"
    rels_name = "xl/drawings/_rels/drawing1.xml.rels"
    rels = files.get(rels_name, b"")
    numbers = [int(item) for item in re.findall(br'Id="rId(\d+)"', rels)]
    rid = f"rId{max(numbers) + 1 if numbers else 1}"
    anchor = (
        "<oneCellAnchor>"
        f"<from><col>{col}</col><colOff>0</colOff><row>{row}</row><rowOff>0</rowOff></from>"
        '<ext cx="76200" cy="76200"/>'
        "<pic><nvPicPr><cNvPr id=\"9\" name=\"Picture 1\"/><cNvPicPr/></nvPicPr>"
        "<blipFill>"
        '<a:blip xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        f'r:embed="{rid}"/>'
        '<a:stretch xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<a:fillRect/></a:stretch></blipFill>"
        '<spPr><a:prstGeom xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'prst="rect"/></spPr></pic><clientData/></oneCellAnchor>'
    )
    if drawing_name in files:
        drawing = files[drawing_name].decode("utf-8")
        close = "</wsDr>" if "</wsDr>" in drawing else "</xdr:wsDr>"
        files[drawing_name] = drawing.replace(close, anchor + close, 1).encode("utf-8")
        if rels:
            files[rels_name] = rels.replace(
                b"</Relationships>",
                (
                    f'<Relationship Id="{rid}" Type="{_IMAGE_REL}" '
                    'Target="/xl/media/image1.png"/></Relationships>'
                ).encode("utf-8"),
                1,
            )
        else:
            files[rels_name] = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'<Relationship Id="{rid}" Type="{_IMAGE_REL}" '
                'Target="/xl/media/image1.png"/></Relationships>'
            ).encode("utf-8")
    else:
        files[drawing_name] = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<wsDr xmlns="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing">'
            f"{anchor}</wsDr>"
        ).encode("utf-8")
        files[rels_name] = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="{rid}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            'Target="/xl/media/image1.png"/></Relationships>'
        ).encode("utf-8")
        sheet = files["xl/worksheets/sheet1.xml"].decode("utf-8")
        sheet_rels = files.get("xl/worksheets/_rels/sheet1.xml.rels", b"")
        sheet_numbers = [int(item) for item in re.findall(br'Id="rId(\d+)"', sheet_rels)]
        sheet_rid = f"rId{max(sheet_numbers) + 1 if sheet_numbers else 1}"
        drawing_tag = f'<drawing xmlns:r="{_DRAWING_REL}" r:id="{sheet_rid}"/>'
        files["xl/worksheets/sheet1.xml"] = sheet.replace(
            "</worksheet>", drawing_tag + "</worksheet>", 1
        ).encode("utf-8")
        rel = (
            f'<Relationship Id="{sheet_rid}" Type="{_DRAWING_REL}" '
            'Target="/xl/drawings/drawing1.xml"/>'
        )
        if sheet_rels:
            files["xl/worksheets/_rels/sheet1.xml.rels"] = sheet_rels.replace(
                b"</Relationships>", rel.encode("utf-8") + b"</Relationships>", 1
            )
        else:
            files["xl/worksheets/_rels/sheet1.xml.rels"] = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f"{rel}</Relationships>"
            ).encode("utf-8")
        override = (
            '<Override PartName="/xl/drawings/drawing1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
        )
        files["[Content_Types].xml"] = files["[Content_Types].xml"].replace(
            b"</Types>", override.encode("utf-8") + b"</Types>", 1
        )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, blob in files.items():
            zf.writestr(name, blob)
    return out.getvalue()


def build_supported_workbook(directory: Path, *, array_formula: bool = True) -> bytes:
    """Workbook containing each supported part. ``directory`` receives the PNG."""
    directory.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.properties.creator = "synthetic fixture"
    wb.properties.lastModifiedBy = "synthetic fixture"
    wb.properties.title = "Supported subset sample"
    ws = wb.active
    ws.title = "Security"
    ws["A1"] = "Question"
    ws["A1"].font = Font(name="Calibri", bold=True, color="FF0000", size=14)
    ws["A1"].fill = PatternFill("solid", fgColor="00AA00")
    ws["A1"].alignment = Alignment(horizontal="center", wrap_text=True)
    thin = Side(style="thin", color="0000FF")
    ws["A1"].border = Border(left=thin)
    ws.merge_cells("A1:C1")
    ws["A2"] = "Do you encrypt data at rest?"
    ws["C2"] = "notes stay"
    ws["D2"] = "=LEN(A2)"
    ws["E2"] = 100
    ws["E2"].number_format = "0.00%"
    ws["B3"] = "preset"
    ws["B3"].font = Font(name="Arial", italic=True, size=12, color="112233")
    ws["F2"] = "A"
    ws["F3"] = "B"
    ws["G1"] = "Score"
    ws["G2"] = 3
    ws["G3"] = 5
    if array_formula:
        ws["H2"] = ArrayFormula("H2:H3", "=E2:E3")
    validation = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
    validation.add("B2:B10")
    ws.add_data_validation(validation)
    chart = BarChart()
    chart.title = "Scores"
    chart.add_data(Reference(ws, min_col=7, min_row=1, max_row=3), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=6, min_row=2, max_row=3))
    chart.shape = 4
    chart.legend = None
    ws.add_chart(chart, "E5")
    hidden = wb.create_sheet("HiddenCalc")
    hidden.sheet_state = "hidden"
    hidden["A1"] = "calc"
    hidden["B1"] = "=SUM(Security!E2)"
    very = wb.create_sheet("VeryHidden")
    very.sheet_state = "veryHidden"
    very["A1"] = "kept"
    very["C3"] = '=IF(Security!A2="",0,1)'
    wb.defined_names.add(DefinedName(name="ScoreCell", attr_text="Security!$E$2"))
    wb.defined_names.add(DefinedName(name="HiddenName", attr_text="HiddenCalc!$A$1", hidden=True))
    buf = io.BytesIO()
    wb.save(buf)
    # Row 12 is zero-based row 11. The runtime image does not install Pillow.
    return _embed_png(buf.getvalue(), _png_bytes(), col=0, row=11)


def _export(data: bytes, answer: str = "Approved") -> bytes:
    questions = [
        {"id": 1, "source_location": json.dumps({"sheet": "Security", "row": 2, "col": 1})}
    ]
    return create_export_from_questionnaire(data, questions, {1: answer})


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return "".join(el.itertext())


def _files(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _flag(el: ET.Element, name: str) -> bool:
    for child in el:
        if _local(child.tag) == name:
            return child.attrib.get("val", "1") not in {"0", "false", "False"}
    return False


def _color(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    for child in el:
        if _local(child.tag) != "color":
            continue
        if "rgb" in child.attrib:
            return child.attrib["rgb"][-6:].upper()
        if "theme" in child.attrib:
            return "theme:" + child.attrib["theme"] + ":" + child.attrib.get("tint", "")
        if "indexed" in child.attrib:
            return "indexed:" + child.attrib["indexed"]
    return None


def _font_sig(font: ET.Element) -> tuple:
    name = size = None
    for child in font:
        if _local(child.tag) == "name":
            name = child.attrib.get("val")
        elif _local(child.tag) == "sz":
            size = str(float(child.attrib.get("val", "0")))
    return (name, size, _flag(font, "b"), _flag(font, "i"), _color(font))


def _fill_sig(fill: ET.Element) -> tuple:
    for child in fill:
        if _local(child.tag) != "patternFill":
            continue
        pattern = child.attrib.get("patternType") or "none"
        fg = None
        for grand in child:
            if _local(grand.tag) != "fgColor":
                continue
            if "rgb" in grand.attrib:
                fg = grand.attrib["rgb"][-6:].upper()
            elif "theme" in grand.attrib:
                fg = "theme:" + grand.attrib["theme"]
        return (pattern, fg)
    return ("none", None)


def _border_sig(border: ET.Element) -> tuple:
    found = {}
    for child in border:
        side = _local(child.tag)
        style = child.attrib.get("style")
        if side in {"left", "right", "top", "bottom"} and style:
            found[side] = (style, _color(child))
    return tuple(sorted(found.items()))


def _style_tables(blob: bytes):
    root = ET.fromstring(blob)
    fonts = fills = borders = xfs = None
    num_fmts: dict[int, str] = {}
    for child in root:
        name = _local(child.tag)
        if name == "fonts":
            fonts = list(child)
        elif name == "fills":
            fills = list(child)
        elif name == "borders":
            borders = list(child)
        elif name == "cellXfs":
            xfs = list(child)
        elif name == "numFmts":
            for item in child:
                if _local(item.tag) == "numFmt":
                    num_fmts[int(item.attrib["numFmtId"])] = item.attrib.get("formatCode", "")
    return fonts, fills, borders, xfs, num_fmts


def _xf_sig(xf: ET.Element, fonts, fills, borders, num_fmts) -> tuple:
    font = fonts[int(xf.attrib.get("fontId", "0"))]
    fill = fills[int(xf.attrib.get("fillId", "0"))]
    border = borders[int(xf.attrib.get("borderId", "0"))]
    num_id = int(xf.attrib.get("numFmtId", "0"))
    code = num_fmts.get(num_id) or _BUILTIN_NUM_FMTS.get(num_id) or str(num_id)
    align = None
    for child in xf:
        if _local(child.tag) == "alignment":
            wrap = child.attrib.get("wrapText") in {"1", "true", "True"}
            align = (child.attrib.get("horizontal"), wrap)
    return (_font_sig(font), _fill_sig(fill), _border_sig(border), code.replace(" ", ""), align)


def _shared_strings(files: dict[str, bytes]) -> list[str]:
    blob = files.get("xl/sharedStrings.xml")
    if blob is None:
        return []
    found = []
    for si in ET.fromstring(blob):
        if _local(si.tag) != "si":
            continue
        found.append("".join(node.text or "" for node in si.iter() if _local(node.tag) == "t"))
    return found


def _canon_value(raw: str | None) -> tuple:
    if raw is None:
        return ("t", "")
    try:
        number = float(raw)
    except ValueError:
        return ("t", raw)
    if number == int(number) and abs(number) < 10**15:
        return ("n", str(int(number)))
    return ("n", repr(number))


def _sheet_paths(files: dict[str, bytes]) -> dict[str, str]:
    rels = ET.fromstring(files["xl/_rels/workbook.xml.rels"])
    targets = {}
    for rel in rels:
        if _local(rel.tag) != "Relationship":
            continue
        target = rel.attrib["Target"]
        if target.startswith("/"):
            target = target.lstrip("/")
        elif not target.startswith("xl/"):
            target = "xl/" + target
        targets[rel.attrib["Id"]] = target
    root = ET.fromstring(files["xl/workbook.xml"])
    found = {}
    for el in root.iter():
        if _local(el.tag) != "sheet":
            continue
        rid = el.attrib.get(f"{{{_REL_NS}}}id") or el.attrib.get("id")
        found[el.attrib["name"]] = targets[rid]
    return found


def _cells(files: dict[str, bytes], path: str, skip: set[str]) -> dict:
    root = ET.fromstring(files[path])
    strings = _shared_strings(files)
    fonts, fills, borders, xfs, num_fmts = _style_tables(files["xl/styles.xml"])
    found = {}
    for cell in root.iter():
        if _local(cell.tag) != "c":
            continue
        ref = cell.attrib.get("r")
        if ref in skip:
            continue
        formula = value = inline = None
        formula_type = ""
        for child in cell:
            kind = _local(child.tag)
            if kind == "f":
                formula = _text(child).lstrip("=").strip()
                formula_type = child.attrib.get("t") or ""
            elif kind == "v":
                value = _text(child)
            elif kind == "is":
                inline = _text(child)
        if formula is None and not value and not inline:
            continue
        if formula is not None:
            stored = ("f", formula_type, formula)
        elif cell.attrib.get("t") == "s" and value is not None and value.isdigit():
            stored = ("v", _canon_value(strings[int(value)]))
        elif inline is not None:
            stored = ("v", _canon_value(inline))
        else:
            stored = ("v", _canon_value(value))
        style_id = int(cell.attrib.get("s", "0"))
        style = _xf_sig(xfs[style_id], fonts, fills, borders, num_fmts)
        found[ref] = (stored, style)
    return found


def _merges(files: dict[str, bytes], path: str) -> list[str]:
    root = ET.fromstring(files[path])
    return sorted(
        el.attrib.get("ref", "") for el in root.iter() if _local(el.tag) == "mergeCell"
    )


def _validations(files: dict[str, bytes], path: str) -> list[tuple]:
    root = ET.fromstring(files[path])
    found = []
    for el in root.iter():
        if _local(el.tag) != "dataValidation":
            continue
        formula = ""
        for child in el:
            if _local(child.tag) == "formula1":
                formula = _text(child).strip()
        blank = (el.attrib.get("allowBlank") or "").lower() in {"1", "true"}
        sqref = " ".join((el.attrib.get("sqref") or "").split())
        found.append((el.attrib.get("type"), sqref, formula, blank))
    return sorted(found)


def _names_and_states(files: dict[str, bytes]) -> tuple[list[tuple], list[tuple]]:
    root = ET.fromstring(files["xl/workbook.xml"])
    states = []
    names = []
    for el in root.iter():
        if _local(el.tag) == "sheet":
            states.append((el.attrib.get("name"), el.attrib.get("state") or "visible"))
        elif _local(el.tag) == "definedName":
            hidden = (el.attrib.get("hidden") or "").lower() in {"1", "true"}
            names.append((el.attrib.get("name"), hidden, "".join(_text(el).split())))
    return states, sorted(names)


def _charts(files: dict[str, bytes]) -> list[tuple]:
    found = []
    for name in sorted(files):
        if not (name.startswith("xl/charts/") and name.endswith(".xml")):
            continue
        root = ET.fromstring(files[name])
        titles: list[str] = []
        types: list[str] = []
        refs: list[str] = []
        for el in root.iter():
            if _local(el.tag) == "title" and not titles:
                titles = [node.text for node in el.iter() if _local(node.tag) == "t" and node.text]
            if _local(el.tag).endswith("Chart"):
                types.append(_local(el.tag))
            if _local(el.tag) == "f" and (el.text or "").strip():
                refs.append(el.text.strip())
        found.append((tuple(titles), tuple(types), tuple(refs)))
    return found


def _drawings(files: dict[str, bytes]) -> list[tuple]:
    found = []
    for name in sorted(files):
        low = name.lower()
        if not (low.startswith("xl/drawings/") and low.endswith(".xml")):
            continue
        root = ET.fromstring(files[name])
        for anchor in list(root):
            kind = None
            position = []
            for el in anchor.iter():
                local = _local(el.tag)
                if local in {"pic", "graphicFrame", "sp", "cxnSp"} and kind is None:
                    kind = local
                if local in {"col", "row"} and (el.text or "").strip():
                    position.append((local, el.text.strip()))
            found.append((name, _local(anchor.tag), kind, tuple(position)))
    return found


def _media(files: dict[str, bytes]) -> dict[str, bytes]:
    return {name: blob for name, blob in files.items() if name.startswith("xl/media/")}


def package_view(data: bytes, answers: dict[str, set[str]] | None = None) -> dict:
    """Normalized supported-subset view. Answer cells are omitted."""
    answers = answers if answers is not None else _ANSWERS
    files = _files(data)
    states, names = _names_and_states(files)
    sheets = {}
    for sheet_name, path in _sheet_paths(files).items():
        sheets[sheet_name] = {
            "cells": _cells(files, path, answers.get(sheet_name, set())),
            "merges": _merges(files, path),
            "validations": _validations(files, path),
        }
    return {
        "states": states,
        "names": names,
        "sheets": sheets,
        "charts": _charts(files),
        "drawings": _drawings(files),
        "media": _media(files),
    }


def _assert_same_view(before: dict, after: dict) -> None:
    assert before["states"] == after["states"], (before["states"], after["states"])
    assert before["names"] == after["names"], (before["names"], after["names"])
    assert before["charts"] == after["charts"], (before["charts"], after["charts"])
    assert before["drawings"] == after["drawings"], (before["drawings"], after["drawings"])
    assert before["media"] == after["media"]
    assert before["sheets"].keys() == after["sheets"].keys()
    for name in before["sheets"]:
        left, right = before["sheets"][name], after["sheets"][name]
        assert left["merges"] == right["merges"], (name, left["merges"], right["merges"])
        assert left["validations"] == right["validations"], (
            name,
            left["validations"],
            right["validations"],
        )
        assert left["cells"].keys() == right["cells"].keys(), (
            name,
            sorted(set(left["cells"]) ^ set(right["cells"])),
        )
        for ref in left["cells"]:
            assert left["cells"][ref] == right["cells"][ref], (
                name,
                ref,
                left["cells"][ref],
                right["cells"][ref],
            )


def _cell_text(data: bytes, sheet: str, ref: str) -> str:
    files = _files(data)
    path = _sheet_paths(files)[sheet]
    strings = _shared_strings(files)
    root = ET.fromstring(files[path])
    for cell in root.iter():
        if _local(cell.tag) != "c" or cell.attrib.get("r") != ref:
            continue
        for child in cell:
            if _local(child.tag) == "is":
                return _text(child)
            if _local(child.tag) == "v" and cell.attrib.get("t") == "s":
                return strings[int(_text(child))]
            if _local(child.tag) == "v":
                return _text(child)
    raise AssertionError(f"{sheet}!{ref} missing")


def _assert_supported_content(view: dict, *, very_hidden: bool) -> None:
    states = dict(view["states"])
    assert states["Security"] == "visible"
    assert states["HiddenCalc"] == "hidden"
    if very_hidden:
        assert states["VeryHidden"] == "veryHidden"
    else:
        assert "VeryHidden" in states
    assert ("ScoreCell", False, "Security!$E$2") in view["names"]
    assert ("HiddenName", True, "HiddenCalc!$A$1") in view["names"]
    security = view["sheets"]["Security"]
    assert "A1:C1" in security["merges"]
    assert ("list", "B2:B10", '"Yes,No"', True) in security["validations"]
    assert security["cells"]["D2"][0] == ("f", "", "LEN(A2)")
    assert security["cells"]["A1"][1][0][0] == "Calibri"
    assert security["cells"]["A1"][1][0][2] is True  # bold
    assert security["cells"]["E2"][1][3] == "0.00%"
    assert view["media"]
    assert any(item[0] == ("Scores",) and "barChart" in item[1] for item in view["charts"])
    assert view["sheets"]["HiddenCalc"]["cells"]["B1"][0][0] == "f"


def test_openpyxl_fixture_preserves_supported_subset(tmp_path: Path) -> None:
    src = build_supported_workbook(tmp_path, array_formula=True)
    assert unsupported_workbook_features(src) == []
    out = _export(src)
    before, after = package_view(src), package_view(out)
    _assert_supported_content(before, very_hidden=True)
    assert before["sheets"]["Security"]["cells"]["H2"][0] == ("f", "array", "E2:E3")
    _assert_same_view(before, after)
    assert _cell_text(out, "Security", "B2") == "Approved"


def test_image_only_workbook_keeps_the_picture() -> None:
    wb = Workbook()
    wb.active.title = "Security"
    wb.active["A1"] = "Question"
    buf = io.BytesIO()
    wb.save(buf)
    src = _embed_png(buf.getvalue(), _png_bytes(), col=0, row=5)
    out = _export(src)
    _assert_same_view(package_view(src), package_view(out))
    assert _cell_text(out, "Security", "B2") == "Approved"


def test_libreoffice_fixture_preserves_supported_subset() -> None:
    """Checked-in bytes were written by LibreOffice headless, not by openpyxl."""
    src = _LO_FIXTURE.read_bytes()
    app_xml = _files(src)["docProps/app.xml"]
    assert b"LibreOffice/" in app_xml
    assert b"openpyxl" not in src
    assert unsupported_workbook_features(src) == []
    out = _export(src)
    before, after = package_view(src), package_view(out)
    _assert_supported_content(before, very_hidden=False)
    _assert_same_view(before, after)
    assert _cell_text(out, "Security", "B2") == "Approved"


def _minimal_xlsx() -> bytes:
    wb = Workbook()
    wb.active.title = "Security"
    wb.active["A1"] = "Question"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _inject(
    base: bytes,
    extra: dict[str, bytes] | None = None,
    replace: dict[str, bytes] | None = None,
) -> bytes:
    extra = extra or {}
    replace = replace or {}
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            payload = replace.get(info.filename, src.read(info.filename))
            dst.writestr(info.filename, payload)
        for name, payload in extra.items():
            dst.writestr(name, payload)
    return out.getvalue()


def _with_part(name: str, payload: bytes):
    return lambda: _inject(_minimal_xlsx(), {name: payload})


def _with_sheet(snippet: str):
    def build() -> bytes:
        base = _minimal_xlsx()
        with zipfile.ZipFile(io.BytesIO(base)) as zf:
            sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
        sheet = sheet.replace("</worksheet>", snippet + "</worksheet>")
        return _inject(base, replace={"xl/worksheets/sheet1.xml": sheet.encode("utf-8")})

    return build


def _macro_content_type() -> bytes:
    base = _minimal_xlsx()
    with zipfile.ZipFile(io.BytesIO(base)) as zf:
        content = zf.read("[Content_Types].xml").decode("utf-8")
    old = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    content = content.replace(old, "application/vnd.ms-excel.sheet.macroEnabled.12", 1)
    assert "macroEnabled" in content
    return _inject(base, replace={"[Content_Types].xml": content.encode("utf-8")})


_SHAPE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing">
  <xdr:twoCellAnchor><xdr:sp><xdr:nvSpPr/></xdr:sp></xdr:twoCellAnchor>
</xdr:wsDr>
"""
_VML_RECT = b"""<?xml version="1.0" encoding="UTF-8"?>
<xml xmlns:v="urn:schemas-microsoft-com:vml"><v:rect/></xml>
"""
_VML_BUTTON = b"""<?xml version="1.0" encoding="UTF-8"?>
<xml xmlns:v="urn:schemas-microsoft-com:vml" xmlns:x="urn:schemas-microsoft-com:office:excel">
  <v:shape><x:ClientData ObjectType="Button"/></v:shape>
</xml>
"""
_VML_NOTE = b"""<?xml version="1.0" encoding="UTF-8"?>
<xml xmlns:v="urn:schemas-microsoft-com:vml" xmlns:x="urn:schemas-microsoft-com:office:excel">
  <v:shape><x:ClientData ObjectType="Note"/></v:shape>
</xml>
"""

_UNSUPPORTED = [
    ("macros", "vba-project", _with_part("xl/vbaProject.bin", b"synthetic-vba")),
    ("macros", "macro-content-type", _macro_content_type),
    ("shapes", "drawingml-shape", _with_part("xl/drawings/drawing9.xml", _SHAPE_XML)),
    ("shapes", "vml-rect", _with_part("xl/drawings/vmlDrawing9.vml", _VML_RECT)),
    ("shapes", "header-footer-drawing", _with_sheet("<legacyDrawingHF/>")),
    ("form controls", "control-properties", _with_part("xl/ctrlProps/ctrlProp1.xml", b"<x/>")),
    ("form controls", "activex", _with_part("xl/activeX/activeX1.xml", b"<x/>")),
    (
        "form controls",
        "worksheet-controls",
        _with_sheet('<controls><control name="Button1"/></controls>'),
    ),
    ("form controls", "vml-button", _with_part("xl/drawings/vmlDrawing8.vml", _VML_BUTTON)),
    ("pivot tables", "pivot-cache", _with_part("xl/pivotCache/pivotCacheDefinition1.xml", b"<x/>")),
    ("external links", "external-link", _with_part("xl/externalLinks/externalLink1.xml", b"<x/>")),
    ("slicers", "slicer-part", _with_part("xl/slicers/slicer1.xml", b"<x/>")),
    (
        "slicers",
        "slicer-extension",
        _with_sheet('<extLst><ext uri="{A8765BA9-456A-4DAB-B4F3-ACF838C121DE}"/></extLst>'),
    ),
    ("timelines", "timeline", _with_part("xl/timelines/timeline1.xml", b"<x/>")),
    (
        "sparklines",
        "sparkline-extension",
        _with_sheet('<extLst><ext uri="{05C60535-1F16-4FD2-B633-F4F36F0B64E0}"/></extLst>'),
    ),
    ("embedded objects", "ole", _with_part("xl/embeddings/oleObject1.bin", b"synthetic-ole")),
    ("data connections", "connections", _with_part("xl/connections.xml", b"<connections/>")),
    ("data connections", "query-table", _with_part("xl/queryTables/queryTable1.xml", b"<x/>")),
    ("web extensions", "web-extension", _with_part("xl/webextensions/webextension1.xml", b"<x/>")),
    ("custom XML parts", "custom-xml", _with_part("customXml/item1.xml", b"<root/>")),
    (
        "protected ranges",
        "protected-range",
        _with_sheet("<protectedRanges><protectedRange sqref=\"A1:A1\"/></protectedRanges>"),
    ),
    ("custom ribbon", "custom-ribbon", _with_part("customUI/customUI.xml", b"<customUI/>")),
    (
        "threaded comments",
        "threaded-comment",
        _with_part("xl/threadedComments/threadedComment1.xml", b"<x/>"),
    ),
    ("threaded comments", "persons", _with_part("xl/persons.xml", b"<persons/>")),
    ("sheet backgrounds", "sheet-background", _with_sheet("<picture/>")),
    (
        "ignored errors",
        "ignored-errors",
        _with_sheet('<extLst><ext uri="{01252117-D84E-4E92-8308-4BE1C098FCBB}"/></extLst>'),
    ),
]


@pytest.mark.parametrize(
    "label,case_id,build",
    _UNSUPPORTED,
    ids=[item[1] for item in _UNSUPPORTED],
)
def test_unsupported_structure_is_rejected(label: str, case_id: str, build) -> None:
    data = build()
    with pytest.raises(UnsupportedWorkbookStructure) as caught:
        create_export_from_questionnaire(data, [], {})
    assert caught.value.features == (label,)
    message = str(caught.value)
    assert label in message
    assert "<" not in message
    assert "xl/" not in message
    assert case_id


def test_unsupported_workbook_is_terminal_bad_input() -> None:
    from app.core.job_errors import BAD_INPUT, classify, is_retryable_code, safe_error_message

    exc = UnsupportedWorkbookStructure(["macros", "shapes"])
    assert classify(exc) == BAD_INPUT
    assert is_retryable_code(classify(exc)) is False
    assert safe_error_message(exc) == str(exc)
    assert "macros, shapes" in str(exc)


def test_comment_notes_and_caches_are_not_rejected() -> None:
    noted = _inject(_minimal_xlsx(), {"xl/drawings/vmlDrawing1.vml": _VML_NOTE})
    cached = _inject(
        _minimal_xlsx(),
        {
            "xl/calcChain.xml": b"<calcChain/>",
            "xl/printerSettings/printerSettings1.bin": b"synthetic-printer",
        },
    )
    assert unsupported_workbook_features(noted) == []
    assert unsupported_workbook_features(cached) == []
    create_export_from_questionnaire(noted, [], {})
    create_export_from_questionnaire(cached, [], {})


class _Query:
    def __init__(self, value):
        self._value = value

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value

    def all(self):
        if self._value is None:
            return []
        if isinstance(self._value, list):
            return list(self._value)
        return [self._value]


class _Session:
    def __init__(self, rows: dict):
        self._rows = rows

    def query(self, model):
        return _Query(self._rows.get(model))

    def add(self, obj) -> None:
        return None

    def refresh(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = 1

    def rollback(self) -> None:
        return None


class _Store:
    bucket_raw = "raw"
    bucket_exports = "exports"

    def __init__(self, blob: bytes):
        self.blob = blob
        self.uploads: list[tuple[str, bytes]] = []

    def download(self, bucket: str, key: str) -> bytes:
        return self.blob

    def upload(self, bucket: str, key: str, body, content_type: str | None = None) -> str:
        data = body.read() if hasattr(body, "read") else body
        self.uploads.append((key, bytes(data)))
        return key


def _run_export(monkeypatch, blob: bytes, *, filename: str = "questionnaire.xlsx"):
    from app import worker
    from app.models import Answer, ExportRecord, Question, Questionnaire

    store = _Store(blob)
    monkeypatch.setattr(worker, "StorageClient", lambda: store)
    monkeypatch.setattr(worker, "_record_usage_once", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.services.storage_reconcile.commit_or_discard_object",
        lambda *args, **kwargs: None,
    )
    questionnaire = SimpleNamespace(
        id=3, workspace_id=1, storage_key="raw/questionnaire.xlsx", filename=filename
    )
    question = SimpleNamespace(
        id=1,
        text="Do you encrypt data at rest?",
        source_location=json.dumps({"sheet": "Security", "row": 2, "col": 1}),
    )
    answer = SimpleNamespace(question_id=1, text="Approved", status="approved")
    session = _Session(
        {
            Questionnaire: questionnaire,
            ExportRecord: None,
            Question: [question],
            Answer: [answer],
        }
    )
    job = SimpleNamespace(id=7, workspace_id=1, lease_owner=None, result=None, attempt=1)
    worker.run_export(job, session, {"questionnaire_id": 3, "workspace_id": 1, "format": "xlsx"})
    return job, store


@pytest.mark.parametrize(
    "label,case_id,build",
    _UNSUPPORTED,
    ids=[item[1] for item in _UNSUPPORTED],
)
def test_worker_unsupported_structure_fails_without_docx_fallback(
    monkeypatch, label: str, case_id: str, build
) -> None:
    with pytest.raises(UnsupportedWorkbookStructure) as caught:
        _run_export(monkeypatch, build())
    assert caught.value.features == (label,)
    assert case_id


def test_worker_keeps_docx_fallback_for_corrupt_workbook(monkeypatch) -> None:
    job, store = _run_export(monkeypatch, b"this is not a workbook")
    assert job.result
    assert len(store.uploads) == 1
    key, body = store.uploads[0]
    assert key.endswith(".docx")
    assert body.startswith(b"PK")
    assert b"word/" in body


def test_worker_keeps_docx_fallback_for_unexpected_writer_errors(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("synthetic writer failure")

    monkeypatch.setattr("app.services.xlsx_writer.create_export_from_questionnaire", boom)
    job, store = _run_export(monkeypatch, _minimal_xlsx())
    assert job.result
    key, body = store.uploads[0]
    assert key.endswith("_answers_fallback.docx") or key.endswith(".docx")
    assert b"word/" in body


def test_worker_exports_supported_workbook_as_xlsx(monkeypatch, tmp_path: Path) -> None:
    job, store = _run_export(monkeypatch, build_supported_workbook(tmp_path))
    assert job.result
    key, body = store.uploads[0]
    assert key.endswith(".xlsx")
    assert b"word/" not in body
    assert _cell_text(body, "Security", "B2") == "Approved"
