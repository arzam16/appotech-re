# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2024 arzamas-16 <https://github.com/arzamas-16>

import logging
import struct
import wave
from abc import ABC, abstractmethod
from io import BytesIO
from typing import List, Tuple

from src.common import align_bytes
from src.error import AppotechTruncatedError


class AbstractSfxEntry(ABC):
    """An abstract SFX entry. Make a descender class for each audio format."""

    _FMT: str = "<IHH"
    SIZE: int = struct.calcsize(_FMT)

    CHUNK_SIZE = 0x100

    """Offset of file relative to the SFX blob."""
    offset: int
    """Size of file in 0x100-bytes-long chunks (the WAV trailer block size is
    NOT included in this field!)"""
    size: int
    """Sampling rate of an SFX."""
    samplerate: int
    """Raw audio data."""
    contents: bytes

    def __init__(
        self,
        offset: int = 0,
        size: int = 0,
        samplerate: int = 0,
        contents: bytes = b"",
    ):
        self.offset = offset
        self.size = size
        self.samplerate = samplerate  # in Hz
        self.contents = contents

    @abstractmethod
    def get_format(self) -> str:
        """Return the format/extension of the SFX."""
        pass

    @abstractmethod
    def total_size_in_bytes(self) -> int:
        """Calculate the total size of the SFX in bytes."""
        pass

    @abstractmethod
    def export_to_blob(self) -> Tuple[bytes, bytes]:
        """Generate the byte representation of the entry for inclusion into the
        new SFX blob.

        Returns:
            Tuple[bytes, bytes]: (header), (audio data).
        """
        pass

    @abstractmethod
    def export_to_file(self) -> bytes:
        """Generate bytes for export to an external standalone audio file.

        Returns:
            bytes: audio file data.
        """
        pass

    @abstractmethod
    def import_from_blob(self, data: bytes):
        """Load entry contents from the SFX blob.

        Parameters:
            data (bytes): Raw SFX blob data.
        """
        pass

    @abstractmethod
    def import_from_file(self, offset: int, data: bytes):
        """Load entry contents from standalone external file bytes.

        Parameters:
            offset (int): Offset of the entry (in bytes) relative to SFX blob.
            data (bytes): File bytes.
        """
        pass

    def __bytes__(self) -> bytes:
        """Export offset, size and samplerate as `bytes`."""
        data: bytes = struct.pack(
            self._FMT, self.offset, self.size, self.samplerate
        )
        return data

    @abstractmethod
    def __str__(self) -> str:
        """Return the SFX info in human-readable form."""
        pass


class Mp3SfxEntry(AbstractSfxEntry):  # noqa: D101
    def get_format(self) -> str:
        return "MP3"

    def total_size_in_bytes(self) -> int:
        return self.size * self.CHUNK_SIZE

    def export_to_blob(self) -> Tuple[bytes, bytes]:
        return self.__bytes__(), self.contents

    def export_to_file(self) -> bytes:
        return self.contents

    def import_from_blob(self, data: bytes):
        self.contents = data  # import as is

    def import_from_file(self, offset: int, data: bytes):
        self.offset = offset
        self.contents = align_bytes(data, self.CHUNK_SIZE)
        # adjust size
        self.size = len(self.contents) // self.CHUNK_SIZE
        # sampling rate is 0 for MP3
        self.samplerate = 0

    def __str__(self) -> str:
        offset_end: int = self.offset + self.total_size_in_bytes()
        return (
            f"{'Offset: ':<15}{self.offset}-{offset_end} (relative to SFX blob)\n"
            f"{'Size: ':<15}{self.total_size_in_bytes()} bytes\n"
            f"{'Format: ':<15}{self.get_format()}"
        )


class WavSfxEntry(AbstractSfxEntry):  # noqa: D101
    WAV_TRAILER_SIZE: int = 0x100
    TRAILER_MAGIC: bytes = b"WAV\x00"
    _TRAILER_FMT: str = "<4sBB250x"

    trailer: bytes = b""
    tr_samplerate: int = 0  # kHz
    tr_resolution: int = 0  # bits per sample

    def __init__(self, offset: int = 0, size: int = 0, samplerate: int = 0):
        self.offset = offset
        self.size = size
        self.samplerate = samplerate

    def get_format(self) -> str:
        return "WAV"

    def total_size_in_bytes(self) -> int:
        return self.size * self.CHUNK_SIZE + self.WAV_TRAILER_SIZE

    def export_to_blob(self) -> Tuple[bytes, bytes]:
        return self.__bytes__(), self.contents + self.trailer

    def export_to_file(self) -> bytes:
        """Attempt to reconstruct the WAV header."""
        # Also reverse the WAV 0x80 thingy.
        xor: int = 0x80 if self.tr_resolution == 8 else 0x00
        baos: BytesIO = BytesIO()
        with wave.open(baos, "wb") as wav:
            wav.setnchannels(1)  # always mono
            wav.setsampwidth(self.tr_resolution // 8)  # bits to bytes
            wav.setframerate(self.tr_samplerate * 1000)  # kHz to Hz
            wav.writeframesraw(bytes([b ^ xor for b in self.contents]))
        return baos.getvalue()

    def import_from_blob(self, data: bytes):
        self.contents = data

        # Check if there's trailer magic in the last 0x100 bytes of `contents`
        wav_test: bytes = self.contents[-self.WAV_TRAILER_SIZE :][:4]
        if wav_test != self.TRAILER_MAGIC:
            logging.warning(f"WAV trailer not found! Found this: {wav_test}")
            return

        self.trailer = self.contents[-self.WAV_TRAILER_SIZE :]
        # Validate just the size. The header has been checked at this point.
        if len(self.trailer) != self.WAV_TRAILER_SIZE:
            raise AppotechTruncatedError(
                self.WAV_TRAILER_SIZE, len(self.trailer)
            )
        _, self.tr_samplerate, self.tr_resolution = struct.unpack(
            self._TRAILER_FMT, self.trailer
        )

        # Keep the raw audio data without the WAV trailer
        self.contents = self.contents[: -self.WAV_TRAILER_SIZE]

    def import_from_file(self, offset: int, data: bytes):
        self.offset = offset
        xor: int = 0x00
        bais: BytesIO = BytesIO(data)
        with wave.open(bais, "rb") as wav:
            # be very forgiving to allow experimenting, but it will backfire
            if wav.getnchannels() != 1:
                logging.warning("Only mono WAV is supported!")

            self.tr_resolution = wav.getsampwidth() * 8  # bytes to bits
            if self.tr_resolution not in (8, 16):
                logging.warning(f"{self.tr_resolution}-bit WAV isn't supported")
            elif self.tr_resolution == 16:
                logging.warning(
                    "16-bit WAV might be not supported if your firmware is old"
                )
            xor = 0x80 if self.tr_resolution == 8 else 0x00

            self.samplerate = wav.getframerate()
            self.tr_samplerate = self.samplerate // 1000  # Hz to kHz
            if self.tr_samplerate not in (8, 16, 32):
                logging.warning("Only 8/16/32 kHz samplerate is supported")
            elif self.tr_samplerate != 8:
                logging.warning(
                    "16/32 kHz samplerate might be not supported if your "
                    "firmware is old"
                )
        # Assemble the WAV trailer now. Not very memory-efficient, though...
        self.trailer = struct.pack(
            self._TRAILER_FMT,
            self.TRAILER_MAGIC,
            self.tr_samplerate,
            self.tr_resolution,
        )
        # Read raw frame data and pad it with zeroes
        self.contents = align_bytes(
            bytes([b ^ xor for b in wav.readframes(wav.getnframes())]),
            self.CHUNK_SIZE,
        )
        # Adjust size
        self.size = len(self.contents) // self.CHUNK_SIZE

    def __str__(self) -> str:
        offset_end: int = self.offset + self.total_size_in_bytes()
        return (
            f"{'Offset: ':<15}{self.offset}-{offset_end} (relative to SFX blob)\n"
            f"{'Size: ':<15}{self.size * self.CHUNK_SIZE} bytes (just the raw audio data)\n"
            f"{'Size: ':<15}{self.total_size_in_bytes()} bytes (including the WAV trailer)\n"
            f"{'Format: ':<15}{self.get_format()}\n"
            f"{'Samplerate: ':<15}{self.samplerate} Hz\n"
            f"{'Resolution: ':<15}{self.tr_resolution}-bit"
        )


class SfxBlob:
    """SFX blob sector structure reimplementation."""

    MAGIC: bytes = b"\x00\x08\x00\x00"
    HDR_SIZE: int = 0x800
    MAX_ENTRIES: int = HDR_SIZE // AbstractSfxEntry.SIZE
    logger: logging.Logger = logging.getLogger(__name__)

    entries: List[AbstractSfxEntry]

    def __init__(self, entries=[]):
        self.entries = entries

    def load(self, data: bytes):
        """Load structure from an existing SFX blob from firmware."""
        self.entries.clear()

        # Validate size. Can't check entries yet, check the header for now
        size_check: int = self.HDR_SIZE
        if len(data) < size_check:
            raise AppotechTruncatedError(size_check, len(data))

        # Load available entries from header
        self.logger.info("Reading header")
        for off in range(0, self.HDR_SIZE, AbstractSfxEntry.SIZE):
            e_offset, e_size, e_samplerate = struct.unpack(
                AbstractSfxEntry._FMT, data[off : off + AbstractSfxEntry.SIZE]
            )
            if not any((e_offset, e_size, e_samplerate)):
                self.logger.warning("Stop reading: first empty entry found")
                break

            # initialize an entry with empty contents for now
            # samplerate is set only for WAV files, lets use it as a hint
            entry: AbstractSfxEntry = None
            if e_samplerate:
                entry = WavSfxEntry(e_offset, e_size, e_samplerate)
            else:
                entry = Mp3SfxEntry(e_offset, e_size, e_samplerate)
            self.entries.append(entry)

        # Load the contents of each entry
        self.logger.info("Reading contents of entries")
        for entry in self.entries:
            size_check = entry.total_size_in_bytes()
            if len(data) < size_check:
                raise AppotechTruncatedError(size_check, len(data))
            entry.import_from_blob(
                data[entry.offset : entry.offset + size_check]
            )

    def load_from_files(self, paths: List[str]):
        """Build the SFX blob structure from the list of files."""
        body_off: int = self.HDR_SIZE
        entry: AbstractSfxEntry

        for path in paths:
            logging.info(f"Processing {path}")
            if path.lower().endswith(".mp3"):
                entry = Mp3SfxEntry()
            else:
                entry = WavSfxEntry()
            data: bytes  # Read the file
            with open(path, "rb") as fis:
                data = fis.read()
            entry.import_from_file(body_off, data)
            self.entries.append(entry)
            body_off += entry.total_size_in_bytes()

    def total_size_in_bytes(self):
        return self.HDR_SIZE + sum(
            e.total_size_in_bytes() for e in self.entries
        )

    def __bytes__(self) -> bytes:
        header_off: int = 0
        result: bytearray = bytearray(self.total_size_in_bytes())

        for entry in self.entries:
            e_hdr, e_body = entry.export_to_blob()
            result[header_off : header_off + len(e_hdr)] = e_hdr
            result[entry.offset : entry.offset + len(e_body)] = e_body
            header_off += len(e_hdr)

        return bytes(result)
