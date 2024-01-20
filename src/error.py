# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2024 arzamas-16 <https://github.com/arzamas-16>

"""An attempt to make errors more generic and consistent in the project."""


class AppotechError(Exception):  # noqa: D101
    pass


class AppotechTruncatedError(AppotechError):  # noqa: D101
    def __init__(self, expected_bytes: int, actual_bytes: int):
        self.expected_bytes: int = expected_bytes
        self.actual_bytes: int = actual_bytes
        super().__init__(
            f"Truncated data: expected {expected_bytes} bytes, "
            f"got {actual_bytes} bytes"
        )
