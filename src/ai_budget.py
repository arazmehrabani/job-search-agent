from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any


class AIBudgetExceeded(RuntimeError):
    """Raised before an AI subprocess/API call when a local safety budget is exhausted."""


@dataclass
class BudgetSnapshot:
    locked: bool
    lock_reason: str
    max_calls_per_run: int
    max_estimated_input_tokens_per_run: int
    max_failed_calls_per_run: int
    calls_started: int
    estimated_input_tokens_reserved: int
    failures: int
    blocked_calls: int
    remaining_calls: int
    remaining_estimated_input_tokens: int
    usage_hint_percent: float | None
    usage_hint_resets_on: str
    allowance_period_started_on: str
    ledger_file: str
    ledger_calls_today: int
    ledger_input_tokens_today: int
    ledger_calls_allowance_period: int
    ledger_input_tokens_allowance_period: int
    max_provider_calls_per_day: int
    max_provider_calls_per_allowance_period: int
    max_estimated_input_tokens_per_day: int
    max_estimated_input_tokens_per_allowance_period: int
    ledger_warning: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AIBudgetGuard:
    """Fail-closed local safety rail for Codex/API usage.

    The guard deliberately does not pretend to know OpenAI's official plan accounting.
    It enforces four independent local controls before a provider process can start:

    * a manually maintained remaining-percent hint from the official usage UI;
    * hard per-run call/input ceilings;
    * a failure circuit breaker;
    * a small cross-project ledger stored in the user's home directory, so copying the
      agent into a new version folder does not silently reset daily/allowance-period
      safety limits.

    The ledger counts provider *attempts*, not merely successful calls. Failed provider
    calls can still consume time/allowance, so counting only successes would be unsafe.
    """

    def __init__(self, cfg: dict):
        acfg = (cfg or {}).get("ai", {}) or {}
        bcfg = acfg.get("budget", {}) or {}
        self.enabled = bool(bcfg.get("enabled", True))
        self.max_calls = max(0, int(bcfg.get("max_calls_per_run", 4) or 0))
        self.max_input = max(0, int(bcfg.get("max_estimated_input_tokens_per_run", 35000) or 0))
        self.max_failures = max(0, int(bcfg.get("max_failed_calls_per_run", 1) or 0))
        self.pause_below = float(bcfg.get("pause_below_remaining_percent", 10) or 0)
        self.manual_pause = bool(bcfg.get("manual_pause", False))
        self.hint_file = Path(str(bcfg.get("usage_hint_file", "input/codex_usage_hint.json") or "input/codex_usage_hint.json")).expanduser()

        # Cross-version/cross-folder limits. New names are attempt-based. The old
        # successful-call keys are accepted as fallbacks for backwards compatibility.
        self.max_day_calls = max(0, int(
            bcfg.get("max_provider_calls_per_day", bcfg.get("max_successful_calls_per_day", 4)) or 0
        ))
        self.max_period_calls = max(0, int(
            bcfg.get("max_provider_calls_per_allowance_period", bcfg.get("max_successful_calls_per_calendar_month", 12)) or 0
        ))
        self.max_day_input = max(0, int(bcfg.get("max_estimated_input_tokens_per_day", 35000) or 0))
        self.max_period_input = max(0, int(bcfg.get("max_estimated_input_tokens_per_allowance_period", 90000) or 0))
        ledger_raw = str(bcfg.get("ledger_file", "~/.job_search_agent/codex_budget_ledger.jsonl") or "~/.job_search_agent/codex_budget_ledger.jsonl")
        self.ledger_file = Path(ledger_raw).expanduser()
        self.ledger_fail_closed = bool(bcfg.get("ledger_fail_closed", True))

        self.calls_started = 0
        self.input_reserved = 0
        self.failures = 0
        self.blocked_calls = 0
        self.usage_hint_percent: float | None = None
        self.usage_hint_resets_on = ""
        self.allowance_period_started_on = ""
        self.lock_reason = ""
        self.external_lock_reason = ""
        self.ledger_warning = ""
        self._read_usage_hint()
        self._refresh_lock()

    def _read_usage_hint(self) -> None:
        if not self.hint_file.exists():
            return
        try:
            data = json.loads(self.hint_file.read_text(encoding="utf-8"))
            raw = data.get("remaining_percent")
            self.usage_hint_percent = None if raw is None else float(raw)
            self.usage_hint_resets_on = str(data.get("resets_on", "") or "").strip()
            self.allowance_period_started_on = str(data.get("period_started_on", "") or "").strip()
        except Exception:
            self.usage_hint_percent = None
            self.usage_hint_resets_on = ""
            self.allowance_period_started_on = ""

    def _ledger_stats(self) -> dict[str, int]:
        stats = {
            "calls_today": 0,
            "input_tokens_today": 0,
            "calls_period": 0,
            "input_tokens_period": 0,
        }
        if not self.ledger_file.exists():
            return stats
        today = date.today()
        try:
            period_start = date.fromisoformat(self.allowance_period_started_on) if self.allowance_period_started_on else today.replace(day=1)
        except Exception:
            period_start = today.replace(day=1)
        try:
            with self.ledger_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        ts = datetime.fromisoformat(str(row.get("timestamp", ""))).astimezone()
                        d = ts.date()
                        tokens = max(0, int(row.get("estimated_input_tokens", 0) or 0))
                    except Exception:
                        continue
                    if d == today:
                        stats["calls_today"] += 1
                        stats["input_tokens_today"] += tokens
                    if d >= period_start:
                        stats["calls_period"] += 1
                        stats["input_tokens_period"] += tokens
            self.ledger_warning = ""
        except Exception as exc:
            self.ledger_warning = f"Could not read global AI ledger: {exc}"
        return stats

    def _append_ledger_attempt(self, operation: str, estimated_input_tokens: int) -> None:
        try:
            self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
            row = {
                "timestamp": datetime.now().astimezone().isoformat(),
                "operation": str(operation),
                "estimated_input_tokens": max(0, int(estimated_input_tokens)),
            }
            with self.ledger_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.ledger_warning = ""
        except Exception as exc:
            self.ledger_warning = f"Could not write global AI ledger: {exc}"
            if self.ledger_fail_closed:
                raise AIBudgetExceeded(
                    f"{operation}: global AI usage ledger could not be written; provider call blocked fail-closed: {exc}"
                )

    def _rolling_lock_reason(self) -> str:
        if not self.enabled:
            return ""
        stats = self._ledger_stats()
        if self.ledger_warning and self.ledger_fail_closed:
            return self.ledger_warning + " (fail-closed)"
        if self.max_day_calls and stats["calls_today"] >= self.max_day_calls:
            return f"Global local daily provider-call ceiling reached ({stats['calls_today']}/{self.max_day_calls} attempts today)."
        if self.max_period_calls and stats["calls_period"] >= self.max_period_calls:
            return (
                "Global local allowance-period provider-call ceiling reached "
                f"({stats['calls_period']}/{self.max_period_calls} attempts since {self.allowance_period_started_on or 'period start'})."
            )
        if self.max_day_input and stats["input_tokens_today"] >= self.max_day_input:
            return f"Global local daily estimated-input ceiling reached ({stats['input_tokens_today']}/{self.max_day_input})."
        if self.max_period_input and stats["input_tokens_period"] >= self.max_period_input:
            return (
                "Global local allowance-period estimated-input ceiling reached "
                f"({stats['input_tokens_period']}/{self.max_period_input})."
            )
        return ""

    def _refresh_lock(self) -> None:
        self.lock_reason = ""
        if self.external_lock_reason:
            self.lock_reason = self.external_lock_reason
            return
        if not self.enabled:
            return
        if self.manual_pause:
            self.lock_reason = "AI budget is manually paused in config."
            return
        if self.usage_hint_percent is not None:
            if self.usage_hint_resets_on:
                try:
                    if date.today() >= date.fromisoformat(self.usage_hint_resets_on):
                        self.lock_reason = (
                            f"Codex usage hint expired on {self.usage_hint_resets_on}; update {self.hint_file} "
                            "from the official Usage UI before allowing new AI calls."
                        )
                        return
                except Exception:
                    pass
            if self.usage_hint_percent <= self.pause_below:
                self.lock_reason = (
                    f"Codex remaining-usage hint is {self.usage_hint_percent:g}%, at/below the local safety threshold "
                    f"of {self.pause_below:g}%. Update {self.hint_file} after the official allowance resets."
                )
                return
        rolling = self._rolling_lock_reason()
        if rolling:
            self.lock_reason = rolling

    def force_lock(self, reason: str) -> None:
        self.external_lock_reason = str(reason or "Local AI budget lock")
        self._refresh_lock()

    @property
    def locked(self) -> bool:
        self._refresh_lock()
        return bool(self.lock_reason)

    def remaining_calls(self) -> int:
        if not self.enabled:
            return 10**9
        self._refresh_lock()
        if self.lock_reason:
            return 0
        if self.max_failures and self.failures >= self.max_failures:
            return 0
        run_remaining = max(0, self.max_calls - self.calls_started)
        stats = self._ledger_stats()
        if self.max_day_calls:
            run_remaining = min(run_remaining, max(0, self.max_day_calls - stats["calls_today"]))
        if self.max_period_calls:
            run_remaining = min(run_remaining, max(0, self.max_period_calls - stats["calls_period"]))
        return run_remaining

    def remaining_input_tokens(self) -> int:
        if not self.enabled:
            return 10**12
        run_remaining = max(0, self.max_input - self.input_reserved)
        stats = self._ledger_stats()
        if self.max_day_input:
            run_remaining = min(run_remaining, max(0, self.max_day_input - stats["input_tokens_today"]))
        if self.max_period_input:
            run_remaining = min(run_remaining, max(0, self.max_period_input - stats["input_tokens_period"]))
        return run_remaining

    def reserve(self, operation: str, estimated_input_tokens: int) -> None:
        if not self.enabled:
            return
        self._refresh_lock()
        estimated_input_tokens = max(0, int(estimated_input_tokens))
        reason = ""
        if self.lock_reason:
            reason = self.lock_reason
        elif self.calls_started >= self.max_calls:
            reason = f"Hard AI call ceiling reached ({self.max_calls} calls/run)."
        elif self.input_reserved + estimated_input_tokens > self.max_input:
            reason = (
                f"Hard estimated-input ceiling would be exceeded: {self.input_reserved + estimated_input_tokens} "
                f"> {self.max_input} tokens/run."
            )
        elif self.max_failures and self.failures >= self.max_failures:
            reason = f"AI failure circuit breaker opened after {self.failures} failed call(s)."
        else:
            stats = self._ledger_stats()
            if self.max_day_calls and stats["calls_today"] + 1 > self.max_day_calls:
                reason = f"Daily provider-call ceiling would be exceeded ({stats['calls_today'] + 1}>{self.max_day_calls})."
            elif self.max_period_calls and stats["calls_period"] + 1 > self.max_period_calls:
                reason = f"Allowance-period provider-call ceiling would be exceeded ({stats['calls_period'] + 1}>{self.max_period_calls})."
            elif self.max_day_input and stats["input_tokens_today"] + estimated_input_tokens > self.max_day_input:
                reason = "Daily estimated-input ceiling would be exceeded."
            elif self.max_period_input and stats["input_tokens_period"] + estimated_input_tokens > self.max_period_input:
                reason = "Allowance-period estimated-input ceiling would be exceeded."
        if reason:
            self.blocked_calls += 1
            raise AIBudgetExceeded(f"{operation}: {reason}")

        # Write the cross-project attempt ledger BEFORE the provider starts. If the
        # ledger cannot be persisted and fail-closed is enabled, no provider call occurs.
        self._append_ledger_attempt(operation, estimated_input_tokens)
        self.calls_started += 1
        self.input_reserved += estimated_input_tokens

    def record_result(self, success: bool) -> None:
        if self.enabled and not success:
            self.failures += 1

    def snapshot(self) -> dict[str, Any]:
        self._refresh_lock()
        stats = self._ledger_stats()
        return BudgetSnapshot(
            locked=bool(self.lock_reason),
            lock_reason=self.lock_reason,
            max_calls_per_run=self.max_calls,
            max_estimated_input_tokens_per_run=self.max_input,
            max_failed_calls_per_run=self.max_failures,
            calls_started=self.calls_started,
            estimated_input_tokens_reserved=self.input_reserved,
            failures=self.failures,
            blocked_calls=self.blocked_calls,
            remaining_calls=self.remaining_calls(),
            remaining_estimated_input_tokens=self.remaining_input_tokens(),
            usage_hint_percent=self.usage_hint_percent,
            usage_hint_resets_on=self.usage_hint_resets_on,
            allowance_period_started_on=self.allowance_period_started_on,
            ledger_file=str(self.ledger_file),
            ledger_calls_today=stats["calls_today"],
            ledger_input_tokens_today=stats["input_tokens_today"],
            ledger_calls_allowance_period=stats["calls_period"],
            ledger_input_tokens_allowance_period=stats["input_tokens_period"],
            max_provider_calls_per_day=self.max_day_calls,
            max_provider_calls_per_allowance_period=self.max_period_calls,
            max_estimated_input_tokens_per_day=self.max_day_input,
            max_estimated_input_tokens_per_allowance_period=self.max_period_input,
            ledger_warning=self.ledger_warning,
        ).to_dict()
