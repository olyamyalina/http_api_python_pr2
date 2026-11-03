import pymupdf
import pytest

from ean8_service.barcode import generate, normalize, validate

EXPECTED_PAGE_COUNT = 2


@pytest.mark.parametrize("value,expected", [
    ("1234567", "12345670"), ("96385074", "96385074"),
    ("0000001", "00000017"), ("0123456", "01234565"),
])
def test_check_digits(value, expected):
    assert normalize(value) == expected


@pytest.mark.parametrize("value", [
    "12345671", "123", "abcdefgh", "１２３４５６７", 1234567,
])
def test_invalid_codes(value):
    with pytest.raises(ValueError):
        normalize(value)


@pytest.mark.parametrize("data", [{}, [], {"codes": []}, {"codes": "123"}])
def test_invalid_input(data):
    with pytest.raises(ValueError):
        validate(data)


def test_multipage_pdf():
    pdf = generate({"codes": ["1234567"] * 12})
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        assert len(document) == EXPECTED_PAGE_COUNT
        first_page = document[0]
        assert "1234" in first_page.get_text()
