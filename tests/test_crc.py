"""Tests for the CRC-16 checksum implementation, including the UTF-8 byte
encoding helper's multi-byte branches (2-byte, 3-byte, and 4-byte/surrogate
pair characters) that test_addon_core.py's single ASCII-only test doesn't
exercise.
"""

from custom_components.ksenia_lares.crc import CRC, _utf8_bytes, addCRC


def test_utf8_bytes_ascii_single_byte():
    assert _utf8_bytes("A") == [65]


def test_utf8_bytes_two_byte_character():
    # 'è' (U+00E8) requires a 2-byte UTF-8 encoding
    result = _utf8_bytes("è")

    assert result == list("è".encode("utf-8"))


def test_utf8_bytes_three_byte_character():
    # '€' (U+20AC) requires a 3-byte UTF-8 encoding
    result = _utf8_bytes("€")

    assert result == list("€".encode("utf-8"))


def test_utf8_bytes_four_byte_surrogate_pair_character():
    # '😀' (U+1F600) is outside the BMP and requires a 4-byte encoding
    result = _utf8_bytes("😀")

    assert result == list("😀".encode("utf-8"))


def test_utf8_bytes_mixed_string_matches_native_encoding():
    text = "Ksenia è così 😀"

    assert _utf8_bytes(text) == list(text.encode("utf-8"))


def test_crc_is_deterministic_for_same_input():
    message = '{"CMD":"TEST","CRC_16":"0x0000"}'

    assert CRC(message) == CRC(message)


def test_crc_differs_for_different_payloads():
    msg1 = '{"CMD":"TEST","PAYLOAD":{"A":1},"CRC_16":"0x0000"}'
    msg2 = '{"CMD":"TEST","PAYLOAD":{"A":2},"CRC_16":"0x0000"}'

    assert CRC(msg1) != CRC(msg2)


def test_crc_returns_hex_format():
    result = CRC('{"CRC_16":"0x0000"}')

    assert result.startswith("0x")
    assert len(result) == 6  # "0x" + 4 hex digits


def test_add_crc_replaces_placeholder_with_real_checksum():
    msg = '{"test":"message","CRC_16":"0x0000"}'

    result = addCRC(msg)

    assert result.endswith('"}')
    assert '"CRC_16":"0x0000"' not in result


def test_add_crc_handles_unicode_payload():
    msg = '{"DES":"Linea cucina è così","CRC_16":"0x0000"}'

    result = addCRC(msg)

    assert "0x0000" not in result
