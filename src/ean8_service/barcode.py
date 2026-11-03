from io import BytesIO

from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

PAYLOAD_LENGTH = 7
CODE_LENGTH = 8
MAX_CODES = 100
MIN_CODES = 1
LABELS_PER_PAGE = 10
CHECK_WEIGHTS = (3, 1)


def normalize(value):
    if not isinstance(value, str) or not value.isascii():
        raise ValueError("Codes must be ASCII digit strings")
    if not value.isdigit() or len(value) not in (PAYLOAD_LENGTH, CODE_LENGTH):
        raise ValueError("Each code must contain 7 or 8 digits")
    payload = value[:PAYLOAD_LENGTH]
    total = sum(int(digit) * CHECK_WEIGHTS[index % len(CHECK_WEIGHTS)]
                for index, digit in enumerate(payload))
    code = payload + str((-total) % 10)
    if len(value) == CODE_LENGTH and value != code:
        raise ValueError("Invalid EAN-8 check digit: " + value)
    return code


def validate(data):
    if not isinstance(data, dict) or set(data) != {"codes"}:
        raise ValueError('Expected an object with the single key "codes"')
    values = data["codes"]
    if (not isinstance(values, list)
            or not MIN_CODES <= len(values) <= MAX_CODES):
        raise ValueError("codes must be a list of 1..100 items")
    return [normalize(value) for value in values]


def generate(data):
    codes = validate(data)
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=A4, invariant=True)
    canvas.setTitle("EAN-8 barcodes")
    for index, code in enumerate(codes):
        row = index % LABELS_PER_PAGE
        if index and not row:
            canvas.showPage()
        drawing = createBarcodeDrawing(
            "EAN8", value=code, barWidth=0.935, barHeight=44,
            humanReadable=True, quiet=True,
        )
        renderPDF.draw(drawing, canvas, 50, A4[1] - 90 - row * 74)
    canvas.save()
    return stream.getvalue()
