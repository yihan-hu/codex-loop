from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessState:
    has_exited: bool = False
    exit_code: int | None = None
    output_drained: bool = False
    failure_message: str | None = None

    def exited(self, code: int, *, output_drained: bool | None = None) -> "ProcessState":
        return ProcessState(True, int(code), self.output_drained if output_drained is None else bool(output_drained), self.failure_message)

    def drained(self) -> "ProcessState":
        return ProcessState(self.has_exited, self.exit_code, True, self.failure_message)

    def with_failure(self, message: str) -> "ProcessState":
        return ProcessState(self.has_exited, self.exit_code, self.output_drained, str(message))
