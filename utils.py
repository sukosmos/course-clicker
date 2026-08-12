import json
import math
import multiprocessing as mp
import platform
import struct
import subprocess
import tempfile
import time
import wave

from datetime import datetime, timedelta, time as dt_time
from pathlib import Path


CONFIG_PATH = Path(__file__).with_name("config.json")


# ============================================================
# Config
# ============================================================

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(
            config,
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# Timing
# ============================================================

def datetime_to_ns(dt):
    return int(round(dt.timestamp() * 1_000_000_000))


def wall_to_perf_deadline(target_wall_ns):
    """
    wall clock(time.time_ns)을
    monotonic perf_counter 기준 deadline으로 변환.
    """

    wall1 = time.time_ns()
    perf = time.perf_counter_ns()
    wall2 = time.time_ns()

    wall_mid = (wall1 + wall2) // 2

    return perf + (target_wall_ns - wall_mid)


def wait_until_perf(deadline_ns, spin_window_ms=20):
    """
    멀리 있을 때 sleep,
    마지막 spin_window_ms 동안 busy-wait.
    """

    spin_ns = int(spin_window_ms * 1_000_000)

    while True:
        remain_ns = (
            deadline_ns
            - time.perf_counter_ns()
        )

        if remain_ns <= 0:
            return

        if remain_ns > 1_000_000_000:
            time.sleep(0.2)

        elif remain_ns > 100_000_000:
            time.sleep(0.01)

        elif remain_ns > spin_ns:
            time.sleep(
                (remain_ns - spin_ns)
                / 1_000_000_000
            )

        else:
            # 마지막 구간
            pass


def future_wall_ns_with_fraction(
    fraction_ms,
    prepare_seconds=5
):
    """
    현재로부터 최소 prepare_seconds 이후이며,
    초 내부 위치가 fraction_ms인 wall-clock 시각 생성.

    예:
      fraction_ms = 938.0
      → xx:xx:xx.938
    """

    min_target_ns = (
        time.time_ns()
        + int(prepare_seconds * 1_000_000_000)
    )

    second_ns = (
        min_target_ns // 1_000_000_000
    )

    target_ns = (
        second_ns * 1_000_000_000
        + int(round(fraction_ms * 1_000_000))
    )

    if target_ns < min_target_ns:
        target_ns += 1_000_000_000

    return target_ns


def prewarm_input():
    """
    실제 timing 시작 전에 pyautogui를 import하고
    현재 포인터를 한번 읽어 초기화 비용을 미리 처리.
    """

    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0

    pyautogui.position()


def precise_click(
    target_wall_ns,
    spin_window_ms=20
):
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0

    deadline_perf_ns = wall_to_perf_deadline(
        target_wall_ns
    )

    wait_until_perf(
        deadline_perf_ns,
        spin_window_ms
    )

    call_ns = time.time_ns()

    pyautogui.click()

    return_ns = time.time_ns()

    trigger_error_ms = (
        call_ns - target_wall_ns
    ) / 1_000_000

    return {
        "call_ns": call_ns,
        "return_ns": return_ns,
        "trigger_error_ms": trigger_error_ms,
        "click_duration_ms":
            (return_ns - call_ns) / 1_000_000,
    }


# ============================================================
# Beep / countdown
# ============================================================

def prepare_beep_asset():
    path = (
        Path(tempfile.gettempdir())
        / "course_clicker_beep.wav"
    )

    if path.exists():
        return str(path)

    sample_rate = 44100
    duration_ms = 80
    frequency = 880
    amplitude = 9000

    samples = int(
        sample_rate
        * duration_ms
        / 1000
    )

    with wave.open(str(path), "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)

        frames = []

        for i in range(samples):
            progress = i / samples

            envelope = min(
                progress / 0.1,
                (1.0 - progress) / 0.1,
                1.0
            )

            envelope = max(
                0.0,
                envelope
            )

            value = int(
                amplitude
                * envelope
                * math.sin(
                    2
                    * math.pi
                    * frequency
                    * i
                    / sample_rate
                )
            )

            frames.append(
                struct.pack("<h", value)
            )

        wav.writeframes(
            b"".join(frames)
        )

    return str(path)


def _play_beep(path):
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

        winsound.PlaySound(
            path,
            winsound.SND_FILENAME
        )

    else:
        print("\a", end="", flush=True)


def _wait_wall(target_ns):
    while True:
        remain_ns = (
            target_ns - time.time_ns()
        )

        if remain_ns <= 0:
            return

        if remain_ns > 50_000_000:
            time.sleep(
                (remain_ns - 20_000_000)
                / 1_000_000_000
            )

        else:
            time.sleep(
                remain_ns
                / 1_000_000_000
            )


def _countdown_worker(
    click_wall_ns,
    countdown_seconds,
    sound_path
):
    """
    별도 process에서 실행.
    클릭 timing main process와 GIL을 공유하지 않음.
    """

    for number in range(
        countdown_seconds,
        0,
        -1
    ):
        alarm_ns = (
            click_wall_ns
            - number * 1_000_000_000
        )

        # 이미 지난 beep는 생략
        if alarm_ns <= time.time_ns():
            continue

        _wait_wall(alarm_ns)

        print(
            f"[{number}]",
            flush=True
        )

        _play_beep(sound_path)


def start_countdown(
    click_wall_ns,
    enabled=True,
    countdown_seconds=3
):
    if not enabled:
        return None

    if countdown_seconds <= 0:
        return None

    sound_path = prepare_beep_asset()

    process = mp.Process(
        target=_countdown_worker,
        args=(
            click_wall_ns,
            countdown_seconds,
            sound_path,
        ),
        daemon=True,
    )

    process.start()

    return process


def cleanup_countdown(process):
    if process is None:
        return

    process.join(timeout=0.3)

    if process.is_alive():
        process.terminate()
        process.join(timeout=0.2)


# ============================================================
# Server timestamp / calibration
# ============================================================

def closest_server_datetime(
    server_hms,
    local_call_ns
):
    hh, mm, ss = map(
        int,
        server_hms.split(":")
    )

    local_dt = datetime.fromtimestamp(
        local_call_ns / 1_000_000_000
    )

    candidates = []

    for day_delta in (-1, 0, 1):
        date = (
            local_dt.date()
            + timedelta(days=day_delta)
        )

        candidates.append(
            datetime.combine(
                date,
                dt_time(hh, mm, ss)
            )
        )

    return min(
        candidates,
        key=lambda dt:
            abs(
                dt.timestamp()
                - local_dt.timestamp()
            )
    )


def classify_boundary(
    candidate_ms,
    call_ns,
    server_hms
):
    """
    candidate_ms가 실제 effective delay보다 작은지 확인.

    SAFE:
        서버 시각이 candidate가 가리키는
        초 경계를 넘음.

    EARLY:
        아직 해당 초 경계 전.
    """

    candidate_ns = int(
        round(
            candidate_ms
            * 1_000_000
        )
    )

    estimated_boundary_ns = (
        call_ns + candidate_ns
    )

    # 가장 가까운 정수 초
    boundary_second = (
        estimated_boundary_ns
        + 500_000_000
    ) // 1_000_000_000

    boundary_ns = (
        boundary_second
        * 1_000_000_000
    )

    actual_threshold_ms = (
        boundary_ns - call_ns
    ) / 1_000_000

    server_dt = closest_server_datetime(
        server_hms,
        call_ns
    )

    server_second = int(
        server_dt.timestamp()
    )

    safe = (
        server_second
        >= boundary_second
    )

    return (
        safe,
        actual_threshold_ms,
        boundary_second,
    )