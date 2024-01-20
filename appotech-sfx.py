#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2024 arzamas-16 <https://github.com/arzamas-16>

"""appotech-sfx: manipulate the SFX blob of AppoTech firmware."""

import argparse
import logging
import os
import os.path as io
import sys
from datetime import datetime
from typing import List

from src.common import align_bytes, find_all, write_and_check
from src.obj.sfx import SfxBlob

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] <%(levelname)s> %(message)s",
)


class AppotechSfx:  # noqa: D101
    PROG_NAME = "appotech-sfx"

    args: argparse.Namespace
    logger: logging.Logger = logging.getLogger(PROG_NAME)

    input_binary: bytes
    input_files: List[str]

    sb: SfxBlob = SfxBlob()
    sb_off_start: int
    sb_size: int

    def main(self):
        """Program entry point. Parse args, setup logger, run main logic."""
        # fmt: off
        parser: argparse.ArgumentParser = argparse.ArgumentParser(
            prog=self.PROG_NAME,
            description="""Manipulate the SFX blob of AppoTech firmware.
The program has 2 modes of operation depending on the type of INPUT. If it's
a file, it's treated as a firmware image (or a standalone SFX blob) and EXTRACT
operations will be available. If it's a directory, its contents are treated as
a set of individual audio files to be packed into a new SFX blob - in this case
the REPACK operations will be available.""",
            epilog="""NOTES. When using the `-O` switch the program will scan
(non-recursively) the specified directory for files with extensions ending with
".mp3" and ".wav". The file list is then sorted by name in ascending order and
used to build the SFX blob. RESTRICTIONS. The speaker firmware imposes some 
restrictions on what files could be used. For example only WAV files could be
played while in Bluetooth mode and MP3 in other modes. Do not reencode WAV into
MP3, this won't work. The supported SFX quality parameters depend on the
firmware version, which cannot currently be accurately determined using the
programs in this repository. For firmwares before V092 only 8 kHz 8-bit mono 
WAV is supported and starting from V093 8/16/32 kHz 8/16-bit mono WAVs are 
supported. I have found no information about the supported MP3 quality
parameters. Removing ID3 tags from MP3 files and using mono channel might save
some space."""
        )
        parser.add_argument(
            "input_path",
            metavar="INPUT",
            help=(
                "Input data. Provide either a single binary file for EXTRACT "
                "mode or a directory for REPACK mode."
            )
        )

        parser_extract_group = parser.add_argument_group("EXTRACT")
        parser_extract_group.add_argument(
            "-p",
            dest="print_input",
            action="store_true",
            help="Print SFX blob info."
        )
        parser_extract_group.add_argument(
            "-c",
            metavar="OUTFILE",
            dest="carve_output_path",
            help="Carve out the SFX blob from INPUT and save it to OUTFILE."
        )
        parser_extract_group.add_argument(
            "-e",
            metavar="OUTDIR",
            dest="extract_output_path",
            help=(
                "Extract individual SFX components to OUTDIR. If the directory "
                "doesn't exist it will be created automatically."
            )
        )

        parser_repack_group = parser.add_argument_group("REPACK")
        parser_repack_group.add_argument(
            "-o",
            dest="output_path",
            metavar="OUTFILE",
            help=(
                "Repack and save just the SFX blob to OUTFILE. Please read "
                "about the RESTRICTIONS below."
            )
        )
        parser_repack_group.add_argument(
            "-O",
            dest="inject_path",
            metavar="OUTFILE",
            help=(
                "Repack and inject the SFX blob into the specified firmware "
                "image. The file must exist and the firmware image itself "
                "must have an existing SFX blob to be replaced. Please read "
                "NOTES and RESTRICTIONS below for more info."
            )
        )
        parser_repack_group.add_argument(
            "-f",
            dest="force_inject",
            action="store_true",
            default=False,
            help = (
                "Force write the SFX blob when it big enough to overlap into "
                "the next region. Attention: the resulting binary still will "
                "NOT exceed the original file size!"
            )
        )
        # fmt: on
        self.args = parser.parse_args()

        if io.isfile(self.args.input_path):
            self.mode_extract()
        elif io.isdir(self.args.input_path):
            self.mode_repack()
        else:
            self.logger.error(f"Unknown input argument: {self.args.input_path}")
            sys.exit(1)

    def mode_extract(self):
        """Entry point of the EXTRACT mode."""
        self.extract_load_input()
        if self.args.print_input:
            self.extract_print_input()
        if self.args.carve_output_path:
            self.extract_carve()
        if self.args.extract_output_path:
            self.extract_extract()  # πλεονασμός

    def extract_load_input(self):
        """Load the input SFX blob from file."""
        with open(self.args.input_path, "rb") as fis:
            self.input_binary = fis.read()

        """Search for the "00080000" hexadecimal sequence. Explanation:
        in SfxBlob, entries follow after the header. The header has a fixed
        size of 0x800 bytes. That means the first entry will start at 0x800
        relative to SfxBlob. Each entry in the header has following structure:
        [ offset (u32), size in chunks (u16), sampling rate (u16) ]
        Thus the header will begin with an offset of the first entry, which
        would be "00080000" (SfxBlob.MAGIC). The probles is there might be
        multiple such values in the dumped firmware image, so we must also
        match the correct one."""
        self.sb_off_start = -1
        for test_off in find_all(
            self.input_binary[: -SfxBlob.HDR_SIZE], SfxBlob.MAGIC
        ):
            # The SFX blob seems to be always aligned by 0x80 (128 bytes)
            if test_off % 0x80 != 0:
                self.logger.info(
                    f"Found header at {test_off} but it's not an SFX blob "
                    "(not aligned), keep searching"
                )
                continue
            """The header is quite big, and usually it's not filled to the brim.
            Count zeroes in the header. Assume the header valid if zeroes take
            take more than 80% of space. This is a probabilistic approach but
            it hasn't caused any Type II errors (yet)."""
            zeroes = self.input_binary[
                test_off : test_off + SfxBlob.HDR_SIZE
            ].count(0x00)
            if zeroes <= SfxBlob.HDR_SIZE * 0.8:
                self.logger.info(
                    f"Found header at {test_off} but it's not an SFX blob "
                    "(weird amount of zeroes), keep searching"
                )
                continue
            # All checks passed, save the offset and break the loop
            self.sb_off_start = test_off
            break
        if self.sb_off_start == -1:
            self.logger.error("Could not find an SFX blob header in file")
            sys.exit(1)
        self.logger.info(f"Found the SFX blob header at {self.sb_off_start}")

        # Read the rest of the file because it's troublesome to determine
        # the size of the structure without decoding it first.
        self.sb.load(self.input_binary[self.sb_off_start :])
        self.sb_size = self.sb.total_size_in_bytes()

    def extract_print_input(self):
        """Print SFX blob info. This function can't be moved into sfx.py's
        __str__ because it depends on local variables `self.sb_off_start` and
        `self.sb_size`."""
        self.logger.info("Printing SFX blob info")
        offset_start: int = 0
        offset_end: int = 0
        sep: str = "------------------------------\n"

        contents: str = (
            "SFX BLOB SUMMARY\n"
            f"{'Offset: ':<15}{self.sb_off_start}-{self.sb_off_start + self.sb_size}\n"
            f"{'Entries: ':<15}{len(self.sb.entries)}\n"
            f"{'Size: ':<15}{self.sb_size} bytes\n"
            f"{sep}"
        )

        for idx, entry in enumerate(self.sb.entries):
            offset_start = self.sb_off_start + entry.offset
            offset_end = offset_start + entry.total_size_in_bytes()
            contents += (
                f"Entry #{idx}\n"
                f"{'Offset: ':<15}{offset_start}-{offset_end} (relative to file)\n"
                f"{entry}\n"
                f"{sep}"
            )
        print(contents.strip())

    def extract_carve(self):
        """Save the extracted SFX blob as standalone file."""
        self.logger.info("Carving out the SFX blob")
        if not write_and_check(
            self.args.carve_output_path,
            self.input_binary[
                self.sb_off_start : self.sb_off_start + self.sb_size
            ],
        ):
            sys.exit(1)

    def extract_extract(self):
        """Dump individual audio files from the SFX blob."""
        self.logger.info("Extracting entries")

        # Get current timestamp to "mark" the batch of files just in case
        timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
        dir: str = self.args.extract_output_path
        filename: str = ""
        path: str = ""

        if not io.isdir(dir):
            os.mkdir(dir)
            self.logger.info(f"Created directory {dir}")

        for idx, entry in enumerate(self.sb.entries):
            filename = f"{timestamp}-sfx-{idx:03}.{entry.get_format().lower()}"
            path = io.join(dir, filename)
            if not write_and_check(path, entry.export_to_file()):
                sys.exit(1)

        self.logger.info(f"Extracted {len(self.sb.entries)} entries to {dir}")

    def mode_repack(self):
        """Entry point of the REPACK mode."""
        self.repack_load_input()
        if self.args.output_path:
            self.repack_save_output()
        if self.args.inject_path:
            self.repack_inject_output()

    def repack_load_input(self):
        """Load the input files from the specified directory and build the
        SFX blob out of them."""
        # First, list all files in the specified directory
        self.input_files = [
            io.join(self.args.input_path, f)
            for f in os.listdir(self.args.input_path)
        ]
        # Keep only MP3 and WAV (basic file extension check)
        self.input_files = [
            f for f in self.input_files if f.lower().endswith((".mp3", ".wav"))
        ]
        # Sort by file name
        self.input_files = sorted(self.input_files, key=str.lower)

        if len(self.input_files) > SfxBlob.MAX_ENTRIES:
            self.logger.error("Too many files for a SFX blob!")
            sys.exit(1)

        self.logger.info(f"Discovered {len(self.input_files)} audio files")
        self.sb.load_from_files(self.input_files)

    def repack_save_output(self):
        """Save the built SFX blob as standalone file."""
        self.logger.info(f"Creating SFX blob {self.args.output_file}")
        if not write_and_check(self.args.output_file, bytes(self.sb)):
            sys.exit(1)

    def repack_inject_output(self):
        """Inject the built SFX blob into specified firmware and save it into
        a new file with autogenerated name."""
        self.logger.info(f"Injecting the SFX blob into {self.args.inject_path}")

        # Right now `self.sb` holds the SFX blob built from `self.args.input_file`
        blob = bytes(self.sb)

        # Use `extract_load_input` to load the source file into `self.sb`, this
        # will also refresh `self.sb_off_start` and `self.sb_size`.
        self.args.input_path = self.args.inject_path
        self.extract_load_input()

        if len(blob) < self.sb_size:
            self.logger.info(
                "The new SFX blob is smaller than the old one! Adding "
                f"{self.sb_size - len(blob)} bytes of padding (using 0xFF)."
            )
            blob = align_bytes(blob, self.sb_size, 0xFF)
        if len(blob) > self.sb_size:
            if self.args.force_inject:
                # Check if blob doesn't exceed the size of the original file.
                delta: int = (
                    self.sb_off_start + len(blob) - len(self.input_binary)
                )
                if delta > 0:
                    self.logger.warning(
                        f"File size limit exceeded by {delta} bytes. "
                        "Truncating (yes, happens even with `-f`)."
                    )
                blob = blob[: len(blob) - delta]
            else:
                self.logger.error(
                    "Modified blob is bigger than original! "
                    f"{len(blob)} vs {self.sb_size}. Refusing to write "
                    "because it overlaps its own region. Consider "
                    "using the `-f` option."
                )
                sys.exit(1)
        blob = bytes(
            self.input_binary[: self.sb_off_start]
            + blob
            + self.input_binary[self.sb_off_start + len(blob) :]
        )

        timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
        path: str = f"{self.args.inject_path}-{timestamp}-mod.bin"
        if not write_and_check(path, blob):
            sys.exit(1)


if __name__ == "__main__":
    AppotechSfx().main()
