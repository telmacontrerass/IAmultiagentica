from ci2lab.harness.context import estimate_tokens, trim_messages


def test_trim_keeps_system_and_recent():
    messages = [{"role": "system", "content": "sys"}]
    for i in range(20):
        messages.append({"role": "user", "content": f"msg {i} " + "x" * 200})
        messages.append({"role": "assistant", "content": f"reply {i} " + "y" * 200})

    trimmed = trim_messages(messages, max_tokens=800)
    assert trimmed[0]["role"] == "system"
    assert len(trimmed) < len(messages)
    assert trimmed[-1]["role"] in ("user", "assistant")


def test_estimate_tokens_positive():
    msgs = [{"role": "user", "content": "hola mundo"}]
    assert estimate_tokens(msgs) >= 1
