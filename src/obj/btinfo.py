# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2024 arzamas-16 <https://github.com/arzamas-16>

import logging
import struct
from src.common import as_hex, bit
from src.error import AppotechError, AppotechTruncatedError


class BtInfo:
    """
    BTINF sector structure reimplementation.
    For convenience, the class was named BtInfo (note the "o").
    Original source code for this structure:
    AX2227_BTBOXSDK_V110_20141010/APP_LLP/btstack/BtApi.c (line 600)
    ( https://github.com/Edragon/buildwin )
    """

    _FMT: str = "<xBBBB4x32s6s10xH"
    MAGIC: bytes = b"BTINF"
    SIZE = len(MAGIC) + struct.calcsize(_FMT)
    logger: logging.Logger = logging.getLogger(__name__)

    FLAG_CUST_BT_NAME = bit(0)
    FLAG_CUST_BT_MAC = bit(1)
    FLAG_CUST_MUTE_CFG = bit(2)

    flags: int = 0
    mic_unmute_thresh: int = 0
    mic_mute_thresh: int = 0
    mic_mute_duration: int = 0
    bt_name: str = ""
    bt_mac: bytes = b""
    checksum: int = 0

    CONFIGURABLES = (
        "flags",
        "mic_unmute_thresh",
        "mic_mute_thresh",
        "mic_mute_duration",
        "bt_name",
        "bt_mac",
    )

    def __init__(
        self,
        flags=0,
        mic_unmute_thresh=0,
        mic_mute_thresh=0,
        mic_mute_duration=0,
        bt_name="",
        bt_mac=b"\x00\x00\x00\x00\x00\x00",
        checksum=0,
    ):
        self.flags = flags
        self.mic_unmute_thresh = mic_unmute_thresh
        self.mic_mute_thresh = mic_mute_thresh
        self.mic_mute_duration = mic_mute_duration
        self.bt_name = bt_name
        self.bt_mac = bt_mac
        self.checksum = checksum

    def load(self, data: bytes):
        """Decode the binary structure and set the appropriate class fields"""
        off: int = 0

        # Validate size
        if len(data) < self.SIZE:
            raise AppotechTruncatedError(self.SIZE, len(data))

        # Validate header
        if not data.startswith(self.MAGIC):
            raise AppotechError("Invalid magic")
        off += len(self.MAGIC)

        try:
            (
                self.flags,
                self.mic_unmute_thresh,
                self.mic_mute_thresh,
                self.mic_mute_duration,
                self.bt_name,
                self.bt_mac,
                self.checksum,
            ) = struct.unpack(self._FMT, data[off : self.SIZE])

            # fixup the bluetooth name by converting it to string
            self.bt_name = self.bt_name.split(b"\x00")[0].decode("utf-8")
            # fixup bluetooth mac address endianness
            self.bt_mac = bytes(reversed(self.bt_mac))
        except (UnicodeDecodeError, struct.error) as ex:
            raise AppotechError(
                f"Could not load entry from {data.hex()}"
            ) from ex

        # Be forgiving when validating the checksum, do not raise an error on mismatch
        our_checksum = sum(data[: self.SIZE - 2])
        if our_checksum != self.checksum:
            self.logger.warning(
                "Invalid checksum: "
                f"expected {as_hex(our_checksum, 2)}, "
                f"got {as_hex(self.checksum, 2)}"
            )

    def __bytes__(self) -> bytes:  # noqa: D105
        data_without_checksum: bytes = self.MAGIC + struct.pack(
            self._FMT[:-1],
            self.flags,
            self.mic_unmute_thresh,
            self.mic_mute_thresh,
            self.mic_mute_duration,
            self.bt_name.encode(),
            bytes(reversed(self.bt_mac)),
        )
        # Don't be afraid of `checksum` overflow, its max value is 65536 (0xFFFF)
        # The structure is 62 bytes long, max possible sum is 0xFF * 62 = 15872 (0x3E00)
        checksum: bytes = struct.pack("<H", sum(data_without_checksum))
        return data_without_checksum + checksum

    def __str__(self) -> str:  # noqa: D105
        return (
            "BtInfo(\n"
            f"    flags             = {as_hex(self.flags, 1)}\n"
            f"    mic_unmute_thresh = {as_hex(self.mic_unmute_thresh, 1)}\n"
            f"    mic_mute_thresh   = {as_hex(self.mic_mute_thresh, 1)}\n"
            f"    mic_mute_duration = {as_hex(self.mic_mute_duration, 1)}\n"
            f"    bt_name           = \"{self.bt_name}\"\n"
            f"    bt_mac            = {as_hex(self.bt_mac)}\n"
            f"    checksum          = {as_hex(self.checksum, 2)}\n"
            ")"
        )  # fmt: skip

    def __repr__(self) -> str:  # noqa: D105
        return (
            f"BtInfo({self.flags}, "
            f"{self.mic_unmute_thresh}, "
            f"{self.mic_mute_thresh}, "
            f"{self.mic_mute_duration}, "
            f"\"{self.bt_name}\", "
            f"{self.bt_mac}, "
            f"{self.checksum})"
        )  # fmt: skip
