from ci2lab.harness.vision import (
    count_vision_images_in_messages,
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
