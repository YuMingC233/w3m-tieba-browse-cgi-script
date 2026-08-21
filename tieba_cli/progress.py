"""Small stderr progress renderer for the export command."""

from __future__ import annotations

import sys
from typing import TextIO


class TerminalProgress:
    def __init__(self, stream: TextIO | None = None, width: int = 24) -> None:
        self.stream = stream or sys.stderr
        self.width = width
        self._line_open = False
        self._completed: set[tuple[str, int]] = set()

    def __call__(self, stage: str, current: int, total: int) -> None:
        if total < 1:
            return
        current = min(max(current, 0), total)
        interactive = bool(getattr(self.stream, "isatty", lambda: False)())
        if not interactive:
            key = (stage, total)
            if current == total and key not in self._completed:
                self.stream.write(f"{stage}: {current}/{total}\n")
                self.stream.flush()
                self._completed.add(key)
            return

        filled = round(self.width * current / total)
        bar = "#" * filled + "-" * (self.width - filled)
        self.stream.write(f"\r{stage:<8} [{bar}] {current}/{total}")
        self.stream.flush()
        self._line_open = current < total
        if current == total:
            self.stream.write("\n")
            self.stream.flush()

    def close(self) -> None:
        if self._line_open:
            self.stream.write("\n")
            self.stream.flush()
            self._line_open = False
