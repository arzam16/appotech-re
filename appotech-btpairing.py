#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2024 arzamas-16 <https://github.com/arzamas-16>

"""appotech-btpairing: Manipulate the DB_RECORD (BTPAIRINFO) sector of AppoTech firmware."""

import argparse
import hashlib
import logging
import sys
from typing import List

from src.common import (
    indices_atoi_list,
    irange,
    set_variable,
    split_in_chunks,
    write_and_check,
)
from src.obj.btpairing import BtPairing

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] <%(levelname)s> %(message)s",
)


class AppotechBtPairing:  # noqa: D101
    PROG_NAME = "appotech-btpairing"

    args: argparse.Namespace
    logger: logging.Logger = logging.getLogger(PROG_NAME)

    input_binary: bytes
    bp: BtPairing = BtPairing()
    bp_off_start: int  # struct offset in input file
    bp_size: int  # struct size right after it's been loaded from file
    bp_hash: bytes

    def main(self):
        """Program entry point. Parse args, setup logger, run main logic."""
        # fmt: off
        parser: argparse.ArgumentParser = argparse.ArgumentParser(
            prog=self.PROG_NAME,
            description="Manipulate the DB_RECORD (BTPAIRINFO) sector of AppoTech firmware",
            epilog=(
                f"AVAILABLE ENTRY FIELDS: {', '.join(BtPairing.Entry.CONFIGURABLES)}"
            )
        )
        parser.add_argument(
            "-i",
            dest="input_path",
            metavar="INFILE",
            help="Find and read structure from INFILE. If not provided, an empty structure will be created.",
        )
        parser.add_argument(
            "-p",
            dest="print_input",
            action="store_true",
            help="Print source structure.",
        )
        parser.add_argument(
            "-P",
            dest="print_output",
            action="store_true",
            help="Print modified structure.",
        )
        parser.add_argument(
            "-a",
            dest="add_entries",
            metavar="i",
            nargs="+",
            help="Add an empty entry at index. Indices are processed sequentially."
        )
        parser.add_argument(
            "-d",
            dest="delete_entries",
            metavar="i",
            nargs="+",
            help="Delete entry at index. Indices are accepted in any order."
        )
        parser.add_argument(
            "-S",
            dest="assign_values",
            metavar="i K V",
            nargs="+",
            help=(
                "Set (assign) values to the fields of entry by its index. "
                "Example: -S 0 bt_name \"amogus\". "
                "See AVAILABLE ENTRY FIELDS below."
            ),
        )
        parser.add_argument(
            "-C",
            dest="clear_values",
            metavar="I K",
            nargs="+",
            help=(
                "Clear values in the fields of entry by its index. "
                "Example: -C 3 link_key. "
                "See AVAILABLE ENTRY FIELDS below."
            )
        )
        parser.add_argument(
            "-x",
            dest="paired_idx",
            metavar="i",
            help=(
                "Change the index of the currently paired device "
                "(aka the latest active entry). "
                "Accepted values are from 0 to 255 inclusive."
            )
        )
        parser.add_argument(
            "-o",
            dest="output_path",
            metavar="OUTFILE",
            help="Save just the modified structure to OUTFILE.",
        )
        parser.add_argument(
            "-O",
            dest="mod_path",
            metavar="OUTFILE",
            help="Inject the modified structure into the INFILE contents and save to OUTFILE.",
        )
        parser.add_argument(
            "-f",
            dest="force_write_mod",
            action="store_true",
            default=False,
            help=(
                "Force write the modified structure when it big enough to "
                "overlap into the next region. Attention: the resulting binary "
                "still will NOT exceed the original file size!"
            )
        )
        # fmt: on
        self.args = parser.parse_args()

        self.load_input()
        if self.args.print_input:
            self.logger.info("Printing source structure")
            self.print_values()
            # Exit now if launched just to print the source structure
            if not any(
                (
                    self.args.add_entries,
                    self.args.delete_entries,
                    self.args.assign_values,
                    self.args.paired_idx,
                    self.args.print_output,
                    self.args.output_path,
                    self.args.mod_path,
                )
            ):
                sys.exit(0)

        if self.args.add_entries:
            self.add_entries()
        if self.args.delete_entries:
            self.delete_entries()
        if self.args.assign_values:
            self.assign_values()
        if self.args.clear_values:
            self.clear_values()
        if self.args.paired_idx:
            self.set_paired_index()

        if self.args.print_output:
            new_hash = hashlib.sha256(bytes(self.bp)).hexdigest()
            if self.bp_hash == new_hash:
                self.logger.info("No modifications were made")
                sys.exit(0)
            else:
                self.logger.info("Printing modified structure")
                self.print_values()

        if not any((self.args.output_path, self.args.mod_path)):
            self.logger.error("No output path specified")
            sys.exit(1)
        self.save_output()

    def load_input(self):
        """Load the input BtPairing structure either from file or use the default one."""
        if self.args.input_path:
            with open(self.args.input_path, "rb") as fis:
                self.input_binary = fis.read()
            self.logger.info(
                f"Read {len(self.input_binary)} bytes "
                f"from {self.args.input_path}"
            )

            try:  # EAFP :(
                self.bp_off_start = self.input_binary.index(BtPairing.MAGIC)
            except ValueError:
                self.logger.exception("Could not find magic value in file")
                sys.exit(1)

            # Read the rest of the file because it's troublesome to determine
            # the size of the structure without decoding it first.
            self.bp.load(self.input_binary[self.bp_off_start :])
        else:
            self.logger.info(
                "Input file was not provided, using empty structure"
            )
            self.bp_off_start = 0
        self.bp_hash = hashlib.sha256(bytes(self.bp)).hexdigest()
        self.bp_size = self.bp.length()

    def print_values(self):
        """Pretty-print all available fields in the structure."""
        self.logger.info("MAC addresses are reversed for your convenience")
        print(str(self.bp))

    def add_entries(self):
        """Inject new empty entries at the indices from CLI args"""
        idx: List[int] = indices_atoi_list(
            self.args.add_entries, len(self.bp.entries)
        )
        if not idx:  # the error has already been logged by the function above
            sys.exit(1)

        for i in idx:
            self.logger.info(f"Injecting empty entry at index {i}")
            self.bp.entries.insert(i, BtPairing.Entry())

    def delete_entries(self):
        """Delete entries at the indices from CLI args"""
        idx: List[int] = indices_atoi_list(
            self.args.delete_entries, len(self.bp.entries)
        )
        if not idx:  # the error has already been logged by the function above
            sys.exit(1)

        self.bp.entries = [
            self.bp.entries[i]
            for i in range(len(self.bp.entries))
            if i not in idx
        ]
        for i in idx:
            self.logger.info(f"Removed entry at index {i}")

    def assign_values(self):
        """Assign entry fields based on index-key-value triplets from CLI args."""
        if len(self.args.assign_values) % 3 != 0:
            self.logger.error("Invalid values specified for -S swtich")
            sys.exit(1)

        # Iterate through the pairs: (key, value)
        for index, field, value in split_in_chunks(self.args.assign_values, 3):
            idx: int = 0
            try:
                idx = int(index)
                if idx > len(self.bp.entries):
                    raise ValueError()
            except ValueError:
                self.logger.exception(f"Invalid index {idx}")
                sys.exit(1)
            entry: BtPairing.Entry = self.bp.entries[idx]

            if field == "link_key":
                set_variable(entry, field, value, len_range=irange(16))
            elif field == "bt_mac":
                set_variable(entry, field, value, len_range=irange(6))
            elif field == "bt_name":
                set_variable(entry, field, value, len_range=irange(32))
            elif field == "is_valid":
                set_variable(entry, field, value)
            else:
                self.logger.error(
                    f"Unknown field {field}. "
                    f"Available fields: {', '.join(BtPairing.Entry.CONFIGURABLES)}"
                )
                sys.exit(1)
            self.logger.info(
                f"Successfully assigned bp.entries[{idx}].{field} = {value}"
            )

    def clear_values(self):
        """Clear entry fields based on index-key pairs from CLI args."""
        # create dummy object with default values set
        dummy: BtPairing.Entry = BtPairing.Entry()

        for index, field in split_in_chunks(self.args.clear_values, 2):
            idx: int = 0
            try:
                idx = int(index)
                if idx > len(self.bp.entries):
                    raise ValueError()
            except ValueError:
                self.logger.error(f"Invalid index {idx}")
                sys.exit(1)
            entry: BtPairing.Entry = self.bp.entries[idx]

            if field not in BtPairing.Entry.CONFIGURABLES:
                self.logger.error(
                    f"Unknown field {field}. "
                    f"Available fields: {', '.join(BtPairing.Entry.CONFIGURABLES)}"
                )
                sys.exit(1)
            value = getattr(dummy, field)
            setattr(entry, field, value)
            self.logger.info(
                f"Successfully assigned bp.entries[{idx}].{field} = {value}"
            )

    def set_paired_index(self):
        """Set index of the latest connected device"""
        idx: int = 0
        try:
            idx = int(self.args.paired_idx)
            if idx not in irange(0xFF):
                raise ValueError()
        except ValueError:
            self.logger.error(f"Invalid index {idx}")
            sys.exit(1)

        self.bp.paired_idx = idx
        self.logger.info(f"Successfully assigned bp.paired_idx = {idx}")

    def save_output(self):
        """Save the structure as standalone file and/or modified source file."""
        blob: bytes = bytes(self.bp)

        for path in (self.args.output_path, self.args.mod_path):
            if not path:
                continue
            if path == self.args.output_path:
                self.logger.info("Saving just the struct")
            elif path == self.args.mod_path:
                self.logger.info("Injecting modified struct into source file")
                # assemble the modified binary
                if len(blob) > self.bp_size:
                    if self.args.force_write_mod:
                        delta: int = (
                            self.bp_off_start
                            + len(blob)
                            - len(self.input_binary)
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
                            f"{len(blob)} vs {self.bp_size}. Refusing to write "
                            "because it overlaps its own region. Consider "
                            "using the `-f` option."
                        )
                        sys.exit(1)
                elif len(blob) < self.bp_size:
                    padding_sz = len(blob) - self.bp_size
                    blob = blob + (b"\xFF" * padding_sz)
                    self.logger.warning(
                        "Modified blob is bigger than original! "
                        f"{len(blob)} vs {self.bp_size}. "
                        f"Added {padding_sz} bytes of padding."
                    )
                blob = bytes(
                    self.input_binary[: self.bp_off_start]
                    + blob
                    + self.input_binary[self.bp_off_start + len(blob) :]
                )
            if not write_and_check(path, blob):
                sys.exit(1)


if __name__ == "__main__":
    AppotechBtPairing().main()
