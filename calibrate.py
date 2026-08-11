import csv
import json
import shutil
import time
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path

import pyautogui


CONFIG_PATH = Path(__file__).with_name("config.json")
CSV_PATH = Path(__file__).with_name("calibration_v2.csv")
BACKUP_PATH = Path(__file__).with_name("config.json.bak")

# 초기 검증 횟수
BASELINE_TRIALS = 5

# 최종적으로 이 폭 이하까지 좁히기
TARGET_WIDTH_MS = 10.0

# 전체 최대 테스트 횟수
MAX_TRIALS = 15

# Enter 누른 뒤 브라우저로 돌아갈 시간
PREPARE_SECONDS = 6

# 너무 초 경계 바로 옆에 클릭하는 것을 피함
BOUNDARY_GUARD_MS = 3.0


pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def backup_config():
    if CONFIG_PATH.exists():
        shutil.copy2(CONFIG_PATH, BACKUP_PATH)


def wait_until_ns(target_ns, spin_window_ms=20):
    spin_ns = int(spin_window_ms * 1_000_000)

    while True:
        now_ns = time.time_ns()
        remain_ns = target_ns - now_ns

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
            # 마지막 구간은 busy wait
            pass


def closest_server_datetime(server_hms, local_call_ns):
    hh, mm, ss = map(int, server_hms.split(":"))

    local_dt = datetime.fromtimestamp(
        local_call_ns / 1_000_000_000
    )

    candidates = []

    for day_delta in (-1, 0, 1):
        date = local_dt.date() + timedelta(days=day_delta)

        candidate = datetime.combine(
            date,
            dt_time(hh, mm, ss)
        )

        candidates.append(candidate)

    return min(
        candidates,
        key=lambda dt: abs(
            dt.timestamp() - local_dt.timestamp()
        )
    )


def calculate_delay_interval(local_call_ns, server_hms):
    """
    서버가 HH:MM:SS만 표시한다고 가정.

    예:
      local click = 14:57:49.899
      server      = 14:57:52

    실제 서버 이벤트 시각은

      [14:57:52.000, 14:57:53.000)

    따라서 effective delay는

      [2101ms, 3101ms)
    """

    local_sec = local_call_ns / 1_000_000_000

    server_dt = closest_server_datetime(
        server_hms,
        local_call_ns
    )

    server_sec = server_dt.timestamp()

    lower_ms = (
        server_sec - local_sec
    ) * 1000

    upper_ms = lower_ms + 1000

    return lower_ms, upper_ms


def make_target_ns(fraction_ms):
    now_ns = time.time_ns()

    current_sec = (
        now_ns // 1_000_000_000
    )

    target_sec = (
        current_sec + PREPARE_SECONDS
    )

    return (
        target_sec * 1_000_000_000
        + int(fraction_ms * 1_000_000)
    )


def choose_next_fraction(low_ms, high_ms):
    """
    현재 delay 범위 중앙이
    서버의 초 경계 근처에 오도록 클릭 fraction을 선택.

    binary search와 비슷한 역할.
    """

    midpoint = (
        low_ms + high_ms
    ) / 2.0

    fraction = (
        -midpoint
    ) % 1000.0

    if fraction < BOUNDARY_GUARD_MS:
        fraction = BOUNDARY_GUARD_MS

    if fraction > 1000 - BOUNDARY_GUARD_MS:
        fraction = (
            1000 - BOUNDARY_GUARD_MS
        )

    return fraction


def append_csv(
    trial,
    target_ns,
    call_ns,
    return_ns,
    server_hms,
    sample_low,
    sample_high,
    common_low,
    common_high,
):
    exists = CSV_PATH.exists()

    with open(
        CSV_PATH,
        "a",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.writer(f)

        if not exists:
            writer.writerow([
                "trial",
                "target_local",
                "click_call",
                "click_return",
                "click_duration_ms",
                "server_display",
                "sample_low_ms",
                "sample_high_ms",
                "common_low_ms",
                "common_high_ms",
            ])

        target_dt = datetime.fromtimestamp(
            target_ns / 1e9
        )

        call_dt = datetime.fromtimestamp(
            call_ns / 1e9
        )

        return_dt = datetime.fromtimestamp(
            return_ns / 1e9
        )

        writer.writerow([
            trial,
            target_dt.isoformat(
                timespec="milliseconds"
            ),
            call_dt.isoformat(
                timespec="milliseconds"
            ),
            return_dt.isoformat(
                timespec="milliseconds"
            ),
            f"{(return_ns-call_ns)/1e6:.3f}",
            server_hms,
            f"{sample_low:.3f}",
            f"{sample_high:.3f}",
            (
                f"{common_low:.3f}"
                if common_low is not None
                else ""
            ),
            (
                f"{common_high:.3f}"
                if common_high is not None
                else ""
            ),
        ])


def run_one_trial(
    trial,
    fraction_ms,
    spin_window_ms,
):
    print()
    print("=" * 55)
    print(f"TEST #{trial}")
    print("=" * 55)

    input(
        "Enter → 브라우저로 이동 → "
        "실제 테스트 버튼 위에 마우스를 올려두세요: "
    )

    target_ns = make_target_ns(
        fraction_ms
    )

    target_dt = datetime.fromtimestamp(
        target_ns / 1e9
    )

    print()
    print(
        "PC 클릭 예정:",
        target_dt.strftime(
            "%H:%M:%S.%f"
        )[:-3]
    )

    wait_until_ns(
        target_ns,
        spin_window_ms
    )

    call_ns = time.time_ns()

    try:
        pyautogui.click()

    except pyautogui.FailSafeException:
        print("Fail-safe로 취소되었습니다.")
        raise SystemExit

    return_ns = time.time_ns()

    call_dt = datetime.fromtimestamp(
        call_ns / 1e9
    )

    return_dt = datetime.fromtimestamp(
        return_ns / 1e9
    )

    print()
    print(
        "click() 호출:",
        call_dt.strftime(
            "%H:%M:%S.%f"
        )[:-3]
    )

    print(
        "click() 반환:",
        return_dt.strftime(
            "%H:%M:%S.%f"
        )[:-3]
    )

    print(
        "click() 소요:",
        f"{(return_ns-call_ns)/1e6:.3f} ms"
    )

    server_hms = input(
        "\n웹페이지 서버 표시 시각 "
        "(HH:MM:SS): "
    ).strip()

    low, high = calculate_delay_interval(
        call_ns,
        server_hms
    )

    print()
    print(
        "이번 effective delay 범위:"
    )
    print(
        f"  {low:.3f}"
        f" ~ {high:.3f} ms"
    )

    return (
        target_ns,
        call_ns,
        return_ns,
        server_hms,
        low,
        high,
    )


def main():
    config = load_config()
    backup_config()

    spin_window_ms = float(
        config.get(
            "spin_window_ms",
            20
        )
    )

    print()
    print("=" * 55)
    print(" Course Clicker Calibration v2")
    print("=" * 55)
    print()
    print("중요:")
    print(
        "- 반드시 실제 사용할 것과 동일한 "
        "페이지/버튼/네트워크 환경에서 테스트"
    )
    print(
        "- 기존 offset 값은 이번 측정에서는 사용하지 않음"
    )
    print(
        "- 서버가 HH:MM:SS 형태로 표시한다고 가정"
    )
    print()
    print(
        f"기존 config는 {BACKUP_PATH.name}로 백업합니다."
    )

    # 초기 probing 위치
    baseline_fractions = [
        100.0,
        300.0,
        500.0,
        700.0,
        900.0,
    ]

    common_low = None
    common_high = None

    samples = []

    trial = 0

    # -----------------------------------
    # Phase 1
    # -----------------------------------

    print()
    print("PHASE 1: delay 안정성 확인")

    for fraction_ms in baseline_fractions:

        trial += 1

        result = run_one_trial(
            trial,
            fraction_ms,
            spin_window_ms,
        )

        (
            target_ns,
            call_ns,
            return_ns,
            server_hms,
            low,
            high,
        ) = result

        samples.append(
            (low, high)
        )

        if common_low is None:
            common_low = low
            common_high = high

        else:
            common_low = max(
                common_low,
                low
            )

            common_high = min(
                common_high,
                high
            )

        append_csv(
            trial,
            target_ns,
            call_ns,
            return_ns,
            server_hms,
            low,
            high,
            common_low,
            common_high,
        )

        if common_low >= common_high:
            print()
            print("======================================")
            print("CALIBRATION FAILED")
            print("======================================")
            print()
            print(
                "5회 측정에서 일정한 offset으로 "
                "설명할 수 없는 결과가 나왔습니다."
            )
            print()
            print(
                "즉 네트워크/서버 처리 delay가 "
                "측정 중 크게 변했거나,"
            )
            print(
                "웹페이지가 보여주는 시각이 "
                "실제 요청 도착 시각이 아닐 수 있습니다."
            )
            print()
            print(
                "이 경우 ms 단위 offset 보정값을 "
                "자동 저장하지 않습니다."
            )
            print()
            print(
                f"원본 결과는 {CSV_PATH.name}에 저장됨"
            )

            return

    print()
    print("PHASE 1 통과")
    print()
    print(
        "공통 delay 범위:"
    )
    print(
        f"  {common_low:.3f}"
        f" ~ {common_high:.3f} ms"
    )

    # -----------------------------------
    # Phase 2
    # -----------------------------------

    print()
    print("PHASE 2: 범위 정밀화")

    while (
        common_high - common_low
        > TARGET_WIDTH_MS
        and trial < MAX_TRIALS
    ):

        fraction_ms = choose_next_fraction(
            common_low,
            common_high
        )

        trial += 1

        result = run_one_trial(
            trial,
            fraction_ms,
            spin_window_ms,
        )

        (
            target_ns,
            call_ns,
            return_ns,
            server_hms,
            low,
            high,
        ) = result

        new_low = max(
            common_low,
            low
        )

        new_high = min(
            common_high,
            high
        )

        append_csv(
            trial,
            target_ns,
            call_ns,
            return_ns,
            server_hms,
            low,
            high,
            new_low,
            new_high,
        )

        if new_low >= new_high:
            print()
            print("======================================")
            print("JITTER DETECTED")
            print("======================================")
            print()
            print(
                "정밀화 과정에서 기존 범위와 "
                "겹치지 않는 측정값이 나왔습니다."
            )
            print()
            print(
                "현재 환경에서는 delay가 "
                "고정값이 아닐 가능성이 큽니다."
            )
            print()
            print(
                "기존 config는 변경하지 않습니다."
            )
            return

        common_low = new_low
        common_high = new_high

        width = (
            common_high
            - common_low
        )

        print()
        print(
            "현재 공통 범위:"
        )
        print(
            f"  {common_low:.3f}"
            f" ~ {common_high:.3f} ms"
        )
        print(
            f"폭: {width:.3f} ms"
        )

    # -----------------------------------
    # 저장
    # -----------------------------------

    estimate = (
        common_low
        + common_high
    ) / 2

    width = (
        common_high
        - common_low
    )

    config[
        "effective_offset_ms"
    ] = round(
        estimate,
        3
    )

    config[
        "offset_range_ms"
    ] = [
        round(common_low, 3),
        round(common_high, 3),
    ]

    config[
        "offset_range_width_ms"
    ] = round(
        width,
        3
    )

    # no-early 정책용
    config[
        "no_early_offset_ms"
    ] = round(
        common_low,
        3
    )

    config[
        "offset_calibrated_at"
    ] = datetime.now().isoformat(
        timespec="seconds"
    )

    save_config(config)

    print()
    print("=" * 55)
    print("CALIBRATION COMPLETE")
    print("=" * 55)
    print()

    print(
        "delay range:",
        f"{common_low:.3f}"
        f" ~ {common_high:.3f} ms"
    )

    print(
        "midpoint:",
        f"{estimate:.3f} ms"
    )

    print(
        "range width:",
        f"{width:.3f} ms"
    )

    print()
    print(
        "no-early offset:",
        f"{common_low:.3f} ms"
    )

    print()
    print(
        "config.json 업데이트 완료"
    )

    print(
        "이전 config:",
        BACKUP_PATH.name
    )

    print(
        "측정 로그:",
        CSV_PATH.name
    )


if __name__ == "__main__":
    main()