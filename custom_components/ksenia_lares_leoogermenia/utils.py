"""Utilities."""


def calculate_crc_value(input_string):
    """Calcola il valore CRC a 16 bit da una stringa di caratteri.

    :param input_string: Stringa in input
    :return: il valore CRC a 16 bit, nel formato "0x0000"
    """
    if not getattr(calculate_crc_value, "table", None):
        poly = 0x1021
        table = []
        for i in range(256):
            c = i << 8
            for _ in range(8):
                if c & 0x8000:
                    c = (c << 1) ^ poly
                else:
                    c = c << 1
                c &= 0xFFFF
            table.append(c)
        calculate_crc_value.table = table

    i = input_string[: input_string.rfind('"CRC_16"') + len('"CRC_16"')]
    data_bytes = i.encode("utf-8")

    r = 0xFFFF
    table = calculate_crc_value.table

    for byte in data_bytes:
        pop_index = (r >> 8) & 0xFF

        r = ((r << 8) & 0xFFFF) ^ table[pop_index] ^ byte

    return f"0x{r:04x}"
