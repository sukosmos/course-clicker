from __future__ import annotations

import math
import time
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk
from typing import Any, Callable

from calibrate import CalibrationSession, ProbePlan
from ui_theme import (
    COLORS,
    FONT,
    FlatButton,
    make_button,
    make_card,
    make_toggle,
    muted_label,
    section_label,
    title_label,
)
from utils import (
    append_calibration_log,
    cancel_process,
    classify_boundary,
    cleanup_countdown,
    datetime_to_ns,
    future_wall_ns_with_fraction,
    load_config,
    ns_to_datetime,
    poll_click_result,
    prewarm_input,
    save_config,
    start_countdown,
    start_precise_click,
    validate_server_hms,
)


class ClickDialog(tk.Toplevel):
    """Shared ARM/Test dialog. Test mode exposes a configurable delay."""

    MIN_TEST_DELAY = 5
    MAX_TEST_DELAY = 30

    def __init__(
        self,
        parent: tk.Misc,
        *,
        target_server: datetime,
        target_local: datetime,
        config: dict[str, Any],
        alarm_enabled: bool,
        title: str,
        test_mode: bool,
        on_done: Callable[[], None] | None,
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.target_server = target_server
        self.target_local = target_local
        self.target_wall_ns = datetime_to_ns(target_local)
        self.config_data = config
        self.alarm_enabled = alarm_enabled
        self.test_mode = test_mode
        self.on_done = on_done

        self.test_delay_seconds = max(
            self.MIN_TEST_DELAY,
            min(
                self.MAX_TEST_DELAY,
                int(self.config_data.get("test_delay_seconds", 8)),
            ),
        )

        self.click_process = None
        self.click_queue = None
        self.alarm_process = None
        self.done = False
        self.started = False

        self.title(title)
        self.geometry("500x590" if test_mode else "500x520")
        self.resizable(False, False)
        self.configure(bg=COLORS["bg"])
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        self.body = tk.Frame(self, bg=COLORS["bg"])
        self.body.pack(fill="both", expand=True, padx=26, pady=24)

        title_label(
            self.body,
            "테스트 클릭" if test_mode else "ARMED",
            size=22,
        ).pack(anchor="w")

        muted_label(
            self.body,
            (
                "대기시간과 알람을 확인한 뒤 테스트를 시작하세요."
                if test_mode
                else "실제 클릭 타이밍 동안에는 마우스를 움직이지 마세요."
            ),
            size=9,
            wraplength=440,
        ).pack(anchor="w", pady=(4, 18))

        card = make_card(self.body)
        card.pack(fill="x")
        self.card_body = tk.Frame(card, bg=COLORS["card"])
        self.card_body.pack(fill="x", padx=18, pady=16)

        self.server_label = muted_label(
            self.card_body,
            "",
            bg=COLORS["card"],
            size=9,
        )
        self.server_label.pack(anchor="w")

        self.local_label = tk.Label(
            self.card_body,
            text="",
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=(FONT, 14, "bold"),
        )
        self.local_label.pack(anchor="w", pady=(5, 0))
        self._refresh_target_labels()

        if self.test_mode:
            self._build_test_delay_control()

        self.countdown_label = tk.Label(
            self.body,
            text="READY",
            bg=COLORS["bg"],
            fg=COLORS["text"],
            font=(FONT, 36, "bold"),
        )
        self.countdown_label.pack(pady=(28, 10))

        instruction = (
            "클릭되어도 문제없는 위치에 마우스를 올려두세요."
            if test_mode
            else "[신청] 버튼 위에 마우스를 올린 뒤 움직이지 마세요."
        )
        self.status = muted_label(
            self.body,
            instruction,
            size=10,
            justify="center",
            wraplength=430,
        )
        self.status.pack(pady=(0, 18))

        self.start_button: FlatButton = make_button(
            self.body,
            "테스트 시작" if test_mode else "ARM",
            self.start,
            kind="primary",
        )
        self.start_button.pack(fill="x", pady=(0, 8))

        make_button(self.body, "취소", self.cancel).pack(fill="x")

        self.result_label = muted_label(
            self.body,
            "",
            size=9,
            wraplength=430,
        )
        self.result_label.pack(fill="x", pady=(16, 0))
        self.grab_set()

    def _build_test_delay_control(self) -> None:
        tk.Frame(self.card_body, bg=COLORS["line"], height=1).pack(
            fill="x", pady=(15, 13)
        )
        row = tk.Frame(self.card_body, bg=COLORS["card"])
        row.pack(fill="x")

        text = tk.Frame(row, bg=COLORS["card"])
        text.pack(side="left", fill="x", expand=True)
        section_label(text, "테스트 대기시간").pack(anchor="w")
        muted_label(
            text,
            f"{self.MIN_TEST_DELAY}–{self.MAX_TEST_DELAY}초 · 마지막 값을 기억합니다.",
            bg=COLORS["card"],
        ).pack(anchor="w", pady=(3, 0))

        controls = tk.Frame(row, bg=COLORS["card"])
        controls.pack(side="right", padx=(12, 0))

        make_button(
            controls,
            "−",
            lambda: self._change_test_delay(-1),
            kind="soft",
            compact=True,
        ).pack(side="left")

        self.delay_label = tk.Label(
            controls,
            text=f"{self.test_delay_seconds} sec",
            width=7,
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=(FONT, 10, "bold"),
        )
        self.delay_label.pack(side="left", padx=6)

        make_button(
            controls,
            "+",
            lambda: self._change_test_delay(1),
            kind="soft",
            compact=True,
        ).pack(side="left")

    def _change_test_delay(self, delta: int) -> None:
        if self.started:
            return
        self.test_delay_seconds = max(
            self.MIN_TEST_DELAY,
            min(self.MAX_TEST_DELAY, self.test_delay_seconds + delta),
        )
        self.delay_label.config(text=f"{self.test_delay_seconds} sec")
        self.config_data["test_delay_seconds"] = self.test_delay_seconds
        save_config(self.config_data)

    def _refresh_target_labels(self) -> None:
        if self.test_mode:
            self.server_label.config(text="테스트 클릭")
        else:
            self.server_label.config(
                text=f"서버 목표  {self.target_server.strftime('%H:%M:%S.%f')[:-3]}"
            )
        self.local_label.config(
            text=f"PC CLICK  {self.target_local.strftime('%H:%M:%S.%f')[:-3]}"
        )

    def start(self) -> None:
        if self.started:
            return

        if self.test_mode:
            self.config_data["test_delay_seconds"] = self.test_delay_seconds
            save_config(self.config_data)
            self.target_server = datetime.now() + timedelta(seconds=self.test_delay_seconds)
            self.target_local = self.target_server
            self.target_wall_ns = datetime_to_ns(self.target_local)
            self._refresh_target_labels()
        elif self.target_local <= datetime.now():
            messagebox.showerror(
                "목표 시각 지남",
                "목표 클릭 시각이 이미 지났습니다.",
                parent=self,
            )
            return

        ok, error = prewarm_input()
        if not ok:
            messagebox.showerror("마우스 접근 오류", error, parent=self)
            return

        self.started = True
        self.start_button.set_enabled(False)

        countdown_seconds = int(
            self.config_data.get("alarm", {}).get("countdown_seconds", 3)
        )
        self.alarm_process = start_countdown(
            self.target_wall_ns,
            enabled=self.alarm_enabled,
            countdown_seconds=countdown_seconds,
        )

        spin_window_ms = float(self.config_data.get("spin_window_ms", 20.0))
        self.click_process, self.click_queue = start_precise_click(
            self.target_wall_ns,
            spin_window_ms,
        )

        self.status.config(text="목표 시각을 기다리는 중입니다.")
        self._tick()
        self._poll_result()

    def _tick(self) -> None:
        if self.done:
            return
        remaining = (self.target_wall_ns - time.time_ns()) / 1e9
        if remaining <= 0:
            self.countdown_label.config(text="CLICK", fg=COLORS["primary"])
        elif remaining <= 3.0:
            self.countdown_label.config(
                text=str(max(1, math.ceil(remaining))),
                fg=COLORS["primary"],
            )
        elif remaining <= 10:
            self.countdown_label.config(text=f"{remaining:.1f}s", fg=COLORS["text"])
        else:
            self.countdown_label.config(text="ARMED", fg=COLORS["text"])
        self.after(40, self._tick)

    def _poll_result(self) -> None:
        if self.done or self.click_process is None or self.click_queue is None:
            return
        result = poll_click_result(self.click_process, self.click_queue)
        if result is None:
            self.after(10, self._poll_result)
            return

        self.done = True
        cleanup_countdown(self.alarm_process)

        if not result.get("ok"):
            self.countdown_label.config(text="FAILED", fg=COLORS["danger"])
            self.status.config(text="클릭을 실행하지 못했습니다.")
            self.result_label.config(text=str(result.get("error", "Unknown error")))
            return

        call_dt = ns_to_datetime(result["call_ns"])
        self.countdown_label.config(text="DONE", fg=COLORS["success"])
        self.status.config(text="클릭이 실행되었습니다.")
        self.result_label.config(
            text=(
                f"click() 호출   {call_dt.strftime('%H:%M:%S.%f')[:-3]}\n"
                f"Trigger 오차   {result['trigger_error_ms']:+.3f} ms\n"
                f"click() 소요    {result['click_duration_ms']:.3f} ms"
            ),
            fg=COLORS["text"],
        )
        if self.on_done:
            self.on_done()

    def cancel(self) -> None:
        self.done = True
        cancel_process(self.click_process)
        cleanup_countdown(self.alarm_process)
        self.destroy()


class CalibrationWizard(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        config: dict[str, Any],
        on_saved: Callable[[], None] | None,
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.config_data = load_config()
        self.on_saved = on_saved

        self.session: CalibrationSession | None = None
        self.current_plan: ProbePlan | None = None
        self.pending_measurement: dict[str, Any] | None = None
        self.click_result: dict[str, Any] | None = None
        self.click_process = None
        self.click_queue = None
        self.alarm_process = None
        self.target_wall_ns: int | None = None

        self.full_mode = tk.BooleanVar(value=False)
        self.beep_var = tk.BooleanVar(
            value=bool(self.config_data.get("alarm", {}).get("enabled", True))
        )
        self.cal_beep_button: FlatButton | None = None
        self.cal_mode_button: FlatButton | None = None

        self.title("캘리브레이션")
        self.geometry("560x650")
        self.minsize(540, 620)
        self.configure(bg=COLORS["bg"])
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._close)

        self.body = tk.Frame(self, bg=COLORS["bg"])
        self.body.pack(fill="both", expand=True, padx=26, pady=24)
        self._show_intro()
        self.grab_set()

    def _clear(self) -> None:
        for widget in self.body.winfo_children():
            widget.destroy()

    def _show_intro(self) -> None:
        self._clear()
        title_label(self.body, "캘리브레이션", size=23).pack(anchor="w")
        muted_label(
            self.body,
            "최대 8회의 테스트로 early 가능성을 낮추면서 가능한 한 정각에 가까운 offset을 찾습니다.",
            size=10,
            wraplength=500,
        ).pack(anchor="w", pady=(5, 20))

        info = make_card(self.body)
        info.pack(fill="x", pady=(0, 14))
        info_body = tk.Frame(info, bg=COLORS["card"])
        info_body.pack(fill="x", padx=18, pady=16)
        section_label(info_body, "진행 방법").pack(anchor="w")
        muted_label(
            info_body,
            (
                "1. 테스트 가능한 버튼을 준비합니다.\n"
                "2. READY를 누른 뒤 버튼 위에 마우스를 둡니다.\n"
                "3. 자동 클릭 후 페이지에 표시된 HH:MM:SS를 입력합니다.\n"
                "4. 이상한 측정은 같은 라운드만 다시 할 수 있습니다."
            ),
            bg=COLORS["card"],
            size=9,
            wraplength=470,
        ).pack(anchor="w", pady=(8, 0))

        settings_card = make_card(self.body)
        settings_card.pack(fill="x", pady=(0, 18))
        settings = tk.Frame(settings_card, bg=COLORS["card"])
        settings.pack(fill="x", padx=18, pady=14)

        beep_row = tk.Frame(settings, bg=COLORS["card"])
        beep_row.pack(fill="x")
        beep_text = tk.Frame(beep_row, bg=COLORS["card"])
        beep_text.pack(side="left", fill="x", expand=True)
        section_label(beep_text, "카운트다운 beep").pack(anchor="w")
        muted_label(
            beep_text,
            "실전과 같은 조건으로 측정하려면 켜두는 것을 권장합니다.",
            bg=COLORS["card"],
        ).pack(anchor="w", pady=(3, 0))
        self.cal_beep_holder = tk.Frame(beep_row, bg=COLORS["card"])
        self.cal_beep_holder.pack(side="right", padx=(12, 0))
        self._render_calibration_beep()

        tk.Frame(settings, bg=COLORS["line"], height=1).pack(fill="x", pady=14)

        mode_row = tk.Frame(settings, bg=COLORS["card"])
        mode_row.pack(fill="x")
        mode_text = tk.Frame(mode_row, bg=COLORS["card"])
        mode_text.pack(side="left", fill="x", expand=True)
        section_label(mode_text, "보정 모드").pack(anchor="w")
        muted_label(
            mode_text,
            "같은 PC/네트워크라면 빠른 보정을 사용하세요.",
            bg=COLORS["card"],
        ).pack(anchor="w", pady=(3, 0))
        self.cal_mode_holder = tk.Frame(mode_row, bg=COLORS["card"])
        self.cal_mode_holder.pack(side="right", padx=(12, 0))
        self._render_calibration_mode()

        make_button(
            self.body,
            "캘리브레이션 시작",
            self._start_session,
            kind="primary",
        ).pack(fill="x", pady=(0, 8))
        make_button(self.body, "취소", self._close).pack(fill="x")

    def _render_calibration_beep(self) -> None:
        if self.cal_beep_button is not None:
            self.cal_beep_button.destroy()
        self.cal_beep_button = make_toggle(
            self.cal_beep_holder,
            enabled=bool(self.beep_var.get()),
            on_text="BEEP ON · 소리 남",
            off_text="BEEP OFF · 무음",
            command=self._toggle_calibration_beep,
        )
        self.cal_beep_button.pack()

    def _toggle_calibration_beep(self) -> None:
        self.beep_var.set(not self.beep_var.get())
        self._render_calibration_beep()

    def _render_calibration_mode(self) -> None:
        if self.cal_mode_button is not None:
            self.cal_mode_button.destroy()
        full = bool(self.full_mode.get())
        self.cal_mode_button = make_toggle(
            self.cal_mode_holder,
            enabled=full,
            on_text="전체 탐색",
            off_text="빠른 보정",
            command=self._toggle_calibration_mode,
        )
        self.cal_mode_button.pack()

    def _toggle_calibration_mode(self) -> None:
        self.full_mode.set(not self.full_mode.get())
        self._render_calibration_mode()

    def _start_session(self) -> None:
        ok, error = prewarm_input()
        if not ok:
            messagebox.showerror("마우스 접근 오류", error, parent=self)
            return

        self.session = CalibrationSession(
            self.config_data,
            full_mode=self.full_mode.get(),
        )
        self.config_data.setdefault("alarm", {})["enabled"] = bool(self.beep_var.get())
        save_config(self.config_data)
        self._show_next_probe()

    def _show_next_probe(self) -> None:
        assert self.session is not None
        plan = self.session.next_probe()
        if plan is None:
            if self.session.is_complete:
                self._finish_success()
            else:
                self._finish_failure(self.session.failure_reason)
            return

        self.current_plan = plan
        self.pending_measurement = None
        self.click_result = None
        self._show_probe_ready(retry=False)

    def _show_probe_ready(self, *, retry: bool) -> None:
        assert self.current_plan is not None
        plan = self.current_plan
        self._clear()

        title_label(
            self.body,
            "같은 라운드 다시 측정" if retry else "캘리브레이션",
            size=22,
        ).pack(anchor="w")
        muted_label(
            self.body,
            (
                "Candidate와 라운드 번호는 그대로 유지됩니다."
                if retry
                else "버튼 위에 마우스를 올릴 준비를 해주세요."
            ),
            size=9,
        ).pack(anchor="w", pady=(4, 16))

        progress = ttk.Progressbar(
            self.body,
            style="Course.Horizontal.TProgressbar",
            maximum=plan.max_attempts,
            value=max(0, plan.attempt_number - 1),
        )
        progress.pack(fill="x", pady=(0, 12))

        round_row = tk.Frame(self.body, bg=COLORS["bg"])
        round_row.pack(fill="x", pady=(0, 18))
        tk.Label(
            round_row,
            text=f"ROUND {plan.attempt_number} / {plan.max_attempts}",
            bg=COLORS["bg"],
            fg=COLORS["text"],
            font=(FONT, 12, "bold"),
        ).pack(side="left")

        phase_text = {
            "INITIAL": "초기 탐색",
            "BRACKET": "경계 탐색",
            "REFINE": "경계 정밀화",
            "CONFIRM": "최종 확인",
        }.get(plan.phase, "측정")
        tk.Label(
            round_row,
            text=phase_text,
            bg=COLORS["primary_soft"],
            fg=COLORS["primary"],
            font=(FONT, 9, "bold"),
            padx=9,
            pady=4,
        ).pack(side="right")

        card = make_card(self.body)
        card.pack(fill="x", pady=(0, 18))
        card_body = tk.Frame(card, bg=COLORS["card"])
        card_body.pack(fill="x", padx=18, pady=18)
        muted_label(card_body, "이번 Candidate", bg=COLORS["card"]).pack(anchor="w")
        tk.Label(
            card_body,
            text=f"{plan.candidate_ms:.3f} ms",
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=(FONT, 20, "bold"),
        ).pack(anchor="w", pady=(3, 12))
        muted_label(
            card_body,
            "READY를 누르면 창이 숨겨집니다. 브라우저로 이동해서 테스트 버튼 위에 마우스를 올려두세요.",
            bg=COLORS["card"],
            size=9,
            wraplength=470,
        ).pack(anchor="w")

        make_button(
            self.body,
            "READY · 다시 측정" if retry else "READY",
            self._run_probe,
            kind="primary",
        ).pack(fill="x", pady=(0, 8))
        make_button(self.body, "캘리브레이션 취소", self._close).pack(fill="x")

    def _run_probe(self) -> None:
        assert self.current_plan is not None
        calibration_config = self.config_data.get("calibration", {})
        prepare_seconds = float(calibration_config.get("prepare_seconds", 5.0))
        fraction_ms = (-self.current_plan.candidate_ms) % 1000.0
        self.target_wall_ns = future_wall_ns_with_fraction(
            fraction_ms,
            prepare_seconds,
        )

        countdown_seconds = int(
            self.config_data.get("alarm", {}).get("countdown_seconds", 3)
        )
        self.alarm_process = start_countdown(
            self.target_wall_ns,
            enabled=self.beep_var.get(),
            countdown_seconds=countdown_seconds,
        )

        spin_window_ms = float(self.config_data.get("spin_window_ms", 20.0))
        self.click_process, self.click_queue = start_precise_click(
            self.target_wall_ns,
            spin_window_ms,
        )
        self.withdraw()
        self._poll_probe_result()

    def _poll_probe_result(self) -> None:
        if self.click_process is None or self.click_queue is None:
            return
        result = poll_click_result(self.click_process, self.click_queue)
        if result is None:
            self.after(10, self._poll_probe_result)
            return

        cleanup_countdown(self.alarm_process)
        self.alarm_process = None
        self.click_result = result
        self.deiconify()
        self.lift()
        self.grab_set()

        if not result.get("ok"):
            self._finish_failure(str(result.get("error", "Click failed.")))
            return
        self._show_server_time_entry()

    def _show_server_time_entry(self) -> None:
        assert self.current_plan is not None
        assert self.click_result is not None
        self._clear()

        title_label(self.body, "서버 시각 입력", size=22).pack(anchor="w")
        muted_label(
            self.body,
            "자동 클릭 후 웹페이지에 표시된 HH:MM:SS 시각을 그대로 입력하세요.",
            size=10,
            wraplength=500,
        ).pack(anchor="w", pady=(4, 18))

        card = make_card(self.body)
        card.pack(fill="x", pady=(0, 16))
        card_body = tk.Frame(card, bg=COLORS["card"])
        card_body.pack(fill="x", padx=18, pady=18)
        entry_row = tk.Frame(card_body, bg=COLORS["card"])
        entry_row.pack(pady=(0, 16))

        self.hh_var = tk.StringVar()
        self.mm_var = tk.StringVar()
        self.ss_var = tk.StringVar()
        values = ((self.hh_var, "HH"), (self.mm_var, "MM"), (self.ss_var, "SS"))

        for index, (var, label) in enumerate(values):
            box = tk.Frame(entry_row, bg=COLORS["card"])
            box.grid(row=0, column=index * 2, padx=5)
            ttk.Entry(
                box,
                textvariable=var,
                width=4,
                justify="center",
                style="Course.TEntry",
                font=(FONT, 18, "bold"),
            ).pack()
            muted_label(box, label, bg=COLORS["card"]).pack(pady=(4, 0))
            if index < 2:
                tk.Label(
                    entry_row,
                    text=":",
                    bg=COLORS["card"],
                    fg=COLORS["muted"],
                    font=(FONT, 18, "bold"),
                ).grid(row=0, column=index * 2 + 1, padx=2, pady=(0, 18))

        call_dt = ns_to_datetime(self.click_result["call_ns"])
        muted_label(
            card_body,
            (
                f"PC click() 호출   {call_dt.strftime('%H:%M:%S.%f')[:-3]}\n"
                f"Trigger 오차       {self.click_result['trigger_error_ms']:+.3f} ms"
            ),
            bg=COLORS["card"],
            size=9,
        ).pack(anchor="w")

        self.error_label = tk.Label(
            self.body,
            text="",
            bg=COLORS["bg"],
            fg=COLORS["danger"],
            font=(FONT, 9, "bold"),
        )
        self.error_label.pack(anchor="w", pady=(0, 10))

        make_button(
            self.body,
            "결과 확인",
            self._submit_server_time,
            kind="primary",
        ).pack(fill="x", pady=(0, 8))
        make_button(
            self.body,
            "이 라운드 다시 측정",
            self._retry_current_round,
            kind="soft",
        ).pack(fill="x", pady=(0, 8))
        make_button(self.body, "캘리브레이션 취소", self._close).pack(fill="x")

        for var in (self.hh_var, self.mm_var, self.ss_var):
            var.trace_add("write", lambda *_args, v=var: self._limit_two_digits(v))

    def _limit_two_digits(self, var: tk.StringVar) -> None:
        value = "".join(ch for ch in var.get() if ch.isdigit())[:2]
        if value != var.get():
            var.set(value)

    def _submit_server_time(self) -> None:
        assert self.current_plan is not None
        assert self.click_result is not None

        try:
            hh = int(self.hh_var.get())
            mm = int(self.mm_var.get())
            ss = int(self.ss_var.get())
            if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
                raise ValueError
            server_hms = f"{hh:02d}:{mm:02d}:{ss:02d}"
        except ValueError:
            self.error_label.config(text="HH / MM / SS 값을 다시 확인하세요.")
            return

        valid, reason = validate_server_hms(
            server_hms,
            self.click_result["call_ns"],
        )
        if not valid:
            self.error_label.config(text=reason)
            return

        safe, threshold_ms, _ = classify_boundary(
            self.current_plan.candidate_ms,
            self.click_result["call_ns"],
            server_hms,
        )
        self.pending_measurement = {
            "safe": safe,
            "threshold_ms": threshold_ms,
            "server_hms": server_hms,
        }
        self._show_measurement_result(safe, threshold_ms, server_hms)

    def _show_measurement_result(
        self,
        safe: bool,
        threshold_ms: float,
        server_hms: str,
    ) -> None:
        assert self.current_plan is not None
        assert self.session is not None
        self._clear()

        title_label(self.body, "측정 결과 확인", size=22).pack(anchor="w")
        muted_label(
            self.body,
            "이 값을 calibration에 반영하기 전에 한 번 더 확인할 수 있습니다.",
            size=10,
        ).pack(anchor="w", pady=(4, 18))

        card = make_card(self.body)
        card.pack(fill="x", pady=(0, 18))
        card_body = tk.Frame(card, bg=COLORS["card"])
        card_body.pack(fill="x", padx=18, pady=18)

        if safe:
            status_bg = COLORS["success_soft"]
            status_fg = COLORS["success"]
            status_text = "SAFE · 이 측정에서는 early 아님"
        else:
            status_bg = COLORS["warning_soft"]
            status_fg = COLORS["warning"]
            status_text = "EARLY · 이 값은 공격적임"

        tk.Label(
            card_body,
            text=status_text,
            bg=status_bg,
            fg=status_fg,
            font=(FONT, 10, "bold"),
            padx=10,
            pady=6,
        ).pack(anchor="w")

        details = (
            f"ROUND          {self.current_plan.attempt_number} / {self.current_plan.max_attempts}\n"
            f"Candidate      {self.current_plan.candidate_ms:.3f} ms\n"
            f"서버 표시      {server_hms}\n"
            f"Threshold      {threshold_ms:.3f} ms"
        )
        muted_label(
            card_body,
            details,
            bg=COLORS["card"],
            size=9,
        ).pack(anchor="w", pady=(14, 0))

        current = self.session.bracket()
        if current:
            muted_label(
                card_body,
                f"현재까지의 boundary  {current[0]:.3f} ~ {current[1]:.3f} ms",
                bg=COLORS["card"],
                size=9,
            ).pack(anchor="w", pady=(8, 0))

        make_button(
            self.body,
            "이 결과 사용 · 다음 라운드",
            self._commit_pending_measurement,
            kind="primary",
        ).pack(fill="x", pady=(0, 8))
        make_button(
            self.body,
            "이 라운드 다시 측정",
            self._retry_current_round,
            kind="soft",
        ).pack(fill="x", pady=(0, 8))
        make_button(self.body, "캘리브레이션 취소", self._close).pack(fill="x")

    def _commit_pending_measurement(self) -> None:
        assert self.session is not None
        assert self.current_plan is not None
        assert self.click_result is not None
        assert self.pending_measurement is not None

        safe = bool(self.pending_measurement["safe"])
        threshold_ms = float(self.pending_measurement["threshold_ms"])
        server_hms = str(self.pending_measurement["server_hms"])

        append_calibration_log(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "attempt": self.current_plan.attempt_number,
                "phase": self.current_plan.phase,
                "candidate_ms": f"{self.current_plan.candidate_ms:.3f}",
                "actual_threshold_ms": f"{threshold_ms:.3f}",
                "result": "SAFE" if safe else "EARLY",
                "trigger_error_ms": f"{self.click_result['trigger_error_ms']:.3f}",
                "click_duration_ms": f"{self.click_result['click_duration_ms']:.3f}",
                "server_time": server_hms,
            }
        )

        # Only now is the round consumed.
        self.session.record(self.current_plan, safe, threshold_ms)
        self.pending_measurement = None

        if self.session.is_complete:
            self._finish_success()
        elif self.session.is_failed:
            self._finish_failure(self.session.failure_reason)
        else:
            self._show_next_probe()

    def _retry_current_round(self) -> None:
        if self.current_plan is None:
            return
        cancel_process(self.click_process)
        cleanup_countdown(self.alarm_process)
        self.click_process = None
        self.click_queue = None
        self.alarm_process = None
        self.click_result = None
        self.pending_measurement = None
        # current_plan is deliberately preserved. No session.record() => no attempt consumed.
        self._show_probe_ready(retry=True)

    def _finish_success(self) -> None:
        assert self.session is not None
        result = self.session.result()

        self.config_data["effective_offset_ms"] = result["boundary_estimate_ms"]
        self.config_data["no_early_offset_ms"] = result["no_early_offset_ms"]
        calibration = self.config_data.setdefault("calibration", {})
        calibration["version"] = 4
        calibration["last_result"] = result
        self.config_data.setdefault("alarm", {})["enabled"] = bool(self.beep_var.get())
        save_config(self.config_data)

        self._clear()
        title_label(self.body, "캘리브레이션 완료", size=22).pack(anchor="w")
        muted_label(
            self.body,
            "이 컴퓨터에서 사용할 timing 값을 저장했습니다.",
            size=10,
        ).pack(anchor="w", pady=(4, 18))

        gap = float(result["boundary_gap_ms"])
        if gap <= 2.0 and int(result["confirmation_early_count"]) == 0:
            quality = "VERY GOOD"
            q_bg = COLORS["success_soft"]
            q_fg = COLORS["success"]
        elif gap <= 5.0:
            quality = "GOOD"
            q_bg = COLORS["primary_soft"]
            q_fg = COLORS["primary"]
        else:
            quality = "USABLE"
            q_bg = COLORS["warning_soft"]
            q_fg = COLORS["warning"]

        card = make_card(self.body)
        card.pack(fill="x", pady=(0, 18))
        card_body = tk.Frame(card, bg=COLORS["card"])
        card_body.pack(fill="x", padx=18, pady=18)
        tk.Label(
            card_body,
            text=quality,
            bg=q_bg,
            fg=q_fg,
            font=(FONT, 10, "bold"),
            padx=10,
            pady=6,
        ).pack(anchor="w")
        tk.Label(
            card_body,
            text=f"{result['no_early_offset_ms']:.3f} ms",
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=(FONT, 24, "bold"),
        ).pack(anchor="w", pady=(14, 4))
        muted_label(card_body, "최종 no-early offset", bg=COLORS["card"]).pack(anchor="w")
        muted_label(
            card_body,
            (
                f"총 사용한 라운드     {result['attempts']}\n"
                f"Boundary            {result['boundary_low_ms']:.3f} ~ {result['boundary_high_ms']:.3f} ms\n"
                f"Boundary gap        {result['boundary_gap_ms']:.3f} ms\n"
                f"Confirmation EARLY  {result['confirmation_early_count']}"
            ),
            bg=COLORS["card"],
            size=9,
        ).pack(anchor="w", pady=(14, 0))

        make_button(self.body, "완료", self._done, kind="primary").pack(fill="x")

    def _finish_failure(self, reason: str) -> None:
        self._clear()
        title_label(self.body, "캘리브레이션 저장 안 됨", size=22).pack(anchor="w")
        muted_label(
            self.body,
            reason or "제한된 시도 횟수 안에서 신뢰할 수 있는 값을 얻지 못했습니다.",
            size=10,
            wraplength=500,
        ).pack(anchor="w", pady=(5, 20))

        card = make_card(self.body)
        card.pack(fill="x", pady=(0, 18))
        card_body = tk.Frame(card, bg=COLORS["card"])
        card_body.pack(fill="x", padx=18, pady=18)
        tk.Label(
            card_body,
            text="기존 calibration 값은 변경하지 않았습니다.",
            bg=COLORS["warning_soft"],
            fg=COLORS["warning"],
            font=(FONT, 10, "bold"),
            padx=10,
            pady=7,
        ).pack(anchor="w")

        make_button(
            self.body,
            "처음부터 다시 시도",
            self._show_intro,
            kind="primary",
        ).pack(fill="x", pady=(0, 8))
        make_button(self.body, "닫기", self._close).pack(fill="x")

    def _done(self) -> None:
        if self.on_saved:
            self.on_saved()
        self.destroy()

    def _close(self) -> None:
        cancel_process(self.click_process)
        cleanup_countdown(self.alarm_process)
        self.destroy()


class SettingsDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        config: dict[str, Any],
        on_saved: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        super().__init__(parent)
        self.config_data = load_config()
        self.on_saved = on_saved
        self.vars: dict[str, tk.StringVar] = {}

        self.title("고급 설정")
        self.geometry("520x700")
        self.resizable(False, False)
        self.configure(bg=COLORS["bg"])
        self.transient(parent)
        self.grab_set()

        self.body = tk.Frame(self, bg=COLORS["bg"])
        self.body.pack(fill="both", expand=True, padx=26, pady=24)
        title_label(self.body, "고급 설정", size=22).pack(anchor="w")
        muted_label(
            self.body,
            "일반 사용자는 기본값을 유지하는 것을 권장합니다.",
            size=9,
        ).pack(anchor="w", pady=(4, 18))

        self._build_settings_card()
        make_button(self.body, "저장", self.save, kind="primary").pack(
            fill="x", pady=(16, 8)
        )
        make_button(self.body, "취소", self.destroy).pack(fill="x")

    def _build_settings_card(self) -> None:
        card = make_card(self.body)
        card.pack(fill="x")
        content = tk.Frame(card, bg=COLORS["card"])
        content.pack(fill="x", padx=18, pady=16)

        section_label(content, "Timing").pack(anchor="w", pady=(0, 6))
        self._row(content, "Late margin", "late_margin_ms", self.config_data.get("late_margin_ms", 0.0), "ms")
        self._row(content, "Spin window", "spin_window_ms", self.config_data.get("spin_window_ms", 20.0), "ms")
        self._row(content, "Test delay", "test_delay_seconds", self.config_data.get("test_delay_seconds", 8), "sec")

        tk.Frame(content, bg=COLORS["line"], height=1).pack(fill="x", pady=13)
        cal = self.config_data.get("calibration", {})
        section_label(content, "캘리브레이션").pack(anchor="w", pady=(0, 6))
        self._row(content, "Maximum attempts", "max_attempts", cal.get("max_attempts", 8), "≤ 8")
        self._row(content, "Target gap", "target_gap_ms", cal.get("target_gap_ms", 2.0), "ms")
        self._row(content, "Guard", "guard_ms", cal.get("guard_ms", 0.5), "ms")
        self._row(content, "Backoff", "backoff_ms", cal.get("backoff_ms", 1.0), "ms")

        tk.Frame(content, bg=COLORS["line"], height=1).pack(fill="x", pady=13)
        alarm = self.config_data.get("alarm", {})
        section_label(content, "알람").pack(anchor="w", pady=(0, 8))

        self.alarm_enabled = tk.BooleanVar(value=bool(alarm.get("enabled", True)))
        alarm_row = tk.Frame(content, bg=COLORS["card"])
        alarm_row.pack(fill="x", pady=4)
        muted_label(
            alarm_row,
            "카운트다운 알람",
            bg=COLORS["card"],
            size=9,
        ).pack(side="left")
        self.alarm_holder = tk.Frame(alarm_row, bg=COLORS["card"])
        self.alarm_holder.pack(side="right")
        self.alarm_toggle_button: FlatButton | None = None
        self._render_alarm_setting()
        self._row(content, "Countdown", "countdown_seconds", alarm.get("countdown_seconds", 3), "sec")

    def _row(
        self,
        parent: tk.Misc,
        label: str,
        key: str,
        value: Any,
        suffix: str,
    ) -> None:
        row = tk.Frame(parent, bg=COLORS["card"])
        row.pack(fill="x", pady=4)
        muted_label(row, label, bg=COLORS["card"], size=9).pack(side="left")
        right = tk.Frame(row, bg=COLORS["card"])
        right.pack(side="right")
        var = tk.StringVar(value=str(value))
        self.vars[key] = var
        ttk.Entry(
            right,
            textvariable=var,
            width=9,
            justify="right",
            style="Course.TEntry",
        ).pack(side="left")
        muted_label(right, suffix, bg=COLORS["card"], size=9).pack(side="left", padx=(7, 0))

    def _render_alarm_setting(self) -> None:
        if self.alarm_toggle_button is not None:
            self.alarm_toggle_button.destroy()
        self.alarm_toggle_button = make_toggle(
            self.alarm_holder,
            enabled=bool(self.alarm_enabled.get()),
            on_text="ON · 소리 남",
            off_text="OFF · 무음",
            command=self._toggle_alarm_setting,
        )
        self.alarm_toggle_button.pack()

    def _toggle_alarm_setting(self) -> None:
        self.alarm_enabled.set(not self.alarm_enabled.get())
        self._render_alarm_setting()

    def save(self) -> None:
        try:
            late_margin = float(self.vars["late_margin_ms"].get())
            spin_window = float(self.vars["spin_window_ms"].get())
            test_delay = int(self.vars["test_delay_seconds"].get())
            max_attempts = min(8, max(4, int(self.vars["max_attempts"].get())))
            target_gap = float(self.vars["target_gap_ms"].get())
            guard = float(self.vars["guard_ms"].get())
            backoff = float(self.vars["backoff_ms"].get())
            countdown = max(0, min(10, int(self.vars["countdown_seconds"].get())))
        except ValueError:
            messagebox.showerror("잘못된 설정", "숫자만 입력하세요.", parent=self)
            return

        if not (ClickDialog.MIN_TEST_DELAY <= test_delay <= ClickDialog.MAX_TEST_DELAY):
            messagebox.showerror(
                "잘못된 설정",
                f"Test delay는 {ClickDialog.MIN_TEST_DELAY}~{ClickDialog.MAX_TEST_DELAY}초여야 합니다.",
                parent=self,
            )
            return
        if spin_window <= 0 or target_gap <= 0 or guard < 0 or backoff <= 0:
            messagebox.showerror(
                "잘못된 설정",
                "Spin window / Target gap / Backoff는 0보다 커야 하고 Guard는 0 이상이어야 합니다.",
                parent=self,
            )
            return

        self.config_data["late_margin_ms"] = late_margin
        self.config_data["spin_window_ms"] = spin_window
        self.config_data["test_delay_seconds"] = test_delay
        cal = self.config_data.setdefault("calibration", {})
        cal["max_attempts"] = max_attempts
        cal["target_gap_ms"] = target_gap
        cal["guard_ms"] = guard
        cal["backoff_ms"] = backoff
        alarm = self.config_data.setdefault("alarm", {})
        alarm["enabled"] = bool(self.alarm_enabled.get())
        alarm["countdown_seconds"] = countdown
        save_config(self.config_data)

        if self.on_saved:
            self.on_saved(self.config_data)
        self.destroy()
