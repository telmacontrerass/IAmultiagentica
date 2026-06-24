from unittest.mock import patch

from ci2lab.harness.tools.filesystem_parts.documents import pdf_needs_vision
from ci2lab.harness.vision import (
    count_vision_images_in_messages,
    extract_image_paths,
    strip_vision_from_messages,
)


def test_count_vision_images_in_messages():
    messages = [
        {"role": "user", "content": "plain"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "see pages"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,def"}},
            ],
        },
    ]
    assert count_vision_images_in_messages(messages) == 2


def test_strip_vision_from_messages_keeps_text():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Question about the pdf"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        },
    ]
    stripped = strip_vision_from_messages(messages)
    assert stripped[0]["content"] == "Question about the pdf"
    assert count_vision_images_in_messages(stripped) == 0


def test_extract_image_paths_skips_text_pdf(tmp_path):
    text_pdf = tmp_path / "report.pdf"
    text_pdf.write_bytes(b"%PDF-1.4")

    with patch(
        "ci2lab.harness.vision.pdf_needs_vision",
        return_value=False,
    ):
        cleaned, paths = extract_image_paths(
            "Summarize report.pdf please",
            str(tmp_path),
        )

    assert paths == []
    assert "report.pdf" in cleaned


def test_extract_image_paths_includes_scanned_pdf(tmp_path):
    scanned_pdf = tmp_path / "scan.pdf"
    scanned_pdf.write_bytes(b"%PDF-1.4")

    with patch(
        "ci2lab.harness.vision.pdf_needs_vision",
        return_value=True,
    ):
        cleaned, paths = extract_image_paths(
            "What is in scan.pdf?",
            str(tmp_path),
        )

    assert len(paths) == 1
    assert paths[0].endswith("scan.pdf")
    assert "scan.pdf" not in cleaned


def test_pdf_needs_vision_for_scanned_handwritten_pdf():
    pdf = r"C:\Users\clara\Master\IAmultiagentica\P1_T1_IE.pdf"
    from pathlib import Path

    if Path(pdf).is_file():
        assert pdf_needs_vision(Path(pdf)) is True
