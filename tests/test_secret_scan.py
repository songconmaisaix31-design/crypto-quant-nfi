from scripts.ops_common import redact_text


def test_redact_text_masks_secret_like_values():
    text = "secret=abc1234567890TOKEN password: hunterhunter1234 sk-abc123456789"
    redacted = redact_text(text)
    assert "abc1234567890TOKEN" not in redacted
    assert "hunterhunter1234" not in redacted
    assert "sk-abc123456789" not in redacted

