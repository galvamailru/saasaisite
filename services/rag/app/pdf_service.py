"""Конвертация PDF в markdown через docling."""
from pathlib import Path

from docling.document_converter import DocumentConverter


def pdf_to_markdown(pdf_path: Path) -> str:
    """Конвертирует PDF файл в markdown."""
    converter = DocumentConverter()
    result = converter.convert(str(pdf_path))
    return result.document.export_to_markdown()
