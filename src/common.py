# SPDX-License-Identifier: GPL-3.0-only WITH MIT
# SPDX-FileCopyrightText: 2024 arzamas-16 <https://github.com/arzamas-16>

"""Common utility functions."""

import logging
import math
from typing import List, get_type_hints

from src.error import AppotechError


def irange(a, b=None, c=1):
    """Inclusive range"""
    if b is None:
        return range(a + 1)
    return range(a, b + 1, c)


def split_in_chunks(values, chunk_len: int):
    """Iterate tuples with n elements in each"""
    for i in range(0, len(values), chunk_len):
        yield tuple(values[i : i + chunk_len])


def find_all(where, what):
    """Yield positions of all occurrences of the specified pattern."""
    pos = -1
    while True:
        pos = where.find(what, pos + 1)
        if pos == -1:
            break
        yield pos


def as_hex(obj, size: int = 4) -> str:
    """Represent an object as hex string"""
    if isinstance(obj, list) or isinstance(obj, tuple):
        return ", ".join(as_hex(i) for i in obj)
    elif isinstance(obj, bytes) or isinstance(obj, bytearray):
        return obj.hex().upper()
    elif isinstance(obj, int):
        fmt = "{:0" + str(size * 2) + "X}"
        return fmt.format(obj)
    else:
        return "?" * (size * 2)


def bit(n: int) -> int:
    """Return an integer with the nth bit set."""
    return 1 << n


def align_bytes(src: bytes, align_to: int, pad: int = 0x00) -> bytes:
    """Align the given bytes to a specified alignment.

    Args:
        src (bytes): The input bytes to be aligned.
        align_to (int): The alignment size.
        pad (int, optional): The padding byte value (default is 0x00).

    Returns:
        bytes: The aligned bytes.
    """
    src_sz: int = len(src)
    new_sz: int = math.ceil(src_sz / align_to) * align_to

    if src_sz == new_sz:
        return src
    return src.ljust(new_sz, (pad & 0xFF).to_bytes(1, byteorder="little"))


def indices_atoi_list(src: List[str], max_val: int) -> List[int]:
    """Convert a list of strings to list of integers sorted in reverse order.
    Return `None` if any value is invalid OR is greater than `max`"""
    result: List[int] = []
    i: int = 0
    for s in src:
        try:
            i = int(s)
        except ValueError:
            logging.error(f"Invalid index {s}")
            return None
        if i > max_val:
            logging.error(f"Index is too big, {i} > {max_val}")
            return None
        result.append(i)
    result.sort(reverse=True)
    return result


def set_variable(
    obj,
    var_name: str,
    var_value: str,
    val_range: range = None,
    len_range: range = None,
):
    """Convert the value type from `str` to a necessary one using type hints,
    then check if the value meets specific criteria and apply it."""
    type_hints = get_type_hints(obj)
    var_type: type = type_hints.get(var_name)

    if var_type == int:
        value: int = int(var_value)
        if val_range and value not in val_range:
            raise AppotechError(
                f"Cannot assign {var_name} to {value} because "
                f"it's not in the accepted range: {val_range}"
            )
        setattr(obj, var_name, value)
    elif var_type == bytes or var_type == bytearray:
        # Allow slight variance in what HEX we can take as input
        var_value = var_value.replace(":", "").replace(" ", "").lower()
        value = (bytes if var_type == bytes else bytearray).fromhex(var_value)
        if len_range and len(value) not in len_range:
            raise AppotechError(
                f"Cannot assign {var_name} to {value} because "
                f"it's not in the accepted range: {len_range}"
            )
        setattr(obj, var_name, value)
    elif var_type == str:
        if len_range and len(var_value) not in len_range:
            raise AppotechError(
                f"Cannot assign {var_name} to \"{value}\" because "
                f"it's not in the accepted range: {len_range}"
            )  # fmt: skip
        setattr(obj, var_name, var_value)
    elif var_type == bool:
        var_value = var_value.lower()
        if var_value in ("1", "true"):
            setattr(obj, var_name, True)
        elif var_value in ("0", "false"):
            setattr(obj, var_name, False)
        else:
            raise AppotechError(
                f"Cannot assign {var_name} to \"{value}\" because "
                f"only (1, true, 0, false) are supported for booleans"
            )  # fmt: skip
    else:
        raise AppotechError(f"Unknown object type: {var_type}, cannot proceed")


def write_and_check(path: str, data: bytes) -> bool:
    """Write `data` to `file` and check if everything has been written.
    Return true if all bytes have been written successfully."""
    bytes_written: int = 0
    bytes_expected: int = len(data)
    with open(path, "wb") as fos:
        bytes_written: int = fos.write(data)
    if bytes_written == bytes_expected:
        logging.info(f"Wrote {bytes_written} bytes to {path}")
    else:
        logging.error(
            f"Partial write to {path}, "
            f"expected {bytes_expected} "
            f"but wrote {bytes_written}"
        )
        return False
    return True
