#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2024 arzamas-16 <https://github.com/arzamas-16>

"""appotech-btinfo: manipulate the BTINF sector of AppoTech firmware."""

import argparse
import hashlib
import logging
import sys

from src.common import irange, set_variable, split_in_chunks, write_and_check
from src.obj.btinfo import BtInfo

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] <%(levelname)s> %(message)s",
)


class AppotechBtInfo:  # noqa: D101
    PROG_NAME = "appotech-btinfo"

    args: argparse.Namespace
    logger: logging.Logger = logging.getLogger(PROG_NAME)

    input_binary: bytes
    btinfo: BtInfo = BtInfo()
    btinfo_off_start: int  # struct offset in input file
    btinfo_off_end: int  # struct offset in input file
    btinfo_hash: bytes

    def main(self):
        """Program entry point. Parse args, setup logger, run main logic."""
        # fmt: off
        parser: argparse.ArgumentParser = argparse.ArgumentParser(
            prog=self.PROG_NAME,
            description="Manipulate the BTINF sector of AppoTech firmware",
            epilog=(
                f"AVAILABLE FIELDS: {', '.join(BtInfo.CONFIGURABLES)}"
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
            "-S",
            dest="assign_values",
            metavar="K V",
            nargs="+",
            help=(
                "Set (assign) values to the fields of structure. "
                "Example: -S bt_name \"My awesome speaker\". "
                "This switch can be used multiple times. "
                "See AVAILABLE FIELDS below."
            ),
        )
        parser.add_argument(
            "-C",
            dest="clear_values",
            metavar="K",
            nargs="+",
            help=(
                "Clear values in the fields of structure. "
                "Example: -C bt_name. "
                "This switch can be used multiple times. "
                "See AVAILABLE FIELDS below."
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
        # fmt: on
        self.args = parser.parse_args()

        self.load_input()
        if self.args.print_input:
            self.print_values()
            # Exit now if launched just to print the source structure
            if not any(
                (
                    self.args.assign_values,
                    self.args.clear_values,
                    self.args.print_output,
                    self.args.output_path,
                    self.args.mod_path,
                )
            ):
                sys.exit(0)

        if self.args.assign_values:
            self.assign_values()
        if self.args.clear_values:
            self.clear_values()

        if self.args.print_output:
            new_hash = hashlib.sha256(bytes(self.btinfo)).hexdigest()
            if self.btinfo_hash == new_hash:
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
        """Load the input BtInfo structure either from file or use the default one."""
        if self.args.input_path:
            with open(self.args.input_path, "rb") as fis:
                self.input_binary = fis.read()
            self.logger.info(
                f"Read {len(self.input_binary)} bytes "
                f"from {self.args.input_path}"
            )

            # Don't you hate mixing EAFP...
            try:
                self.btinfo_off_start = self.input_binary.index(BtInfo.MAGIC)
            except ValueError:
                self.logger.exception("Could not find magic value in file")
                sys.exit(1)
            # ... and LBYL, do you?
            self.btinfo_off_end = self.btinfo_off_start + BtInfo.SIZE
            if self.btinfo_off_end > len(self.input_binary):
                self.logger.error("Truncated data!")
                sys.exit(1)

            self.btinfo.load(
                self.input_binary[self.btinfo_off_start : self.btinfo_off_end]
            )
        else:
            self.logger.info(
                "Input file was not provided, using empty structure"
            )
            self.btinfo_off_start = 0
            self.btinfo_off_end = BtInfo.SIZE
        self.btinfo_hash = hashlib.sha256(bytes(self.btinfo)).hexdigest()

    def print_values(self):
        """Pretty-print all available fields in the structure."""
        self.logger.info("Printing source structure")
        self.check_flags()
        print(str(self.btinfo))

    # fmt: off
    def check_flags(self):  # noqa: E501
        """Check if the flags are set to enable usage of corresponding fields."""
        bt: BtInfo = self.btinfo
        flags: int = bt.flags
        
        if bt.bt_name and not (flags & BtInfo.FLAG_CUST_BT_NAME):
            self.logger.warning("bt_name is set but won't be used! flag not set")
        if bt.bt_mac != (b"\x00" * 6) and not (flags & BtInfo.FLAG_CUST_BT_MAC):
            self.logger.warning("bt_mac is set but won't be used! flag not set")
        if bt.mic_unmute_thresh and not (flags & BtInfo.FLAG_CUST_MUTE_CFG):
            self.logger.warning("mic_unmute_thresh is set but won't be used! flag not set")
        if bt.mic_mute_thresh and not (flags & BtInfo.FLAG_CUST_MUTE_CFG):
            self.logger.warning("mic_mute_thresh is set but won't be used! flag not set")
        if bt.mic_mute_duration and not (flags & BtInfo.FLAG_CUST_MUTE_CFG):
            self.logger.warning("mic_mute_duration is set but won't be used! flag not set")
    # fmt: on

    def assign_values(self):
        """Assign structure fields based on key-value pairs from CLI args."""
        if len(self.args.assign_values) % 2 != 0:
            self.logger.error("Invalid pairs specified for -S swtich")
            sys.exit(1)

        # Iterate through the pairs: (key, value)
        for field, value in split_in_chunks(self.args.assign_values, 2):
            if field in (
                "flags",
                "mic_unmute_thresh",
                "mic_mute_thresh",
                "mic_mute_duration",
            ):
                set_variable(self.btinfo, field, value, val_range=irange(0xFF))
            elif field == "bt_name":
                set_variable(self.btinfo, field, value, len_range=irange(32))
            elif field == "bt_mac":
                set_variable(self.btinfo, field, value, len_range=irange(6, 6))
            else:
                self.logger.error(
                    f"Unknown field {field}. "
                    f"Available fields: {', '.join(BtInfo.CONFIGURABLES)}"
                )
                sys.exit(1)
            self.logger.info(f"Successfully assigned btinfo.{field} = {value}")

    def clear_values(self):
        """Clear structure fields based on keys (variable names) from CLI args."""
        # create dummy object with default values set
        dummy: BtInfo = BtInfo()

        for field in self.args.clear_values:
            if field not in BtInfo.CONFIGURABLES:
                self.logger.error(
                    f"Unknown field {field}. "
                    f"Available fields: {', '.join(BtInfo.CONFIGURABLES)}"
                )
                sys.exit(1)
            value = getattr(dummy, field)
            setattr(self.btinfo, field, value)
            self.logger.info(f"Successfully assigned btinfo.{field} = {value}")

    def save_output(self):
        """Save the structure as standalone file and/or modified source file."""
        blob: bytes = bytes(self.btinfo)

        # Check flags and alert user just in case
        self.check_flags()

        for path in (self.args.output_path, self.args.mod_path):
            if not path:
                continue
            if path == self.args.output_path:
                self.logger.info("Saving just the struct")
            elif path == self.args.mod_path:
                self.logger.info("Injecting modified struct into source file")
                blob = bytes(
                    self.input_binary[: self.btinfo_off_start]
                    + blob
                    + self.input_binary[self.btinfo_off_end :]
                )
            if not write_and_check(path, blob):
                sys.exit(1)


if __name__ == "__main__":
    AppotechBtInfo().main()
