"""CRC calculation for Ksenia Lares WebSocket protocol.

Credit to @gvisconti1983 for these functions.
"""


def _utf8_bytes(string):
    """Convert string to UTF-8 byte array.

    Handles multi-byte Unicode characters and surrogate pairs.

    Args:
        string: Input string to convert

    Returns:
        List of integers representing UTF-8 bytes
    """
    bytes_array = []
    index = 0

    while index < len(string):
        char_code = ord(string[index])

        if char_code < 128:
            # Single-byte character (ASCII)
            bytes_array.append(char_code)
        elif char_code < 2048:
            # Two-byte character
            bytes_array.append(192 | char_code >> 6)
            bytes_array.append(128 | 63 & char_code)
        elif char_code < 55296 or char_code >= 57344:
            # Three-byte character
            bytes_array.append(224 | char_code >> 12)
            bytes_array.append(128 | char_code >> 6 & 63)
            bytes_array.append(128 | 63 & char_code)
        else:
            # Four-byte character (surrogate pair)
            index += 1
            next_char = ord(string[index])
            char_code = 65536 + ((1023 & char_code) << 10 | 1023 & next_char)
            bytes_array.append(240 | char_code >> 18)
            bytes_array.append(128 | char_code >> 12 & 63)
            bytes_array.append(128 | char_code >> 6 & 63)
            bytes_array.append(128 | 63 & char_code)

        index += 1

    return bytes_array


def CRC(message):
    """Calculate 16-bit CRC for Ksenia Lares protocol.

    Computes CRC-16 checksum up to the CRC_16 field position
    using the polynomial 0x1021 (x^16 + x^12 + x^5 + 1).

    Args:
        message: JSON message string containing "CRC_16" field

    Returns:
        CRC value as hexadecimal string (e.g., "0x1A2B")
    """
    # Convert to UTF-8 bytes
    byte_array = _utf8_bytes(message)

    # Find CRC field position (calculate CRC up to this point)
    crc_position = message.rfind('"CRC_16"') + len('"CRC_16"')
    crc_position += len(byte_array) - len(message)

    # CRC-16 calculation
    crc_value = 0xFFFF  # Initial value

    for byte_index in range(crc_position):
        bit_mask = 0x80
        byte = byte_array[byte_index]

        while bit_mask:
            # Check if MSB is set
            high_bit = bool(crc_value & 0x8000)

            # Shift CRC left and add byte bit
            crc_value = (crc_value << 1) & 0xFFFF
            if byte & bit_mask:
                crc_value += 1

            # XOR with polynomial if high bit was set
            if high_bit:
                crc_value ^= 0x1021

            bit_mask >>= 1

    return f"0x{crc_value:04x}"


# Legacy function name for backward compatibility
u = _utf8_bytes


"""
Adds a CRC_16 checksum to a json string
"""


def addCRC(json_string):
    return (
        json_string[: json_string.rfind('"CRC_16"') + len('"CRC_16":"')] + CRC(json_string) + '"}'
    )
