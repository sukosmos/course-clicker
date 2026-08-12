from __future__ import annotations

import multiprocessing as mp
import platform
import subprocess
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk
from typing import Any

from dialogs import CalibrationWizard, ClickDialog, SettingsDialog
from ui_theme import (
    COLORS,
    FONT,
    FlatButton,
    configure_ttk,
    make_button,
    make_card,
    make_toggle,
    muted_label,
    section_label,
    title_label,
)
from utils import CONFIG_PATH, load_config, save_config

APP_TITLE = "Course Clicker"


class CourseClickerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("610x760")
        self.minsize(580, 720)
        self.configure(bg=COLORS["bg"])
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.config_data = load_config()
        save_config(self.config_data)
        configure_ttk(self)
        self._build_main()
        self.refresh_status()

    def _build_main(self) -> None:
        main = tk.Frame(self, bg=COLORS["bg"])
        main.pack(fill="both", expand=True, padx=28, pady=24)

        title_label(main, APP_TITLE).pack(anchor="w")
        muted_label(
            main,
            "정해진 시각에 현재 마우스 위치를 한 번 클릭합니다.",
            size=10,
        ).pack(anchor="w", pady=(4, 20))

        self._build_status_card(main)
        self._build_target_card(main)
        self._build_actions(main)

        footer = tk.Frame(main, bg=COLORS["bg"])
        footer.pack(fill="x", pady=(16, 0))
        make_button(
            footer,
            "고급 설정",
            self.open_settings,
            kind="soft",
            compact=True,
        ).pack(side="left")

        if platform.system() == "Darwin":
            make_button(
                footer,
                "접근성 도움말",
                self.open_accessibility_help,
                kind="soft",
                compact=True,
            ).pack(side="right")

        self.info_label = muted_label(
            main,
            "",
            size=9,
            wraplength=540,
        )
        self.info_label.pack(fill="x", pady=(14, 0))

    def _build_status_card(self, parent: tk.Misc) -> None:
        card = make_card(parent)
        card.pack(fill="x", pady=(0, 12))
        body = tk.Frame(card, bg=COLORS["card"])
        body.pack(fill="x", padx=20, pady=18)

        top = tk.Frame(body, bg=COLORS["card"])
        top.pack(fill="x")
        section_label(top, "캘리브레이션").pack(side="left")

        self.status_pill = tk.Label(
            top,
            text="",
            font=(FONT, 9, "bold"),
            padx=10,
            pady=5,
            relief="flat",
        )
        self.status_pill.pack(side="right")

        self.status_detail = muted_label(
            body,
            "",
            bg=COLORS["card"],
            size=9,
        )
        self.status_detail.pack(anchor="w", pady=(11, 0))

    def _build_target_card(self, parent: tk.Misc) -> None:
        card = make_card(parent)
        card.pack(fill="x", pady=(0, 14))
        body = tk.Frame(card, bg=COLORS["card"])
        body.pack(fill="x", padx=20, pady=18)

        section_label(body, "목표 시각").pack(anchor="w")
        initial_target = self._parse_target_or_default()
        self.date_var = tk.StringVar(value=initial_target.strftime("%Y-%m-%d"))
        self.time_var = tk.StringVar(value=initial_target.strftime("%H:%M:%S"))

        fields = tk.Frame(body, bg=COLORS["card"])
        fields.pack(fill="x", pady=(13, 0))
        fields.columnconfigure(0, weight=1)
        fields.columnconfigure(1, weight=1)

        date_box = tk.Frame(fields, bg=COLORS["card"])
        date_box.grid(row=0, column=0, sticky="ew", padx=(0, 7))
        muted_label(date_box, "날짜", bg=COLORS["card"]).pack(anchor="w")
        ttk.Entry(
            date_box,
            textvariable=self.date_var,
            style="Course.TEntry",
            font=(FONT, 12),
        ).pack(fill="x", pady=(5, 0))

        time_box = tk.Frame(fields, bg=COLORS["card"])
        time_box.grid(row=0, column=1, sticky="ew", padx=(7, 0))
        muted_label(time_box, "시간", bg=COLORS["card"]).pack(anchor="w")
        ttk.Entry(
            time_box,
            textvariable=self.time_var,
            style="Course.TEntry",
            font=(FONT, 12),
        ).pack(fill="x", pady=(5, 0))

        tk.Frame(body, bg=COLORS["line"], height=1).pack(fill="x", pady=(18, 15))

        alarm_row = tk.Frame(body, bg=COLORS["card"])
        alarm_row.pack(fill="x")
        alarm_text = tk.Frame(alarm_row, bg=COLORS["card"])
        alarm_text.pack(side="left", fill="x", expand=True)
        section_label(alarm_text, "3초 카운트다운 알람").pack(anchor="w")
        muted_label(
            alarm_text,
            "클릭 3초 전부터 짧은 beep를 재생합니다.",
            bg=COLORS["card"],
        ).pack(anchor="w", pady=(3, 0))

        self.alarm_var = tk.BooleanVar(
            value=bool(self.config_data.get("alarm", {}).get("enabled", True))
        )
        self.alarm_button_holder = tk.Frame(alarm_row, bg=COLORS["card"])
        self.alarm_button_holder.pack(side="right", padx=(14, 0))
        self.alarm_button: FlatButton | None = None
        self._render_alarm_button()

    def _build_actions(self, parent: tk.Misc) -> None:
        make_button(
            parent,
            "ARM CLICKER",
            self.arm_real_click,
            kind="primary",
        ).pack(fill="x", pady=(0, 9))

        row = tk.Frame(parent, bg=COLORS["bg"])
        row.pack(fill="x")
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=1)

        make_button(row, "캘리브레이션", self.open_calibration).grid(
            row=0,
            column=0,
            sticky="ew",
            padx=(0, 5),
        )
        make_button(row, "테스트 클릭", self.start_test_click).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(5, 0),
        )

    def _render_alarm_button(self) -> None:
        if self.alarm_button is not None:
            self.alarm_button.destroy()
        self.alarm_button = make_toggle(
            self.alarm_button_holder,
            enabled=bool(self.alarm_var.get()),
            on_text="ALARM ON · 소리 남",
            off_text="ALARM OFF · 무음",
            command=self._toggle_alarm,
        )
        self.alarm_button.pack()

    def _toggle_alarm(self) -> None:
        self.alarm_var.set(not self.alarm_var.get())
        self._render_alarm_button()
        self.config_data.setdefault("alarm", {})["enabled"] = bool(self.alarm_var.get())
        save_config(self.config_data)

    def _parse_target_or_default(self) -> datetime:
        value = self.config_data.get("target_datetime", "")
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return (datetime.now() + timedelta(hours=1)).replace(
                minute=0,
                second=0,
                microsecond=0,
            )

    def _read_target(self) -> datetime | None:
        try:
            return datetime.strptime(
                f"{self.date_var.get().strip()} {self.time_var.get().strip()}",
                "%Y-%m-%d %H:%M:%S",
            )
        except ValueError:
            messagebox.showerror(
                "잘못된 목표 시각",
                "날짜는 YYYY-MM-DD, 시간은 HH:MM:SS 형식으로 입력하세요.",
                parent=self,
            )
            return None

    def refresh_status(self) -> None:
        self.config_data = load_config()
        cal = self.config_data.get("calibration", {}).get("last_result", {})
        offset = float(self.config_data.get("no_early_offset_ms", 0.0) or 0.0)

        if not cal or offset <= 0:
            self._set_status("보정 필요", "warning")
            self.status_detail.config(text="실전 실행 전에 캘리브레이션을 진행하세요.")
        else:
            freshness = "준비 완료"
            age_text = ""
            try:
                calibrated_at = datetime.fromisoformat(str(cal["calibrated_at"]))
                age = datetime.now() - calibrated_at
                hours = age.total_seconds() / 3600
                if hours >= 24:
                    freshness = "재보정 권장"
                elif hours >= 2:
                    freshness = "확인 권장"

                if age.total_seconds() < 3600:
                    age_text = f"{max(1, int(age.total_seconds() // 60))}분 전"
                else:
                    age_text = f"{hours:.1f}시간 전"
            except Exception:
                pass

            self._set_status(
                freshness,
                "success" if freshness == "준비 완료" else "warning",
            )
            details = [f"No-early offset  {offset:.3f} ms"]
            if cal.get("boundary_gap_ms") is not None:
                details.append(f"Boundary gap     {float(cal['boundary_gap_ms']):.3f} ms")
            if age_text:
                details.append(f"마지막 보정       {age_text}")
            self.status_detail.config(text="\n".join(details))

        delay = int(self.config_data.get("test_delay_seconds", 8))
        self.info_label.config(
            text=(
                f"테스트 클릭 기본 대기시간: {delay}초\n"
                "실전 전에는 테스트 클릭으로 마우스 권한과 알람을 한 번 확인하는 것을 권장합니다."
            )
        )

    def _set_status(self, text: str, tone: str) -> None:
        if tone == "success":
            self.status_pill.config(
                text=text,
                bg=COLORS["success_soft"],
                fg=COLORS["success"],
            )
        else:
            self.status_pill.config(
                text=text,
                bg=COLORS["warning_soft"],
                fg=COLORS["warning"],
            )

    def start_test_click(self) -> None:
        placeholder = datetime.now()
        ClickDialog(
            self,
            target_server=placeholder,
            target_local=placeholder,
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
            messagebox.showerror(
                "목표 시각 지남",
                "선택한 목표 시각이 이미 지났습니다.",
                parent=self,
            )
            return

        offset = float(self.config_data.get("no_early_offset_ms", 0.0) or 0.0)
        if offset <= 0:
            if not messagebox.askyesno(
                "캘리브레이션 없음",
                "유효한 no-early 캘리브레이션 값이 없습니다.\n\n보정값 없이 계속할까요?",
                parent=self,
            ):
                return

        late_margin = float(self.config_data.get("late_margin_ms", 0.0))
        target_local = (
            target_server
            - timedelta(milliseconds=offset)
            + timedelta(milliseconds=late_margin)
        )

        self.config_data["target_datetime"] = target_server.strftime("%Y-%m-%d %H:%M:%S")
        self.config_data.setdefault("alarm", {})["enabled"] = bool(self.alarm_var.get())
        save_config(self.config_data)

        ClickDialog(
            self,
            target_server=target_server,
            target_local=target_local,
            config=self.config_data,
            alarm_enabled=self.alarm_var.get(),
            title="ARM CLICKER",
            test_mode=False,
            on_done=self.refresh_status,
        )

    def open_calibration(self) -> None:
        CalibrationWizard(
            self,
            self.config_data,
            on_saved=self.refresh_status,
        )

    def open_settings(self) -> None:
        SettingsDialog(
            self,
            self.config_data,
            on_saved=self._settings_saved,
        )

    def _settings_saved(self, config: dict[str, Any]) -> None:
        self.config_data = config
        self.alarm_var.set(bool(config.get("alarm", {}).get("enabled", True)))
        self._render_alarm_button()
        self.refresh_status()

    def open_accessibility_help(self) -> None:
        messagebox.showinfo(
            "Accessibility",
            (
                "macOS에서는 Course Clicker가 마우스를 제어할 수 있도록 권한이 필요할 수 있습니다.\n\n"
                "System Settings\n"
                "→ Privacy & Security\n"
                "→ Accessibility\n\n"
                "패키징 후에는 Course Clicker 앱 자체를 허용하세요."
            ),
            parent=self,
        )
        try:
            subprocess.Popen(
                [
                    "open",
                    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
                ]
            )
        except Exception:
            pass


if __name__ == "__main__":
    mp.freeze_support()
    app = CourseClickerApp()
    app.mainloop()
