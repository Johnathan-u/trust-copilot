"""Deterministic minimal text-PDF writer for synthetic fixtures and mock documents.

Pure Python, no third-party dependency (TC-01-003a). It replaces the PyMuPDF
writer previously used by ``scripts/generate_mock_docs.py`` and builds the
locator corpus used by ``tests/test_pdf_text_locator_corpus.py``.

Not used on any request path. Only base-14 Helvetica with WinAnsiEncoding is
supported, which covers Latin-1 text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PAGE_W, PAGE_H = 595, 842  # A4 points


@dataclass
class TextItem:
    x: float
    y: float  # baseline, measured from the TOP of the page (converted on write)
    text: str
    size: float = 11


@dataclass
class Page:
    texts: list[TextItem] = field(default_factory=list)
    # Stroked line segments (x1, y1, x2, y2), top-origin, e.g. table grid lines.
    lines: list[tuple[float, float, float, float]] = field(default_factory=list)
    # Draw an 8x8 grayscale raster image at (x, y, w, h), top-origin; no text layer.
    image: tuple[float, float, float, float] | None = None
    # Extra content-stream operators appended verbatim (font /F1 is available), e.g. one
    # BT block that positions several table cells with Td moves or TJ kerning (TC-01-003b).
    raw: bytes = b""


def _esc(s: str) -> bytes:
    raw = s.encode("cp1252")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _content(page: Page) -> bytes:
    out: list[bytes] = []
    for x1, y1, x2, y2 in page.lines:
        out.append(f"{x1:.2f} {PAGE_H - y1:.2f} m {x2:.2f} {PAGE_H - y2:.2f} l S".encode())
    if page.image:
        x, y, w, h = page.image
        out.append(f"q {w:.2f} 0 0 {h:.2f} {x:.2f} {PAGE_H - y - h:.2f} cm /Im1 Do Q".encode())
    for t in page.texts:
        out.append(
            b"BT /F1 "
            + f"{t.size:g}".encode()
            + b" Tf "
            + f"{t.x:.2f} {PAGE_H - t.y:.2f}".encode()
            + b" Td ("
            + _esc(t.text)
            + b") Tj ET"
        )
    if page.raw:
        out.append(page.raw)
    return b"\n".join(out)


def build_pdf(pages: list[Page]) -> bytes:
    """Return the bytes of a PDF with one page per ``Page`` (may be empty pages)."""
    objs: list[bytes] = []  # objs[i] is object number i + 1

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    catalog = add(b"")  # placeholder, filled in later
    pages_obj = add(b"")
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    img_data = bytes((i * 37) % 256 for i in range(64))
    image = add(
        b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Length "
        + str(len(img_data)).encode()
        + b" >>\nstream\n"
        + img_data
        + b"\nendstream"
    )
    kids = []
    for p in pages:
        data = _content(p)
        content = add(
            b"<< /Length " + str(len(data)).encode() + b" >>\nstream\n" + data + b"\nendstream"
        )
        res = b"<< /Font << /F1 " + f"{font} 0 R".encode() + b" >>"
        if p.image:
            res += b" /XObject << /Im1 " + f"{image} 0 R".encode() + b" >>"
        res += b" >>"
        kids.append(
            add(
                b"<< /Type /Page /Parent "
                + f"{pages_obj} 0 R".encode()
                + f" /MediaBox [0 0 {PAGE_W} {PAGE_H}]".encode()
                + b" /Resources "
                + res
                + b" /Contents "
                + f"{content} 0 R".encode()
                + b" >>"
            )
        )
    objs[catalog - 1] = b"<< /Type /Catalog /Pages " + f"{pages_obj} 0 R".encode() + b" >>"
    objs[pages_obj - 1] = (
        b"<< /Type /Pages /Kids ["
        + b" ".join(f"{k} 0 R".encode() for k in kids)
        + b"] /Count "
        + str(len(kids)).encode()
        + b" >>"
    )

    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(buf))
        buf += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(buf)
    buf += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        buf += f"{off:010d} 00000 n \n".encode()
    buf += (
        f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(buf)


def text_block(
    x: float, y: float, lines: list[str], size: float = 11, leading: float = 15
) -> list[TextItem]:
    """Lay out ``lines`` top-down starting at baseline ``y``."""
    return [TextItem(x, y + i * leading, s, size) for i, s in enumerate(lines)]


def bt_row(y: float, cells: list[tuple[float, str]], size: float = 11) -> bytes:
    """One BT block placing ``(x, text)`` cells on baseline ``y`` with relative Td moves.

    Mirrors generators that write a whole table row in one text object (TC-01-003b).
    """
    out = [b"BT /F1 " + f"{size:g}".encode() + b" Tf"]
    px, py = 0.0, 0.0
    for x, text in cells:
        ty = PAGE_H - y
        out.append(f"{x - px:.2f} {ty - py:.2f} Td (".encode() + _esc(text) + b") Tj")
        px, py = x, ty
    out.append(b"ET")
    return b" ".join(out)


def tj_row(x: float, y: float, parts: list[str | float], size: float = 11) -> bytes:
    """One TJ array at ``(x, y)``: strings plus kerning numbers (thousandths of an em)."""
    items = [b"(" + _esc(p) + b")" if isinstance(p, str) else f"{p:g}".encode() for p in parts]
    return (
        b"BT /F1 "
        + f"{size:g}".encode()
        + b" Tf "
        + f"{x:.2f} {PAGE_H - y:.2f}".encode()
        + b" Td ["
        + b" ".join(items)
        + b"] TJ ET"
    )
