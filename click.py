import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pyautogui


CONFIG_PATH = Path(__file__).with_name("config.json")

# 안전장치 유지
pyautogui.FAILSAFE = True

# PyAutoGUI 기본 0.1초 pause 제거
pyautogui.PAUSE = 0


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"{CONFIG_PATH} 파일을 찾을 수 없습니다."
        )

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def wait_until_ns(target_ns, spin_window_ms=20):
    """
    목표 시각까지 대기.

    멀리 있을 때는 sleep(),
    마지막 spin_window_ms 동안은 busy-wait.
    """

    spin_ns = int(spin_window_ms * 1_000_000)

    while True:
        now_ns = time.time_ns()
        remain_ns = target_ns - now_ns

        if remain_ns <= 0:
            return

        # 1초 이상 남음
        if remain_ns > 1_000_000_000:
            time.sleep(0.2)

        # 100ms 이상 남음
        elif remain_ns > 100_000_000:
            time.sleep(0.01)

        # 마지막 busy-wait 직전
        elif remain_ns > spin_ns:
            sleep_ns = remain_ns - spin_ns

            time.sleep(
                sleep_ns / 1_000_000_000
            )

        # 마지막 수십 ms
        else:
            pass


def datetime_to_ns(dt):
    return int(
        dt.timestamp()
        * 1_000_000_000
    )


def get_timing_settings(config):
    """
    no-early offset을 우선 사용한다.

    fallback:
    1. no_early_offset_ms
    2. offset_range_ms 하한
    3. effective_offset_ms
    """

    if "no_early_offset_ms" in config:
        offset_ms = float(
            config["no_early_offset_ms"]
        )

        source = "no_early_offset_ms"

    elif "offset_range_ms" in config:
        offset_ms = float(
            config["offset_range_ms"][0]
        )

        source = "offset_range_ms lower bound"

    else:
        offset_ms = float(
            config.get(
                "effective_offset_ms",
                0.0
            )
        )

        source = "effective_offset_ms (fallback)"

    late_margin_ms = float(
        config.get(
            "late_margin_ms",
            0.0
        )
    )

    spin_window_ms = float(
        config.get(
            "spin_window_ms",
            20
        )
    )

    return (
        offset_ms,
        late_margin_ms,
        spin_window_ms,
        source,
    )


def print_expected_error(
    config,
    trigger_offset_ms,
    late_margin_ms,
):
    """
    Calibration 범위가 존재하면
    예상 서버 도착 오차 범위를 출력한다.

    오차:
      음수 = 목표보다 빠름
      양수 = 목표보다 늦음
    """

    offset_range = config.get(
        "offset_range_ms"
    )

    if not offset_range:
        return

    low = float(offset_range[0])
    high = float(offset_range[1])

    error_low = (
        low
        - trigger_offset_ms
        + late_margin_ms
    )

    error_high = (
        high
        - trigger_offset_ms
        + late_margin_ms
    )

    print()
    print(
        "Calibration delay 범위:",
        f"{low:.3f} ~ {high:.3f} ms"
    )

    print(
        "Calibration 폭:",
        f"{high - low:.3f} ms"
    )

    print()
    print(
        "예상 서버 도착 오차:",
        f"{error_low:+.3f}"
        f" ~ {error_high:+.3f} ms"
    )

    if error_low >= 0:
        print(
            "→ calibration 범위 내에서는 "
            "early 없음"
        )

    else:
        print(
            "→ calibration 범위 내에서도 "
            "early 가능"
        )


def normal_mode(config):
    target_server = datetime.strptime(
        config["target_datetime"],
        "%Y-%m-%d %H:%M:%S"
    )

    (
        offset_ms,
        late_margin_ms,
        spin_window_ms,
        source,
    ) = get_timing_settings(config)

    # 서버 목표 시각에 맞추기 위한
    # 실제 PC click() 호출 목표
    #
    # local target
    # = server target
    # - effective delay
    # + late safety margin

    target_local = (
        target_server
        - timedelta(
            milliseconds=offset_ms
        )
        + timedelta(
            milliseconds=late_margin_ms
        )
    )

    print()
    print("=" * 55)
    print(" Course Clicker - NO EARLY")
    print("=" * 55)
    print()

    print(
        "서버 목표:",
        target_server.strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )[:-3]
    )

    print(
        "사용 offset:",
        f"{offset_ms:+.3f} ms"
    )

    print(
        "offset source:",
        source
    )

    print(
        "late margin:",
        f"{late_margin_ms:+.3f} ms"
    )

    print()

    print(
        "PC 클릭 목표:",
        target_local.strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )[:-3]
    )

    print_expected_error(
        config,
        offset_ms,
        late_margin_ms,
    )

    print()

    if target_local <= datetime.now():
        print(
            "ERROR: 클릭 목표 시각이 "
            "이미 지났습니다."
        )
        return

    input(
        "Enter를 눌러 ARM 하세요. "
        "그 다음 브라우저로 이동해서 "
        "[신청] 버튼 위에 마우스를 올려두세요: "
    )

    # Enter 대기 중 목표 시간이 지나갔는지 다시 확인
    if target_local <= datetime.now():
        print()
        print(
            "ERROR: ARM하는 동안 "
            "클릭 목표 시각이 지났습니다."
        )
        return

    target_ns = datetime_to_ns(
        target_local
    )

    print()
    print("ARMED")
    print()

    x, y = pyautogui.position()

    print(
        "현재 마우스 위치:",
        f"({x}, {y})"
    )

    print()
    print(
        "브라우저를 최상단에 두고 "
        "마우스를 신청 버튼 위에 유지하세요."
    )

    print(
        "중단: Ctrl+C "
    )

    print()

    try:
        wait_until_ns(
            target_ns,
            spin_window_ms
        )

        # click() 호출 직전 PC wall-clock
        before_ns = time.time_ns()

        pyautogui.click()

        # click() 함수 반환 시각
        after_ns = time.time_ns()

    except pyautogui.FailSafeException:
        print()
        print(
            "Fail-safe가 작동하여 "
            "클릭을 취소했습니다."
        )
        return

    except KeyboardInterrupt:
        print()
        print("사용자가 취소했습니다.")
        return

    before_dt = datetime.fromtimestamp(
        before_ns / 1_000_000_000
    )

    after_dt = datetime.fromtimestamp(
        after_ns / 1_000_000_000
    )

    timing_error_ms = (
        before_ns - target_ns
    ) / 1_000_000

    print()
    print("=" * 55)
    print(" CLICK")
    print("=" * 55)

    print(
        "click() 목표:",
        target_local.strftime(
            "%H:%M:%S.%f"
        )[:-3]
    )

    print(
        "click() 호출:",
        before_dt.strftime(
            "%H:%M:%S.%f"
        )[:-3]
    )

    print(
        "click() 반환:",
        after_dt.strftime(
            "%H:%M:%S.%f"
        )[:-3]
    )

    print()

    print(
        "로컬 trigger 오차:",
        f"{timing_error_ms:+.3f} ms"
    )

    print(
        "click() 함수 소요:",
        f"{(after_ns - before_ns) / 1_000_000:.3f} ms"
    )

    print()

    # 실제 trigger 오차까지 포함하여
    # 예상 서버 도착 범위를 다시 계산
    offset_range = config.get(
        "offset_range_ms"
    )

    if offset_range:

        low = float(
            offset_range[0]
        )

        high = float(
            offset_range[1]
        )

        server_error_low = (
            low
            - offset_ms
            + late_margin_ms
            + timing_error_ms
        )

        server_error_high = (
            high
            - offset_ms
            + late_margin_ms
            + timing_error_ms
        )

        print(
            "이번 실행 예상 서버 오차:"
        )

        print(
            f"  {server_error_low:+.3f}"
            f" ~ {server_error_high:+.3f} ms"
        )


def test_mode(seconds):
    print()
    print(
        f"{seconds}초 후 현재 마우스 위치를 "
        "한 번 클릭합니다."
    )

    target_ns = (
        time.time_ns()
        + int(
            seconds
            * 1_000_000_000
        )
    )

    try:
        wait_until_ns(
            target_ns,
            20
        )

        before_ns = time.time_ns()

        pyautogui.click()

        after_ns = time.time_ns()

    except pyautogui.FailSafeException:
        print("Fail-safe: 취소됨")
        return

    except KeyboardInterrupt:
        print("사용자가 취소했습니다.")
        return

    print()
    print("테스트 클릭 완료")

    print(
        "trigger 오차:",
        f"{(before_ns-target_ns)/1e6:+.3f} ms"
    )

    print(
        "click() 소요:",
        f"{(after_ns-before_ns)/1e6:.3f} ms"
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--test-in",
        type=float,
        help=(
            "실제 target 대신 "
            "N초 후 현재 위치 클릭"
        )
    )

    args = parser.parse_args()

    try:
        config = load_config()

        if args.test_in is not None:
            test_mode(
                args.test_in
            )

        else:
            normal_mode(
                config
            )

    except KeyboardInterrupt:
        print()
        print("사용자가 프로그램을 종료했습니다.")

    except Exception as e:
        print()
        print(
            "ERROR:",
            e
        )


if __name__ == "__main__":
    main()