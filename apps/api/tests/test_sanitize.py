"""Санитизация недоверенного ввода: имена файлов и формулы в выгрузках.

Закрывает два класса находок аудита §11:
  * инъекция HTTP-заголовков через имя файла из multipart → response splitting,
    подмена Content-Type, reflected XSS в origin API;
  * формульные инъекции в CSV/XLSX (Excel вычисляет ячейку даже в кавычках).

Тесты на чистые функции — без БД и без фикстур.
"""
from app.core.sanitize import content_disposition, safe_filename, spreadsheet_cell


class TestSafeFilename:
    def test_strips_path_traversal(self):
        assert safe_filename("../../etc/passwd") == "passwd"
        assert safe_filename(r"..\..\windows\system32\cmd.exe") == "cmd.exe"

    def test_strips_null_and_control_chars(self):
        # NUL обрезает путь в некоторых обработчиках ОС
        assert "\x00" not in safe_filename("photo\x00.png")
        assert safe_filename("photo.png") == "photo.png"

    def test_replaces_newlines_that_split_headers(self):
        # Ровно тот вектор, из-за которого был написан модуль
        out = safe_filename("a\nContent-Type: text/html\n\n<script>x</script>.pdf")
        assert "\n" not in out
        assert "\r" not in out

    def test_empty_and_dot_only_fall_back_to_default(self):
        assert safe_filename("") == "file"
        assert safe_filename(None) == "file"
        assert safe_filename("..") == "file"
        assert safe_filename("...", default="doc.pdf") == "doc.pdf"

    def test_truncates_but_keeps_extension(self):
        out = safe_filename("x" * 500 + ".pdf")
        assert len(out) <= 200
        assert out.endswith(".pdf")


class TestContentDisposition:
    def test_header_cannot_be_split(self):
        """Главная гарантия: в значении заголовка не может оказаться перевод строки."""
        hostile = "a\r\nContent-Type: text/html\r\n\r\n<script>alert(1)</script>.pdf"
        header = content_disposition(hostile)
        assert "\r" not in header
        assert "\n" not in header
        # единственные переводы строк — те, что мы сами ставили как разделители параметров
        assert header.count("\n") == 0

    def test_ascii_fallback_has_no_quotes_or_specials(self):
        header = content_disposition('we"ird\\name.pdf')
        # значение после filename="..." не содержит кавычек и обратных слэшей
        fallback = header.split('filename="', 1)[1].split('"', 1)[0]
        assert '"' not in fallback
        assert "\\" not in fallback

    def test_cyrillic_goes_to_extended_parameter(self):
        header = content_disposition("Счёт №5.pdf")
        assert "filename*=UTF-8''" in header
        assert "%D0%A1" in header or "%D0" in header  # «С» в percent-encoding

    def test_empty_falls_back_to_default(self):
        assert 'filename="document.pdf"' in content_disposition("")
        assert 'filename="invoice.pdf"' in content_disposition(None, default="invoice.pdf")


class TestSpreadsheetCell:
    def test_neutralizes_formula_prefixes(self):
        for payload in (
            "=1+1",
            "+1+1",
            "@SUM(A1)",
            "\t=cmd|'/c calc'!A1",
            "\r=cmd",
            "=HYPERLINK(\"http://evil\",\"click\")",
        ):
            out = spreadsheet_cell(payload)
            assert isinstance(out, str) and out.startswith("'"), payload

    def test_dangerous_minus_neutralized(self):
        assert spreadsheet_cell("-cmd|'/c calc.exe'!A1").startswith("'")
        assert spreadsheet_cell("-2+3+cmd").startswith("'")

    def test_negative_numbers_stay_numeric(self):
        """Скидки в прайсе — отрицательные числа; ломать их нельзя."""
        assert spreadsheet_cell("-12.50") == "-12.50"
        assert spreadsheet_cell("-0.5%") == "-0.5%"
        assert spreadsheet_cell("-1234") == "-1234"

    def test_ordinary_values_untouched(self):
        assert spreadsheet_cell("Арматура Ø20") == "Арматура Ø20"
        assert spreadsheet_cell("") == ""
        assert spreadsheet_cell(None) is None
        assert spreadsheet_cell(42) == 42
        assert spreadsheet_cell(3.14) == 3.14