from __future__ import annotations

import multiprocessing as mp
import platform
import subprocess
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk
from typing import Any

from calibrate import CalibrationSession, ProbePlan
from utils import (
    CONFIG_PATH,
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


APP_TITLE = "Course Clicker"


def format_ms(value: float) -> str:
    return f"{value:.3f} ms"


class CourseClickerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("520x640")
        self.minsize(500, 610)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.config_data = load_config()
        save_config(self.config_data)

        self._setup_style()
        self._build_main()
        self.refresh_status()

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("TkDefaultFont", 22, "bold"))
        style.configure("Section.TLabel", font=("TkDefaultFont", 12, "bold"))
        style.configure("Status.TLabel", font=("TkDefaultFont", 11, "bold"))
        style.configure("Big.TButton", font=("TkDefaultFont", 13, "bold"), padding=(10, 12))
        style.configure("Main.TFrame", padding=20)

    def _build_main(self) -> None:
        main = ttk.Frame(self, style="Main.TFrame")
        main.pack(fill="both", expand=True)

        ttk.Label(main, text=APP_TITLE, style="Title.TLabel").pack(pady=(4, 20))

        status_box = ttk.LabelFrame(main, text="캘리브레이션", padding=14)
        status_box.pack(fill="x", pady=(0, 16))

        self.status_label = ttk.Label(status_box, text="", style="Status.TLabel")
        self.status_label.pack(anchor="w")

        self.status_detail = ttk.Label(status_box, text="", justify="left")
        self.status_detail.pack(anchor="w", pady=(6, 0))

        target_box = ttk.LabelFrame(main, text="목표 시각", padding=14)
        target_box.pack(fill="x", pady=(0, 16))

        target_row = ttk.Frame(target_box)
        target_row.pack(fill="x")

        initial_target = self._parse_target_or_default()
        self.date_var = tk.StringVar(value=initial_target.strftime("%Y-%m-%d"))
        self.time_var = tk.StringVar(value=initial_target.strftime("%H:%M:%S"))

        ttk.Label(target_row, text="날짜").grid(row=0, column=0, sticky="w")
        ttk.Entry(target_row, textvariable=self.date_var, width=14).grid(row=1, column=0, padx=(0, 12), sticky="w")
        ttk.Label(target_row, text="시간").grid(row=0, column=1, sticky="w")
        ttk.Entry(target_row, textvariable=self.time_var, width=12).grid(row=1, column=1, sticky="w")

        alarm_row = ttk.Frame(target_box)
        alarm_row.pack(fill="x", pady=(14, 0))
        self.alarm_var = tk.BooleanVar(value=bool(self.config_data.get("alarm", {}).get("enabled", True)))
        ttk.Checkbutton(
            alarm_row,
            text="3초 카운트다운 알람",
            variable=self.alarm_var,
            command=self._save_alarm_toggle,
        ).pack(side="left")

        button_box = ttk.Frame(main)
        button_box.pack(fill="x", pady=(4, 0))
        button_box.columnconfigure(0, weight=1)
        button_box.columnconfigure(1, weight=1)

        ttk.Button(
            button_box,
            text="캘리브레이션",
            style="Big.TButton",
            command=self.open_calibration,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=6)

        ttk.Button(
            button_box,
            text="테스트 클릭",
            style="Big.TButton",
            command=self.start_test_click,
        ).grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=6)

        ttk.Button(
            main,
            text="ARM",
            style="Big.TButton",
            command=self.arm_real_click,
        ).pack(fill="x", pady=(12, 6))

        footer = ttk.Frame(main)
        footer.pack(fill="x", pady=(18, 0))
        ttk.Button(footer, text="고급 설정", command=self.open_settings).pack(side="left")
        if platform.system() == "Darwin":
            ttk.Button(footer, text="접근성 도움말", command=self.open_accessibility_help).pack(side="right")

        self.info_label = ttk.Label(main, text="", justify="left")
        self.info_label.pack(fill="x", pady=(18, 0))

    def _parse_target_or_default(self) -> datetime:
        value = self.config_data.get("target_datetime", "")
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return (datetime.now() + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

    def _save_alarm_toggle(self) -> None:
        self.config_data.setdefault("alarm", {})["enabled"] = bool(self.alarm_var.get())
        save_config(self.config_data)

    def refresh_status(self) -> None:
        self.config_data = load_config()
        cal = self.config_data.get("calibration", {}).get("last_result", {})
        offset = float(self.config_data.get("no_early_offset_ms", 0.0) or 0.0)

        if not cal or offset <= 0:
            self.status_label.config(text="○ 캘리브레이션 필요")
            self.status_detail.config(text="실전 실행 전에 캘리브레이션을 진행하세요.")
        else:
            age_text = ""
            try:
                calibrated_at = datetime.fromisoformat(cal["calibrated_at"])
                age = datetime.now() - calibrated_at
                if age.total_seconds() < 2 * 3600:
                    freshness = "준비 완료"
                elif age.total_seconds() < 24 * 3600:
                    freshness = "재캘리브레이션 권장"
                else:
                    freshness = "재캘리브레이션 강력 권장"
                if age.total_seconds() < 3600:
                    age_text = f"{max(1, int(age.total_seconds() // 60))} min ago"
                else:
                    age_text = f"{age.total_seconds() / 3600:.1f} h ago"
            except Exception:
                freshness = "준비 완료"

            self.status_label.config(text=f"● {freshness}")
            gap = cal.get("boundary_gap_ms")
            details = [f"Offset: {offset:.3f} ms"]
            if gap is not None:
                details.append(f"Boundary gap: {float(gap):.3f} ms")
            if age_text:
                details.append(f"Last calibrated: {age_text}")
            self.status_detail.config(text="\n".join(details))

        self.info_label.config(
            text=f"Config: {CONFIG_PATH}\n"
                 "Use Test Click once before registration to verify mouse permission, alarm, and timing."
        )

    def _read_target(self) -> datetime | None:
        try:
            return datetime.strptime(
                f"{self.date_var.get().strip()} {self.time_var.get().strip()}",
                "%Y-%m-%d %H:%M:%S",
            )
        except ValueError:
            messagebox.showerror("잘못된 목표 시각", "날짜는 YYYY-MM-DD, 시간은 HH:MM:SS 형식으로 입력하세요.", parent=self)
            return None

    def start_test_click(self) -> None:
        target = datetime.now() + timedelta(seconds=8)
        ClickDialog(
            self,
            target_server=target,
            target_local=target,
            config=self.config_data,
            alarm_enabled=self.alarm_var.get(),
            title="테스트 클릭",
            test_mode=True,
            on_done=self.refresh_status,
        )

    def arm_real_click(self) -> None:
        target_server = self._read_target()
        if target_server is None:
            return
        if target_server <= datetime.now():
            messagebox.showerror("목표 시각 지남", "선택한 목표 시각이 이미 지났습니다.", parent=self)
            return

        offset = float(self.config_data.get("no_early_offset_ms", 0.0) or 0.0)
        if offset <= 0:
            if not messagebox.askyesno(
                "캘리브레이션 없음",
                "유효한 no-early 캘리브레이션 값이 없습니다. 보정값 없이 계속할까요?",
                parent=self,
            ):
                return

        late_margin = float(self.config_data.get("late_margin_ms", 0.0))
        target_local = target_server - timedelta(milliseconds=offset) + timedelta(milliseconds=late_margin)

        self.config_data["target_datetime"] = target_server.strftime("%Y-%m-%d %H:%M:%S")
        self.config_data.setdefault("alarm", {})["enabled"] = bool(self.alarm_var.get())
        save_config(self.config_data)

        ClickDialog(
            self,
            target_server=target_server,
            target_local=target_local,
            config=self.config_data,
            alarm_enabled=self.alarm_var.get(),
            title="ARMED",
            test_mode=False,
            on_done=self.refresh_status,
        )

    def open_calibration(self) -> None:
        CalibrationWizard(self, self.config_data, on_saved=self.refresh_status)

    def open_settings(self) -> None:
        SettingsDialog(self, self.config_data, on_saved=self._settings_saved)

    def _settings_saved(self, config: dict[str, Any]) -> None:
        self.config_data = config
        self.alarm_var.set(bool(config.get("alarm", {}).get("enabled", True)))
        self.refresh_status()

    def open_accessibility_help(self) -> None:
        messagebox.showinfo(
            "Accessibility",
            "macOS may require permission for Course Clicker to control the mouse.\n\n"
            "System Settings → Privacy & Security → Accessibility\n\n"
            "When packaged as an app, enable Course Clicker itself.",
            parent=self,
        )
        try:
            subprocess.Popen([
                "open",
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            ])
        except Exception:
            pass


class ClickDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        target_server: datetime,
        target_local: datetime,
        config: dict[str, Any],
        alarm_enabled: bool,
        title: str,
        test_mode: bool,
        on_done,
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.target_server = target_server
        self.target_local = target_local
        self.target_wall_ns = datetime_to_ns(target_local)
        self.config = config
        self.alarm_enabled = alarm_enabled
        self.test_mode = test_mode
        self.on_done = on_done

        self.click_process = None
        self.click_queue = None
        self.alarm_process = None
        self.done = False
        self.started = False

        self.title(title)
        self.geometry("460x430")
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        frame = ttk.Frame(self, padding=22)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="테스트 모드" if test_mode else "ARMED", style="Title.TLabel").pack(pady=(0, 16))

        ttk.Label(frame, text=f"서버 목표: {target_server.strftime('%H:%M:%S.%f')[:-3]}").pack()
        ttk.Label(frame, text=f"PC 클릭:   {target_local.strftime('%H:%M:%S.%f')[:-3]}").pack(pady=(4, 0))

        self.countdown_label = ttk.Label(frame, text="", font=("TkDefaultFont", 30, "bold"))
        self.countdown_label.pack(pady=(30, 14))

        instruction = (
            "클릭되어도 문제없는 위치에 마우스를 올려두세요."
            if test_mode
            else "[신청] 버튼 위에 마우스를 올린 뒤 움직이지 마세요."
        )
        ttk.Label(frame, text=instruction, justify="center").pack(pady=(0, 16))

        self.status = ttk.Label(frame, text="준비 완료")
        self.status.pack(pady=(0, 14))

        self.start_button = ttk.Button(frame, text="시작", style="Big.TButton", command=self.start)
        self.start_button.pack(fill="x", pady=(0, 8))
        ttk.Button(frame, text="취소", command=self.cancel).pack(fill="x")

        self.result_label = ttk.Label(frame, text="", justify="left")
        self.result_label.pack(fill="x", pady=(18, 0))

        self.grab_set()

    def start(self) -> None:
        if self.started:
            return
        if time_left := (self.target_local - datetime.now()).total_seconds():
            if time_left <= 0:
                messagebox.showerror("목표 시각 지남", "The target time has already passed.", parent=self)
                return

        ok, error = prewarm_input()
        if not ok:
            messagebox.showerror("마우스 접근 오류", error, parent=self)
            return

        self.started = True
        self.start_button.config(state="disabled")
        countdown_seconds = int(self.config.get("alarm", {}).get("countdown_seconds", 3))
        self.alarm_process = start_countdown(
            self.target_wall_ns,
            enabled=self.alarm_enabled,
            countdown_seconds=countdown_seconds,
        )
        spin_window_ms = float(self.config.get("spin_window_ms", 20.0))
        self.click_process, self.click_queue = start_precise_click(self.target_wall_ns, spin_window_ms)
        self.status.config(text="목표 시각 대기 중…")
        self._tick()
        self._poll_result()

    def _tick(self) -> None:
        if self.done:
            return
        remaining = (self.target_wall_ns - __import__("time").time_ns()) / 1e9
        if remaining <= 0:
            self.countdown_label.config(text="CLICK")
        elif remaining <= 3.2:
            self.countdown_label.config(text=str(max(1, int(remaining) + 1)))
        else:
            self.countdown_label.config(text=f"{remaining:0.1f}s")
        self.after(50, self._tick)

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
            self.status.config(text="클릭 실패")
            self.result_label.config(text=result.get("error", "Unknown error"))
            return

        call_dt = ns_to_datetime(result["call_ns"])
        self.status.config(text="✓ 클릭 완료")
        self.result_label.config(
            text=(
                f"click() 호출: {call_dt.strftime('%H:%M:%S.%f')[:-3]}\n"
                f"Trigger 오차: {result['trigger_error_ms']:+.3f} ms\n"
                f"click() 소요: {result['click_duration_ms']:.3f} ms"
            )
        )
        if self.on_done:
            self.on_done()

    def cancel(self) -> None:
        self.done = True
        cancel_process(self.click_process)
        cleanup_countdown(self.alarm_process)
        self.destroy()


class CalibrationWizard(tk.Toplevel):
    def __init__(self, parent: CourseClickerApp, config: dict[str, Any], on_saved) -> None:
        super().__init__(parent)
        self.parent = parent
        self.config_data = load_config()
        self.on_saved = on_saved
        self.session: CalibrationSession | None = None
        self.current_plan: ProbePlan | None = None
        self.click_result: dict[str, Any] | None = None
        self.click_process = None
        self.click_queue = None
        self.alarm_process = None
        self.target_wall_ns: int | None = None
        self.full_mode = tk.BooleanVar(value=False)
        self.beep_var = tk.BooleanVar(value=bool(self.config_data.get("alarm", {}).get("enabled", True)))

        self.title("캘리브레이션")
        self.geometry("520x560")
        self.minsize(500, 540)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._close)

        self.body = ttk.Frame(self, padding=22)
        self.body.pack(fill="both", expand=True)
        self._show_intro()
        self.grab_set()

    def _clear(self) -> None:
        for widget in self.body.winfo_children():
            widget.destroy()

    def _show_intro(self) -> None:
        self._clear()
        ttk.Label(self.body, text="캘리브레이션", style="Title.TLabel").pack(pady=(0, 16))
        ttk.Label(
            self.body,
            text=(
                "The program will estimate a fast no-early offset using at most 8 test clicks.\n\n"
                "For each trial, prepare a harmless button on the registration page. After the automatic click, "
                "enter the HH:MM:SS timestamp shown by the page."
            ),
            justify="left",
            wraplength=450,
        ).pack(fill="x", pady=(0, 18))

        ttk.Checkbutton(self.body, text="카운트다운 beep", variable=self.beep_var).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            self.body,
            text="Full calibration (PC/네트워크 환경이 크게 바뀐 경우)",
            variable=self.full_mode,
        ).pack(anchor="w", pady=4)

        ttk.Label(
            self.body,
            text="각 테스트 클릭 동안 창은 자동으로 숨겨져 브라우저를 가리지 않습니다.",
            wraplength=450,
        ).pack(fill="x", pady=(18, 22))

        ttk.Button(self.body, text="캘리브레이션 시작", style="Big.TButton", command=self._start_session).pack(fill="x")
        ttk.Button(self.body, text="취소", command=self._close).pack(fill="x", pady=(8, 0))

    def _start_session(self) -> None:
        ok, error = prewarm_input()
        if not ok:
            messagebox.showerror("마우스 접근 오류", error, parent=self)
            return
        self.session = CalibrationSession(self.config_data, full_mode=self.full_mode.get())
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
        self.click_result = None
        self._clear()

        ttk.Label(self.body, text="캘리브레이션", style="Title.TLabel").pack(pady=(0, 12))
        ttk.Label(
            self.body,
            text=f"테스트 {plan.attempt_number} / {plan.max_attempts}",
            style="Section.TLabel",
        ).pack()

        user_phase = {
            "INITIAL": "대략적인 타이밍 영역 탐색",
            "BRACKET": "SAFE/EARLY 경계 탐색",
            "REFINE": "경계 정밀화",
            "CONFIRM": "최종 안전성 확인",
        }.get(plan.phase, "캘리브레이션")
        ttk.Label(self.body, text=user_phase).pack(pady=(6, 18))

        ttk.Label(
            self.body,
            text="수강신청 페이지에서 테스트 버튼 위에 마우스를 올려두세요.\nREADY를 누르면 창이 숨겨지고 자동 클릭이 실행됩니다.",
            justify="center",
            wraplength=450,
        ).pack(pady=(0, 18))

        details = ttk.LabelFrame(self.body, text="상세 정보", padding=10)
        details.pack(fill="x", pady=(0, 18))
        ttk.Label(details, text=f"Candidate offset: {plan.candidate_ms:.3f} ms").pack(anchor="w")

        ttk.Button(self.body, text="READY", style="Big.TButton", command=self._run_probe).pack(fill="x")
        ttk.Button(self.body, text="취소", command=self._close).pack(fill="x", pady=(8, 0))

    def _run_probe(self) -> None:
        assert self.current_plan is not None
        c = self.config_data.get("calibration", {})
        prepare_seconds = float(c.get("prepare_seconds", 5.0))
        fraction_ms = (-self.current_plan.candidate_ms) % 1000.0
        self.target_wall_ns = future_wall_ns_with_fraction(fraction_ms, prepare_seconds)

        countdown_seconds = int(self.config_data.get("alarm", {}).get("countdown_seconds", 3))
        self.alarm_process = start_countdown(
            self.target_wall_ns,
            enabled=self.beep_var.get(),
            countdown_seconds=countdown_seconds,
        )
        spin_window_ms = float(self.config_data.get("spin_window_ms", 20.0))
        self.click_process, self.click_queue = start_precise_click(self.target_wall_ns, spin_window_ms)

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
        self.click_result = result
        self.deiconify()
        self.lift()
        self.grab_set()

        if not result.get("ok"):
            self._finish_failure(result.get("error", "Click failed."))
            return
        self._show_server_time_entry()

    def _show_server_time_entry(self) -> None:
        assert self.current_plan is not None
        assert self.click_result is not None
        self._clear()

        ttk.Label(self.body, text="서버 시각 입력", style="Title.TLabel").pack(pady=(0, 14))
        ttk.Label(
            self.body,
            text="클릭 후 웹페이지에 표시된 HH:MM:SS 서버 시각을 입력하세요.",
            wraplength=450,
            justify="center",
        ).pack(pady=(0, 18))

        entry_row = ttk.Frame(self.body)
        entry_row.pack(pady=10)
        self.hh_var = tk.StringVar()
        self.mm_var = tk.StringVar()
        self.ss_var = tk.StringVar()
        for idx, (var, label) in enumerate(((self.hh_var, "HH"), (self.mm_var, "MM"), (self.ss_var, "SS"))):
            box = ttk.Frame(entry_row)
            box.grid(row=0, column=idx, padx=8)
            ttk.Entry(box, textvariable=var, width=4, justify="center", font=("TkDefaultFont", 16)).pack()
            ttk.Label(box, text=label).pack(pady=(4, 0))

        call_dt = ns_to_datetime(self.click_result["call_ns"])
        ttk.Label(
            self.body,
            text=(
                f"PC click() 호출: {call_dt.strftime('%H:%M:%S.%f')[:-3]}\n"
                f"Trigger 오차: {self.click_result['trigger_error_ms']:+.3f} ms"
            ),
            justify="center",
        ).pack(pady=(16, 18))

        self.error_label = ttk.Label(self.body, text="")
        self.error_label.pack(pady=(0, 10))
        ttk.Button(self.body, text="다음", style="Big.TButton", command=self._submit_server_time).pack(fill="x")
        ttk.Button(self.body, text="취소", command=self._close).pack(fill="x", pady=(8, 0))
        self.hh_var.trace_add("write", lambda *_: self._limit_two_digits(self.hh_var, self.mm_var))
        self.mm_var.trace_add("write", lambda *_: self._limit_two_digits(self.mm_var, self.ss_var))
        self.ss_var.trace_add("write", lambda *_: self._limit_two_digits(self.ss_var, None))

    def _limit_two_digits(self, var: tk.StringVar, next_var: tk.StringVar | None) -> None:
        value = "".join(ch for ch in var.get() if ch.isdigit())[:2]
        if value != var.get():
            var.set(value)

    def _submit_server_time(self) -> None:
        assert self.session is not None
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
            self.error_label.config(text="올바른 HH:MM:SS 시각을 입력하세요.")
            return

        valid, reason = validate_server_hms(server_hms, self.click_result["call_ns"])
        if not valid:
            self.error_label.config(text=reason)
            return

        safe, threshold_ms, _ = classify_boundary(
            self.current_plan.candidate_ms,
            self.click_result["call_ns"],
            server_hms,
        )

        append_calibration_log({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "attempt": self.current_plan.attempt_number,
            "phase": self.current_plan.phase,
            "candidate_ms": f"{self.current_plan.candidate_ms:.3f}",
            "actual_threshold_ms": f"{threshold_ms:.3f}",
            "result": "SAFE" if safe else "EARLY",
            "trigger_error_ms": f"{self.click_result['trigger_error_ms']:.3f}",
            "click_duration_ms": f"{self.click_result['click_duration_ms']:.3f}",
            "server_time": server_hms,
        })

        self.session.record(self.current_plan, safe, threshold_ms)
        if self.session.is_complete:
            self._finish_success()
        elif self.session.is_failed:
            self._finish_failure(self.session.failure_reason)
        else:
            self._show_measurement_result(safe, threshold_ms)

    def _show_measurement_result(self, safe: bool, threshold_ms: float) -> None:
        assert self.session is not None
        self._clear()
        ttk.Label(self.body, text="✓ 측정 완료", style="Title.TLabel").pack(pady=(0, 16))
        ttk.Label(
            self.body,
            text="측정 결과에 맞춰 다음 테스트 위치를 자동으로 조정합니다.",
            justify="center",
        ).pack(pady=(0, 18))

        details = ttk.LabelFrame(self.body, text="상세 정보", padding=10)
        details.pack(fill="x", pady=(0, 20))
        ttk.Label(details, text=f"결과: {'SAFE' if safe else 'EARLY'}").pack(anchor="w")
        ttk.Label(details, text=f"측정 threshold: {threshold_ms:.3f} ms").pack(anchor="w")
        bracket = self.session.bracket()
        if bracket:
            ttk.Label(details, text=f"현재 boundary: {bracket[0]:.3f} ~ {bracket[1]:.3f} ms").pack(anchor="w")

        ttk.Button(self.body, text="다음 테스트", style="Big.TButton", command=self._show_next_probe).pack(fill="x")
        ttk.Button(self.body, text="취소", command=self._close).pack(fill="x", pady=(8, 0))

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
        ttk.Label(self.body, text="✓ 캘리브레이션 완료", style="Title.TLabel").pack(pady=(0, 18))

        gap = float(result["boundary_gap_ms"])
        if gap <= 2.0 and result["confirmation_early_count"] == 0:
            quality = "Very Good"
        elif gap <= 5.0:
            quality = "Good"
        else:
            quality = "Usable"

        ttk.Label(self.body, text=f"정밀도: {quality}", style="Section.TLabel").pack(pady=(0, 14))
        ttk.Label(
            self.body,
            text=(
                f"Tests: {result['attempts']}\n"
                f"No-early offset: {result['no_early_offset_ms']:.3f} ms\n"
                f"Boundary: {result['boundary_low_ms']:.3f} ~ {result['boundary_high_ms']:.3f} ms\n"
                f"Gap: {result['boundary_gap_ms']:.3f} ms\n"
                f"Confirmation EARLY: {result['confirmation_early_count']}"
            ),
            justify="left",
        ).pack(pady=(0, 24))
        ttk.Button(self.body, text="완료", style="Big.TButton", command=self._done).pack(fill="x")

    def _finish_failure(self, reason: str) -> None:
        self._clear()
        ttk.Label(self.body, text="캘리브레이션 저장 안 됨", style="Title.TLabel").pack(pady=(0, 18))
        ttk.Label(
            self.body,
            text=reason or "제한된 시도 횟수 안에서 신뢰할 수 있는 결과를 얻지 못했습니다.",
            wraplength=450,
            justify="center",
        ).pack(pady=(0, 20))
        ttk.Button(self.body, text="다시 시도", style="Big.TButton", command=self._show_intro).pack(fill="x")
        ttk.Button(self.body, text="닫기", command=self._close).pack(fill="x", pady=(8, 0))

    def _done(self) -> None:
        if self.on_saved:
            self.on_saved()
        self.destroy()

    def _close(self) -> None:
        cancel_process(self.click_process)
        cleanup_countdown(self.alarm_process)
        self.destroy()


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: CourseClickerApp, config: dict[str, Any], on_saved) -> None:
        super().__init__(parent)
        self.config_data = load_config()
        self.on_saved = on_saved
        self.title("고급 설정")
        self.geometry("480x570")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frame = ttk.Frame(self, padding=22)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="고급 설정", style="Title.TLabel").pack(pady=(0, 16))

        self.vars: dict[str, tk.StringVar] = {}

        timing = ttk.LabelFrame(frame, text="Timing", padding=12)
        timing.pack(fill="x", pady=6)
        self._row(timing, "Late margin (ms)", "late_margin_ms", self.config_data.get("late_margin_ms", 0.0))
        self._row(timing, "Spin window (ms)", "spin_window_ms", self.config_data.get("spin_window_ms", 20.0))

        cal = self.config_data.get("calibration", {})
        calibration = ttk.LabelFrame(frame, text="캘리브레이션", padding=12)
        calibration.pack(fill="x", pady=6)
        self._row(calibration, "Max attempts (≤ 8)", "max_attempts", cal.get("max_attempts", 8))
        self._row(calibration, "Target gap (ms)", "target_gap_ms", cal.get("target_gap_ms", 2.0))
        self._row(calibration, "Guard (ms)", "guard_ms", cal.get("guard_ms", 0.5))
        self._row(calibration, "Backoff (ms)", "backoff_ms", cal.get("backoff_ms", 1.0))

        alarm = self.config_data.get("alarm", {})
        alarm_box = ttk.LabelFrame(frame, text="알람", padding=12)
        alarm_box.pack(fill="x", pady=6)
        self.alarm_enabled = tk.BooleanVar(value=bool(alarm.get("enabled", True)))
        ttk.Checkbutton(alarm_box, text="사용", variable=self.alarm_enabled).pack(anchor="w")
        self._row(alarm_box, "카운트다운 초", "countdown_seconds", alarm.get("countdown_seconds", 3))

        ttk.Button(frame, text="저장", style="Big.TButton", command=self.save).pack(fill="x", pady=(18, 6))
        ttk.Button(frame, text="취소", command=self.destroy).pack(fill="x")

    def _row(self, parent: ttk.LabelFrame, label: str, key: str, value: Any) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label).pack(side="left")
        var = tk.StringVar(value=str(value))
        self.vars[key] = var
        ttk.Entry(row, textvariable=var, width=10).pack(side="right")

    def save(self) -> None:
        try:
            late_margin = float(self.vars["late_margin_ms"].get())
            spin_window = float(self.vars["spin_window_ms"].get())
            max_attempts = min(8, max(4, int(self.vars["max_attempts"].get())))
            target_gap = float(self.vars["target_gap_ms"].get())
            guard = float(self.vars["guard_ms"].get())
            backoff = float(self.vars["backoff_ms"].get())
            countdown = max(0, min(10, int(self.vars["countdown_seconds"].get())))
        except ValueError:
            messagebox.showerror("잘못된 설정", "숫자만 입력하세요.", parent=self)
            return

        if spin_window <= 0 or target_gap <= 0 or guard < 0 or backoff <= 0:
            messagebox.showerror("잘못된 설정", "Timing 값은 양수여야 합니다(guard는 0 가능).", parent=self)
            return

        self.config_data["late_margin_ms"] = late_margin
        self.config_data["spin_window_ms"] = spin_window
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


if __name__ == "__main__":
    mp.freeze_support()
    app = CourseClickerApp()
    app.mainloop()
