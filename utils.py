from __future__ import annotations

import csv
import json
import math
import multiprocessing as mp
import os
import platform
import struct
import subprocess
import tempfile
import time
import wave
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path
from queue import Empty
from typing import Any

APP_NAME = "CourseClicker"


def app_data_dir() -> Path:
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / ".config"
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


CONFIG_PATH = app_data_dir() / "config.json"
CALIBRATION_LOG_PATH = app_data_dir() / "calibration_v4.csv"


DEFAULT_CONFIG: dict[str, Any] = {
    "target_datetime": "",
    "effective_offset_ms": 0.0,
    "no_early_offset_ms": 0.0,
    "late_margin_ms": 0.0,
    "spin_window_ms": 20.0,
    "alarm": {
        "enabled": True,
        "countdown_seconds": 3,
    },
    "calibration": {
        "version": 4,
        "max_attempts": 8,
        "target_gap_ms": 2.0,
        "guard_ms": 0.5,
        "backoff_ms": 1.0,
        "quick_initial_step_ms": 8.0,
        "full_initial_step_ms": 128.0,
        "default_guess_ms": 2000.0,
        "prepare_seconds": 5.0,
        "last_result": {},
    },
}


def _deep_merge(base: dict[str, Any], loaded: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _default_target_string() -> str:
    now = datetime.now()
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return next_hour.strftime("%Y-%m-%d %H:%M:%S")


def load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
        except Exception:
            loaded = {}
    else:
        loaded = {}

    config = _deep_merge(DEFAULT_CONFIG, loaded)
    if not config.get("target_datetime"):
        config["target_datetime"] = _default_target_string()
    return config


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def datetime_to_ns(dt: datetime) -> int:
    return int(round(dt.timestamp() * 1_000_000_000))


def ns_to_datetime(value_ns: int) -> datetime:
    return datetime.fromtimestamp(value_ns / 1_000_000_000)


def wall_to_perf_deadline(target_wall_ns: int) -> int:
    wall1 = time.time_ns()
    perf = time.perf_counter_ns()
    wall2 = time.time_ns()
    wall_mid = (wall1 + wall2) // 2
    return perf + (target_wall_ns - wall_mid)


def wait_until_perf(deadline_ns: int, spin_window_ms: float = 20.0) -> None:
    spin_ns = int(spin_window_ms * 1_000_000)
    while True:
        remain_ns = deadline_ns - time.perf_counter_ns()
        if remain_ns <= 0:
            return
        if remain_ns > 1_000_000_000:
            time.sleep(0.2)
        elif remain_ns > 100_000_000:
            time.sleep(0.01)
        elif remain_ns > spin_ns:
            time.sleep((remain_ns - spin_ns) / 1_000_000_000)
        else:
            pass


def future_wall_ns_with_fraction(fraction_ms: float, prepare_seconds: float = 5.0) -> int:
    min_target_ns = time.time_ns() + int(prepare_seconds * 1_000_000_000)
    second_ns = min_target_ns // 1_000_000_000
    target_ns = second_ns * 1_000_000_000 + int(round(fraction_ms * 1_000_000))
    if target_ns < min_target_ns:
        target_ns += 1_000_000_000
    return target_ns


def prewarm_input() -> tuple[bool, str]:
    try:
        import pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0
        pyautogui.position()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _click_worker(target_wall_ns: int, spin_window_ms: float, result_queue: mp.Queue) -> None:
    try:
        import pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0

        deadline_perf_ns = wall_to_perf_deadline(target_wall_ns)
        wait_until_perf(deadline_perf_ns, spin_window_ms)

        call_ns = time.time_ns()
        pyautogui.click()
        return_ns = time.time_ns()

        result_queue.put({
            "ok": True,
            "call_ns": call_ns,
            "return_ns": return_ns,
            "trigger_error_ms": (call_ns - target_wall_ns) / 1_000_000,
            "click_duration_ms": (return_ns - call_ns) / 1_000_000,
        })
    except BaseException as exc:
        result_queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def start_precise_click(target_wall_ns: int, spin_window_ms: float = 20.0) -> tuple[mp.Process, mp.Queue]:
    result_queue: mp.Queue = mp.Queue(maxsize=1)
    process = mp.Process(
        target=_click_worker,
        args=(target_wall_ns, spin_window_ms, result_queue),
        daemon=True,
    )
    process.start()
    return process, result_queue


def poll_click_result(process: mp.Process, result_queue: mp.Queue) -> dict[str, Any] | None:
    try:
        return result_queue.get_nowait()
    except Empty:
        if not process.is_alive():
            try:
                return result_queue.get(timeout=0.1)
            except Exception:
                return {"ok": False, "error": "Click worker ended without a result."}
        return None


def cancel_process(process: mp.Process | None) -> None:
    if process is None:
        return
    if process.is_alive():
        process.terminate()
        process.join(timeout=0.3)


def prepare_beep_asset() -> str:
    path = Path(tempfile.gettempdir()) / "course_clicker_beep.wav"
    if path.exists():
        return str(path)

    sample_rate = 44_100
    duration_ms = 80
    frequency = 880
    amplitude = 9_000
    samples = int(sample_rate * duration_ms / 1000)

    with wave.open(str(path), "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames: list[bytes] = []
        for i in range(samples):
            progress = i / samples
            envelope = max(0.0, min(progress / 0.1, (1.0 - progress) / 0.1, 1.0))
            value = int(
                amplitude
                * envelope
                * math.sin(2 * math.pi * frequency * i / sample_rate)
            )
            frames.append(struct.pack("<h", value))
        wav.writeframes(b"".join(frames))
    return str(path)


def _play_beep(path: str) -> None:
    system = platform.system()
    if system == "Darwin":
        subprocess.run(
            ["afplay", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    elif system == "Windows":
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME)
    else:
        print("\a", end="", flush=True)


def _wait_wall(target_ns: int) -> None:
    while True:
        remain_ns = target_ns - time.time_ns()
        if remain_ns <= 0:
            return
        if remain_ns > 50_000_000:
            time.sleep((remain_ns - 20_000_000) / 1_000_000_000)
        else:
            time.sleep(remain_ns / 1_000_000_000)


def _countdown_worker(click_wall_ns: int, countdown_seconds: int, sound_path: str) -> None:
    for number in range(countdown_seconds, 0, -1):
        alarm_ns = click_wall_ns - number * 1_000_000_000
        if alarm_ns <= time.time_ns():
            continue
        _wait_wall(alarm_ns)
        _play_beep(sound_path)


def start_countdown(click_wall_ns: int, enabled: bool = True, countdown_seconds: int = 3) -> mp.Process | None:
    if not enabled or countdown_seconds <= 0:
        return None
    sound_path = prepare_beep_asset()
    process = mp.Process(
        target=_countdown_worker,
        args=(click_wall_ns, countdown_seconds, sound_path),
        daemon=True,
    )
    process.start()
    return process


def cleanup_countdown(process: mp.Process | None) -> None:
    if process is None:
        return
    process.join(timeout=0.3)
    if process.is_alive():
        process.terminate()
        process.join(timeout=0.2)


def closest_server_datetime(server_hms: str, local_call_ns: int) -> datetime:
    hh, mm, ss = map(int, server_hms.split(":"))
    local_dt = datetime.fromtimestamp(local_call_ns / 1_000_000_000)
    candidates: list[datetime] = []
    for day_delta in (-1, 0, 1):
        date = local_dt.date() + timedelta(days=day_delta)
        candidates.append(datetime.combine(date, dt_time(hh, mm, ss)))
    return min(candidates, key=lambda dt: abs(dt.timestamp() - local_dt.timestamp()))


def validate_server_hms(server_hms: str, local_call_ns: int, max_diff_seconds: float = 30.0) -> tuple[bool, str]:
    try:
        server_dt = closest_server_datetime(server_hms, local_call_ns)
    except Exception:
        return False, "시간 형식이 올바르지 않습니다."
    click_dt = datetime.fromtimestamp(local_call_ns / 1_000_000_000)
    diff = abs((server_dt - click_dt).total_seconds())
    if diff > max_diff_seconds:
        return False, f"클릭 시각과 {diff:.1f}초 차이납니다. 입력값을 다시 확인해주세요."
    return True, ""


def classify_boundary(candidate_ms: float, call_ns: int, server_hms: str) -> tuple[bool, float, int]:
    candidate_ns = int(round(candidate_ms * 1_000_000))
    estimated_boundary_ns = call_ns + candidate_ns
    boundary_second = (estimated_boundary_ns + 500_000_000) // 1_000_000_000
    boundary_ns = boundary_second * 1_000_000_000
    actual_threshold_ms = (boundary_ns - call_ns) / 1_000_000

    server_dt = closest_server_datetime(server_hms, call_ns)
    server_second = int(server_dt.timestamp())
    safe = server_second >= boundary_second
    return safe, actual_threshold_ms, boundary_second


def append_calibration_log(row: dict[str, Any]) -> None:
    fields = [
        "timestamp",
        "attempt",
        "phase",
        "candidate_ms",
        "actual_threshold_ms",
        "result",
        "trigger_error_ms",
        "click_duration_ms",
        "server_time",
    ]
    exists = CALIBRATION_LOG_PATH.exists()
    with CALIBRATION_LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in fields})
