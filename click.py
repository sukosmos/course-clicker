import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pyautogui


CONFIG_PATH = Path(__file__).with_name("config.json")


pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0


def load_config():
    with open(
        CONFIG_PATH,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


def wait_until_ns(target_ns, spin_window_ms=20):

    spin_ns = int(
        spin_window_ms * 1_000_000
    )

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

        # busy-wait 구간 직전
        elif remain_ns > spin_ns:

            sleep_ns = (
                remain_ns
                - spin_ns
            )

            time.sleep(
                sleep_ns
                / 1_000_000_000
            )

        # 마지막 수십 ms
        else:
            pass


def datetime_to_ns(dt):

    return int(
        dt.timestamp()
        * 1_000_000_000
    )


def normal_mode(config):

    target_server = datetime.strptime(
        config["target_datetime"],
        "%Y-%m-%d %H:%M:%S"
    )

    offset_ms = float(
        config.get(
            "effective_offset_ms",
            0
        )
    )

    late_margin_ms = float(
        config.get(
            "late_margin_ms",
            0
        )
    )

    spin_window_ms = float(
        config.get(
            "spin_window_ms",
            20
        )
    )

    # server = local click + effective offset
    #
    # 따라서:
    #
    # local click
    # = server target - offset + late margin

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
    print("========================================")
    print(" 수강신청 자동 1회 클릭")
    print("========================================")
    print()

    print(
        "서버 목표:",
        target_server.strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )[:-3]
    )

    print(
        "offset:",
        f"{offset_ms:+.3f} ms"
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

    print()

    now = datetime.now()

    if target_local <= now:
        print("ERROR: 클릭 목표 시각이 이미 지났습니다.")
        return

    input(
        "Enter를 눌러 ARM 하세요. "
        "그 다음 브라우저로 이동해서 "
        "[신청] 버튼 위에 마우스를 올려두세요: "
    )

    target_ns = datetime_to_ns(
        target_local
    )

    print()
    print("ARMED")
    print()
    print(
        "브라우저를 최상단에 두고 "
        "마우스를 버튼 위에 유지하세요."
    )

    print(
        "중단하려면 마우스를 화면 "
        "왼쪽 위 모서리로 이동하세요."
    )

    print()

    wait_until_ns(
        target_ns,
        spin_window_ms
    )

    before_ns = time.time_ns()

    try:
        pyautogui.click()

    except pyautogui.FailSafeException:
        print()
        print("Fail-safe: 클릭이 취소되었습니다.")
        return

    after_ns = time.time_ns()

    before_dt = datetime.fromtimestamp(
        before_ns / 1e9
    )

    after_dt = datetime.fromtimestamp(
        after_ns / 1e9
    )

    print()
    print("========================================")
    print(" CLICK")
    print("========================================")

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

    print(
        "호출 소요:",
        f"{(after_ns - before_ns) / 1e6:.3f} ms"
    )


def test_mode(seconds):

    print()
    print(
        f"{seconds}초 후 현재 마우스 위치를 "
        "한 번 클릭합니다."
    )

    print(
        "브라우저가 아닌 안전한 위치에서 "
        "먼저 테스트하세요."
    )

    target_ns = (
        time.time_ns()
        + int(
            seconds
            * 1_000_000_000
        )
    )

    wait_until_ns(
        target_ns,
        20
    )

    try:
        pyautogui.click()

    except pyautogui.FailSafeException:
        print("Fail-safe: 취소됨")
        return

    print("테스트 클릭 완료")


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--test-in",
        type=float,
        help=(
            "실제 목표시간 대신 N초 뒤 "
            "현재 마우스 위치 클릭"
        )
    )

    args = parser.parse_args()

    config = load_config()

    if args.test_in is not None:
        test_mode(args.test_in)

    else:
        normal_mode(config)


if __name__ == "__main__":
    main()