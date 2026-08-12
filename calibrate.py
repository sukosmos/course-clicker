# v4
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ProbePlan:
    candidate_ms: float
    phase: str
    attempt_number: int
    max_attempts: int


@dataclass
class CalibrationSession:
    config: dict[str, Any]
    full_mode: bool = False

    max_attempts: int = field(init=False)
    target_gap_ms: float = field(init=False)
    guard_ms: float = field(init=False)
    backoff_ms: float = field(init=False)
    initial_step_ms: float = field(init=False)
    prior_ms: float = field(init=False)

    attempts: int = 0
    safe_values: list[float] = field(default_factory=list)
    early_values: list[float] = field(default_factory=list)
    state: str = "search"
    direction: int | None = None
    step_ms: float = 0.0
    current_candidate: float = 0.0
    final_offset_ms: float | None = None
    confirmation_safe_streak: int = 0
    confirmation_early_count: int = 0
    failure_reason: str = ""

    def __post_init__(self) -> None:
        c = self.config.get("calibration", {})
        self.max_attempts = min(int(c.get("max_attempts", 8)), 8)
        self.target_gap_ms = float(c.get("target_gap_ms", 2.0))
        self.guard_ms = float(c.get("guard_ms", 0.5))
        self.backoff_ms = float(c.get("backoff_ms", 1.0))

        last = c.get("last_result", {})
        if not self.full_mode and last.get("boundary_estimate_ms") is not None:
            self.prior_ms = float(last["boundary_estimate_ms"])
            self.initial_step_ms = float(c.get("quick_initial_step_ms", 8.0))
        elif not self.full_mode and self.config.get("effective_offset_ms"):
            self.prior_ms = float(self.config["effective_offset_ms"])
            self.initial_step_ms = float(c.get("quick_initial_step_ms", 8.0))
        elif not self.full_mode and self.config.get("no_early_offset_ms"):
            self.prior_ms = float(self.config["no_early_offset_ms"])
            self.initial_step_ms = float(c.get("quick_initial_step_ms", 8.0))
        else:
            self.prior_ms = float(c.get("default_guess_ms", 2000.0))
            self.initial_step_ms = float(c.get("full_initial_step_ms", 128.0))

        self.step_ms = self.initial_step_ms
        self.current_candidate = self.prior_ms

    def bracket(self) -> tuple[float, float] | None:
        if not self.safe_values or not self.early_values:
            return None
        upper = min(self.early_values)
        valid_safe = [v for v in self.safe_values if v < upper]
        if not valid_safe:
            return None
        return max(valid_safe), upper

    def _search_budget_remaining(self) -> int:
        # 마지막 2번은 confirmation에 남긴다.
        return max(0, self.max_attempts - self.attempts - 2)

    def next_probe(self) -> ProbePlan | None:
        if self.state in {"complete", "failed"}:
            return None
        if self.attempts >= self.max_attempts:
            self._fail("최대 시도 횟수 안에서 안정적인 값을 확인하지 못했습니다.")
            return None

        if self.attempts == 0:
            candidate = self.prior_ms
            phase = "INITIAL"
        elif self.state == "confirm":
            assert self.final_offset_ms is not None
            candidate = self.final_offset_ms
            phase = "CONFIRM"
        else:
            bracket = self.bracket()
            if bracket is None:
                if self.direction is None:
                    self._fail("초기 탐색 방향을 결정하지 못했습니다.")
                    return None
                candidate = self.current_candidate + self.direction * self.step_ms
                phase = "BRACKET"
            else:
                low, high = bracket
                if high - low <= self.target_gap_ms or self._search_budget_remaining() <= 0:
                    self._enter_confirmation()
                    candidate = self.final_offset_ms
                    phase = "CONFIRM"
                else:
                    candidate = (low + high) / 2.0
                    phase = "REFINE"

        return ProbePlan(
            candidate_ms=float(candidate),
            phase=phase,
            attempt_number=self.attempts + 1,
            max_attempts=self.max_attempts,
        )

    def record(self, plan: ProbePlan, safe: bool, actual_threshold_ms: float) -> None:
        if self.state in {"complete", "failed"}:
            return

        self.attempts += 1

        if plan.phase == "CONFIRM":
            if safe:
                self.confirmation_safe_streak += 1
                if self.confirmation_safe_streak >= 2:
                    self.state = "complete"
                elif self.attempts >= self.max_attempts:
                    self._fail("최종 후보를 2회 연속 SAFE로 확인하지 못했습니다.")
            else:
                self.confirmation_early_count += 1
                self.confirmation_safe_streak = 0
                assert self.final_offset_ms is not None
                self.final_offset_ms = min(
                    self.final_offset_ms,
                    actual_threshold_ms - self.backoff_ms,
                )
                if self.attempts >= self.max_attempts:
                    self._fail("최종 확인 중 EARLY가 발생했습니다.")
            return

        if safe:
            self.safe_values.append(actual_threshold_ms)
        else:
            self.early_values.append(actual_threshold_ms)

        if plan.phase == "INITIAL":
            self.direction = 1 if safe else -1
            self.current_candidate = plan.candidate_ms
        elif plan.phase == "BRACKET":
            self.current_candidate = plan.candidate_ms
            if self.bracket() is None:
                self.step_ms *= 2.0

        bracket = self.bracket()
        if bracket is not None:
            low, high = bracket
            if high - low <= self.target_gap_ms or self._search_budget_remaining() <= 0:
                self._enter_confirmation()
        elif self._search_budget_remaining() <= 0:
            self._fail("SAFE/EARLY 경계를 시도 횟수 안에서 찾지 못했습니다.")

    def _enter_confirmation(self) -> None:
        bracket = self.bracket()
        if bracket is None:
            self._fail("확인할 경계가 없습니다.")
            return
        low, _ = bracket
        self.final_offset_ms = low - self.guard_ms
        self.state = "confirm"
        self.confirmation_safe_streak = 0

    def _fail(self, reason: str) -> None:
        self.state = "failed"
        self.failure_reason = reason

    @property
    def is_complete(self) -> bool:
        return self.state == "complete"

    @property
    def is_failed(self) -> bool:
        return self.state == "failed"

    def result(self) -> dict[str, Any]:
        if not self.is_complete:
            raise RuntimeError("Calibration is not complete.")
        bracket = self.bracket()
        if bracket is None or self.final_offset_ms is None:
            raise RuntimeError("Calibration result is incomplete.")
        low, high = bracket
        return {
            "boundary_low_ms": round(low, 3),
            "boundary_high_ms": round(high, 3),
            "boundary_gap_ms": round(high - low, 3),
            "boundary_estimate_ms": round((low + high) / 2.0, 3),
            "no_early_offset_ms": round(self.final_offset_ms, 3),
            "attempts": self.attempts,
            "confirmation_safe_streak": self.confirmation_safe_streak,
            "confirmation_early_count": self.confirmation_early_count,
            "calibrated_at": datetime.now().isoformat(timespec="seconds"),
        }
