import csv
import json
import math
import time
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path

import pyautogui


CONFIG_PATH = Path(__file__).with_name("config.json")
CSV_PATH = Path(__file__).with_name("calibration.csv")

# 이 정도 이하로 좁혀지면 종료
TARGET_WIDTH_MS = 25.0

# 너무 오래 반복하지 않도록 제한
MAX_TRIALS = 10

# Enter를 누른 뒤 브라우저로 돌아갈 시간
PREPARE_SECONDS = 6


pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    return {
        "target_datetime": "2026-08-12 10:00:00",
        "effective_offset_ms": 0.0,
        "late_margin_ms": 0.0,
        "spin_window_ms": 20
    }


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def wait_until_ns(target_ns, spin_window_ms=20):
    """
    목표 시각까지 대기.
    마지막 spin_window_ms 동안은 busy-wait.
    """

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
            sleep_ns = remain_ns - spin_ns
            time.sleep(sleep_ns / 1_000_000_000)

        else:
            # 마지막 몇 ms는 sleep하지 않고 기다림
            pass


def closest_server_datetime(server_hms, local_call_ns):
    """
    서버가 HH:MM:SS만 보여주므로,
    local click과 가장 가까운 날짜를 선택.
    자정 근처 테스트도 처리.
    """

    hh, mm, ss = map(int, server_hms.split(":"))

    local_dt = datetime.fromtimestamp(
        local_call_ns / 1_000_000_000
    )

    candidates = []

    for day_delta in (-1, 0, 1):
        date = local_dt.date() + timedelta(days=day_delta)

        dt = datetime.combine(
            date,
            dt_time(hh, mm, ss)
        )

        candidates.append(dt)

    return min(
        candidates,
        key=lambda x: abs(x.timestamp() - local_dt.timestamp())
    )


def calculate_interval(local_call_ns, server_hms):
    """
    서버 표시가 HH:MM:SS라고 가정.

    표시가 14:19:04라면 실제 서버 이벤트 시각은
    [14:19:04.000, 14:19:05.000)

    범위 안에 있다고 가정한다.
    """

    local_seconds = local_call_ns / 1_000_000_000

    server_dt = closest_server_datetime(
        server_hms,
        local_call_ns
    )

    server_seconds = server_dt.timestamp()

    lower_ms = (
        server_seconds - local_seconds
    ) * 1000

    upper_ms = lower_ms + 1000

    return lower_ms, upper_ms


def choose_fraction_ms(low, high):
    """
    현재 offset 범위의 중간값 근처에
    서버의 초 경계가 오도록 다음 클릭 시각을 선택.

    사실상 binary search 역할.
    """

    midpoint = (low + high) / 2

    fraction_ms = (-midpoint) % 1000

    # 정확히 초 경계는 OS jitter 영향을 받기 쉬우므로
    # 아주 끝값은 피한다.
    fraction_ms = max(1.0, min(999.0, fraction_ms))

    return fraction_ms


def make_target_ns(fraction_ms):
    now_ns = time.time_ns()

    current_sec = now_ns // 1_000_000_000

    target_sec = current_sec + PREPARE_SECONDS

    return (
        target_sec * 1_000_000_000
        + int(fraction_ms * 1_000_000)
    )


def append_csv(
    trial,
    intended_ns,
    call_ns,
    server_hms,
    lower_ms,
    upper_ms,
    intersection_low,
    intersection_high
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
                "intended_local",
                "click_call_local",
                "server_display",
                "sample_lower_ms",
                "sample_upper_ms",
                "intersection_lower_ms",
                "intersection_upper_ms"
            ])

        writer.writerow([
            trial,
            datetime.fromtimestamp(
                intended_ns / 1e9
            ).isoformat(timespec="milliseconds"),

            datetime.fromtimestamp(
                call_ns / 1e9
            ).isoformat(timespec="milliseconds"),

            server_hms,

            f"{lower_ms:.3f}",
            f"{upper_ms:.3f}",
            f"{intersection_low:.3f}",
            f"{intersection_high:.3f}"
        ])


def main():
    config = load_config()

    spin_window_ms = config.get(
        "spin_window_ms",
        20
    )

    print()
    print("========================================")
    print(" 수강신청 서버 offset 캘리브레이션")
    print("========================================")
    print()
    print("주의:")
    print("- 반복 클릭해도 문제가 없는 상태에서만 테스트하세요.")
    print("- 클릭할 위치는 직접 마우스로 지정합니다.")
    print("- Enter를 누른 뒤 브라우저로 돌아가세요.")
    print("- 마우스를 화면 왼쪽 위 모서리로 옮기면")
    print("  PyAutoGUI fail-safe로 클릭을 중단할 수 있습니다.")
    print()

    intersection_low = None
    intersection_high = None

    # 첫 테스트는 .500초
    fraction_ms = 500.0

    for trial in range(1, MAX_TRIALS + 1):

        print()
        print("----------------------------------------")
        print(f"Test #{trial}")
        print("----------------------------------------")

        input(
            "Enter를 누른 뒤 브라우저로 이동해서 "
            "클릭 대상 위에 마우스를 올려두세요: "
        )

        target_ns = make_target_ns(fraction_ms)

        target_dt = datetime.fromtimestamp(
            target_ns / 1_000_000_000
        )

        print()
        print(
            "이번 PC 클릭 목표:",
            target_dt.strftime("%H:%M:%S.%f")[:-3]
        )

        print(
            f"약 {PREPARE_SECONDS}초 후 클릭합니다."
        )

        wait_until_ns(
            target_ns,
            spin_window_ms
        )

        # 여기 시각을 기준으로 offset을 계산한다.
        call_ns = time.time_ns()

        pyautogui.click()

        returned_ns = time.time_ns()

        call_dt = datetime.fromtimestamp(
            call_ns / 1e9
        )

        returned_dt = datetime.fromtimestamp(
            returned_ns / 1e9
        )

        print()
        print(
            "click() 호출:",
            call_dt.strftime("%H:%M:%S.%f")[:-3]
        )

        print(
            "click() 반환:",
            returned_dt.strftime("%H:%M:%S.%f")[:-3]
        )

        print(
            "PyAutoGUI 호출시간:",
            f"{(returned_ns - call_ns) / 1e6:.3f} ms"
        )

        print()

        server_hms = input(
            "웹페이지가 표시한 서버 시각 "
            "(예: 14:19:04): "
        ).strip()

        try:
            lower_ms, upper_ms = calculate_interval(
                call_ns,
                server_hms
            )

        except Exception:
            print(
                "시간 형식이 잘못되었습니다. "
                "HH:MM:SS 형식으로 입력하세요."
            )
            continue

        if intersection_low is None:
            intersection_low = lower_ms
            intersection_high = upper_ms

        else:
            intersection_low = max(
                intersection_low,
                lower_ms
            )

            intersection_high = min(
                intersection_high,
                upper_ms
            )

        print()
        print(
            "이번 테스트 offset 범위:"
        )

        print(
            f"  {lower_ms:.1f} ms"
            f" ~ {upper_ms:.1f} ms"
        )

        if intersection_low >= intersection_high:
            print()
            print("!! 기존 테스트들과 교집합이 없습니다.")
            print()
            print("가능한 원인:")
            print("- 네트워크 지연 변화")
            print("- 서버 표시 시각이 반올림 방식")
            print("- 테스트마다 서버 처리 시간이 크게 다름")
            print("- 잘못된 서버 시간 입력")
            print()
            print(
                "calibration.csv를 확인하고 "
                "다시 테스트하는 것을 권장합니다."
            )
            return

        width = (
            intersection_high
            - intersection_low
        )

        estimate = (
            intersection_low
            + intersection_high
        ) / 2

        print()
        print("현재 전체 추정:")
        print(
            f"  offset 범위 = "
            f"{intersection_low:.1f}"
            f" ~ {intersection_high:.1f} ms"
        )

        print(
            f"  추정 offset = {estimate:.1f} ms"
        )

        print(
            f"  오차 범위 폭 = {width:.1f} ms"
        )

        append_csv(
            trial,
            target_ns,
            call_ns,
            server_hms,
            lower_ms,
            upper_ms,
            intersection_low,
            intersection_high
        )

        if width <= TARGET_WIDTH_MS:

            config["effective_offset_ms"] = round(
                estimate,
                3
            )

            config["offset_range_ms"] = [
                round(intersection_low, 3),
                round(intersection_high, 3)
            ]

            config["offset_calibrated_at"] = (
                datetime.now().isoformat(
                    timespec="seconds"
                )
            )

            save_config(config)

            print()
            print("========================================")
            print("캘리브레이션 완료")
            print("========================================")

            print(
                f"effective_offset_ms = "
                f"{estimate:.1f}"
            )

            print()
            print(
                "config.json에 자동 저장했습니다."
            )

            return

        fraction_ms = choose_fraction_ms(
            intersection_low,
            intersection_high
        )

        print()
        print(
            "다음 테스트의 초 내부 위치:",
            f".{int(fraction_ms):03d}"
        )

    print()
    print(
        "최대 테스트 횟수에 도달했습니다."
    )

    if intersection_low < intersection_high:

        estimate = (
            intersection_low
            + intersection_high
        ) / 2

        config["effective_offset_ms"] = round(
            estimate,
            3
        )

        config["offset_range_ms"] = [
            round(intersection_low, 3),
            round(intersection_high, 3)
        ]

        save_config(config)

        print(
            f"현재 추정값 {estimate:.1f} ms를 "
            "config.json에 저장했습니다."
        )


if __name__ == "__main__":
    main()