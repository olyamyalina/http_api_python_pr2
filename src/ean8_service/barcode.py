"""Validate EAN-8 data and render vector barcodes as a PDF."""

from io import BytesIO

from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

PAYLOAD_LENGTH = 7
CODE_LENGTH = 8
MAX_CODES = 100
LABELS_PER_PAGE = 10


def normalize(value):
    """Append or verify the GS1 modulo-10 check digit."""
    if not isinstance(value, str) or not value.isascii():
        raise ValueError("Codes must be ASCII digit strings")
    if not value.isdigit() or len(value) not in (7, 8):
        raise ValueError("Each code must contain 7 or 8 digits")
    payload = value[:PAYLOAD_LENGTH]
    total = sum(int(d) * (3 if i % 2 == 0 else 1)
                for i, d in enumerate(payload))
    code = payload + str((-total) % 10)
    if len(value) == CODE_LENGTH and value != code:
        raise ValueError("Invalid EAN-8 check digit: " + value)
    return code


def validate(data):
    """Return normalized codes from a JSON object."""
    if not isinstance(data, dict) or set(data) != {"codes"}:
        raise ValueError('Expected an object with the single key "codes"')
    values = data["codes"]
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_CODES:
        raise ValueError("codes must be a list of 1..100 items")
    return [normalize(value) for value in values]


def generate(data):
    """Generate A4 PDF bytes with up to ten EAN-8 labels per page."""
    codes = validate(data)
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=A4, invariant=True)
    canvas.setTitle("EAN-8 barcodes")
    for index, code in enumerate(codes):
        row = index % LABELS_PER_PAGE
        if index and row == 0:
            canvas.showPage()
        drawing = createBarcodeDrawing(
            "EAN8", value=code, barWidth=0.935, barHeight=44,
            humanReadable=True, quiet=True,
        )
        renderPDF.draw(drawing, canvas, 50, A4[1] - 90 - row * 74)
    canvas.save()
    return stream.getvalue()
