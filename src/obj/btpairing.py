# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2024 arzamas-16 <https://github.com/arzamas-16>

import logging
import struct
from typing import List
from src.common import as_hex
from src.error import AppotechError, AppotechTruncatedError


class BtPairing:
    """
    DB_RECORD sector structure reimplementation.
    For convenience, the class was named BtPairing.
    Original source code for this structure:
    AX2227_BTBOXSDK_V110_20141010/APP_LLP/btstack/BtApi.c (line 111)
    ( https://github.com/Edragon/buildwin )
    """

    MAGIC: bytes = b"BTPAIREDINFOHEAD"
    HDR_SIZE: int = len(MAGIC)
    logger: logging.Logger = logging.getLogger(__name__)

    entries: List
    paired_idx: int

    CONFIGURABLES = tuple("paired_idx")

    def __init__(self, entries=[], paired_idx=0):
        self.entries = entries
        self.paired_idx = paired_idx

        # Initialize with an empty entry by default
        if not len(self.entries):
            self.entries.append(BtPairing.Entry())

    def load(self, data: bytes):
        """Decode the binary structure and set the appropriate class fields"""
        self.entries.clear()
        off: int = 0

        # Validate size.
        # The struct must fit at least 1 entry
        size_check: int = self.HDR_SIZE + BtPairing.Entry.SIZE + 1
        if len(data) < size_check:
            raise AppotechTruncatedError(size_check, len(data))

        # Validate header
        if not data.startswith(self.MAGIC):
            raise AppotechError("Invalid magic")
        off += len(self.MAGIC)

        # Read entries one by one
        while True:
            # Stop if we exhausted the data source
            size_check = len(data) - off
            if size_check < BtPairing.Entry.SIZE:
                self.logger.warning(
                    f"Stop reading: expected {BtPairing.Entry.SIZE} bytes, "
                    f"{size_check} available"
                )
                break
            # Stop on first invalid entry. Prematurely parse the `is_valid`
            # field of the struct and check its value.
            entry_data: bytes = data[off : off + BtPairing.Entry.SIZE]
            if entry_data[-1] != 1:
                self.logger.warning("Stop reading: abnormal `is_valid` value")
                break

            entry = BtPairing.Entry()
            entry.load(entry_data)
            self.entries.append(entry)
            off += BtPairing.Entry.SIZE

        if not self.entries:
            raise AppotechError("No entries were read")

        # Load `paired_idx`
        size_check = len(data) - off
        if size_check < 1:  # need to read just one more byte
            raise AppotechTruncatedError(1, size_check)
        self.paired_idx = data[off]
        off += 1

    def length(self) -> int:
        """Return current length of structure in bytes"""
        return len(self.MAGIC) + len(self.entries) * BtPairing.Entry.SIZE + 1

    def __bytes__(self) -> bytes:  # noqa: D105
        data = (
            self.MAGIC
            + b"".join([bytes(e) for e in self.entries])
            + struct.pack("<B", self.paired_idx)
        )
        return data

    def __repl__(self):  # noqa: D105
        return f"BtPairing({self.entries.__repr__()}, {self.paired_idx})"

    def __str__(self):  # noqa: D105
        # stringify all entries
        ent = ",\n".join([str(e) for e in self.entries])
        # add 1 level of indentation to each line
        ent = "\n".join(f"        {line}" for line in ent.splitlines())

        result: str = "BtPairing(\n"
        result += "    entries = [\n"
        result += ent
        result += f"\n    ],\n    paired_idx = {self.paired_idx}\n"
        result += ")"
        return result

    class Entry:
        """
        DB_DEVICE_RECORD sector structure reimplementation.
        For convenience, the class was named BtPairing.Entry.
        Original source code for this structure:
        AX2227_BTBOXSDK_V110_20141010/APP_LLP/btstack/BtApi.c (line 104)
        ( https://github.com/Edragon/buildwin )
        """

        _FMT: str = "<16s6s32sB"
        SIZE: int = struct.calcsize(_FMT)

        link_key: bytes
        bt_mac: bytes
        bt_name: str
        is_valid: bool

        CONFIGURABLES = ("link_key", "bt_mac", "bt_name", "is_valid")

        def __init__(
            self, link_key=b"", bt_mac=b"", bt_name="", is_valid=False
        ):
            """Initialize the structure with field values. The MAC address
            *MUST* be reversed compared to the value stored in SPI flash!!!"""
            self.link_key = link_key
            self.bt_mac = bt_mac
            self.bt_name = bt_name
            self.is_valid = is_valid

        def load(self, data):
            """
            Decode the binary structure and set the appropriate class fields.
            The MAC address is reversed to make it look like what would
            `cat /var/lib/bluetooth/HOST_MAC/CLIENT_MAC` print.
            When `__bytes__` is called the MAC address will be reversed again
            to produce the value processable by the speaker firmware.
            """

            # Validate size
            if len(data) < self.SIZE:
                raise AppotechTruncatedError(self.SIZE, len(data))

            try:
                (
                    self.link_key,
                    self.bt_mac,
                    self.bt_name,
                    u8_is_valid,
                ) = struct.unpack(self._FMT, data)

                # fixup bluetooth mac address endianness
                self.bt_mac = bytes(reversed(self.bt_mac))
                # fixup the bluetooth name by converting it to string
                self.bt_name = self.bt_name.split(b"\x00")[0].decode("utf-8")
                # fixup the is_valid flag to be boolean
                self.is_valid = u8_is_valid == 1
            except (UnicodeDecodeError, struct.error) as ex:
                raise AppotechError(
                    f"Could not load entry from {as_hex(data)}"
                ) from ex

        def __bytes__(self) -> bytes:  # noqa: D105
            """MAC will be in its original form"""
            return struct.pack(
                self._FMT,
                self.link_key,
                bytes(reversed(self.bt_mac)),
                self.bt_name.encode(),
                int(self.is_valid),
            )

        def __str__(self) -> str:  # noqa: D105
            """MAC is reversed here"""
            return (
                "BtPairing.Entry(\n"
                f"    link_key = {as_hex(self.link_key)}\n"
                f"    bt_mac   = {as_hex(self.bt_mac)}\n"
                f"    bt_name  = \"{self.bt_name}\"\n"
                f"    is_valid = {self.is_valid}\n"
                ")"
            )  # fmt: skip

        def __repr__(self) -> str:  # noqa: D105
            """MAC is reversed here"""
            return (
                f"BtPairing.Entry({self.link_key}, "
                f"{self.bt_mac}, "
                f"\"{self.bt_name}\", "
                f"{self.is_valid})"
            )  # fmt: skip
