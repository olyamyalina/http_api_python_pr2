# Вариант 15. Генерация EAN-8 в PDF

Тема курсовой: «Веб-приложение с HTTP API для асинхронной генерации
штрих-кодов EAN-8 в формате PDF». Python 3.11+.

## Этап 1

Установка: `python -m pip install -e ".[test]"`.
CLI принимает путь к UTF-8 JSON-файлу с единственным полем `codes`:
списком от 1 до 100 строк. Для семи цифр вычисляется контрольная цифра,
для восьми проверяется существующая. Ведущие нули сохраняются.
Неверные данные приводят к коду завершения 2 и сообщению в stderr.
PDF записывается в stdout, по 10 этикеток на странице A4.

В `cmd.exe` (из PowerShell вызывайте через `cmd /c`):

```bat
ean8-cli examples/01_single.json > single.pdf
ean8-cli examples/02_complete.json > complete.pdf
ean8-cli examples/03_leading_zero.json > leading-zero.pdf
ean8-cli examples/04_batch.json > batch.pdf
ean8-cli examples/05_multipage.json > multipage.pdf
```

Для старых версий PowerShell перенаправление бинарного stdout через `>`
может портить PDF, поэтому используйте `cmd.exe` или `subprocess`.
Тестирование: `python -m pytest tests/test_barcode.py`.
Генерация изображения штрих-кода не регистрирует GTIN в GS1.

Контрольная цифра:
`(10 - (3*d1 + d2 + 3*d3 + d4 + 3*d5 + d6 + 3*d7) % 10) % 10`.
Источники: [GS1](https://www.gs1.ch/en/barcodes-standards/check-digit-calculator),
[RFC 7617](https://www.rfc-editor.org/rfc/rfc7617.html).
