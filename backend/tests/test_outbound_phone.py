import pytest

from app.config import Settings
from app.services.outbound_call import validate_e164


@pytest.mark.parametrize("raw,expected", [
    ("+15551234567", "+15551234567"),
    ("(555) 123-4567", "+15551234567"),
    ("555.123.4567", "+15551234567"),
    ("1 555 123 4567", "+15551234567"),
    ("+44 20 7946 0958", "+442079460958"),
    ("0044 20 7946 0958", "+442079460958"),
])
def test_normalizes_to_e164(raw, expected):
    assert validate_e164(raw) == expected


@pytest.mark.parametrize("raw", ["", "12345", "0000000000", "+0123456789", "555-1234"])
def test_rejects_bad_numbers(raw):
    with pytest.raises(ValueError):
        validate_e164(raw)


def test_livekit_http_url_for_server_api():
    s = Settings(livekit_url="wss://example.livekit.cloud")
    assert s.livekit_http_url == "https://example.livekit.cloud"
    assert Settings(livekit_url="example.livekit.cloud").livekit_http_url == "https://example.livekit.cloud"
