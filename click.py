import argparse
import multiprocessing as mp

from datetime import datetime, timedelta

from utils import (
    cleanup_countdown,
    datetime_to_ns,
    load_config,
    precise_click,
    prewarm_input,
    start_countdown,
)


def get_alarm_settings(
    config,
    no_beep
):
    alarm = config.get(
        "alarm",
        {}
    )

    enabled = bool(
        alarm.get(
            "enabled",
            True
        )
    )

    if no_beep:
        enabled = False

    countdown_seconds = int(
        alarm.get(
            "countdown_seconds",
            3
        )
    )

    return (
        enabled,
        countdown_seconds
    )


def execute(
    target_server,
    config,
    no_beep=False,
    ignore_offset=False,
):
    prewarm_input()

    if ignore_offset:
        offset_ms = 0.0
        late_margin_ms = 0.0
        source = "test mode"

    else:
        if "no_early_offset_ms" in config:
            offset_ms = float(
                config[
                    "no_early_offset_ms"
                ]
            )

            source = (
                "no_early_offset_ms"
            )

        else:
            offset_ms = float(
                config.get(
                    "effective_offset_ms",
                    0.0
                )
            )

            source = (
                "effective_offset_ms"
            )

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

    target_local = (
        target_server
        - timedelta(
            milliseconds=offset_ms
        )
        + timedelta(
            milliseconds=late_margin_ms
        )
    )

    target_wall_ns = (
        datetime_to_ns(
            target_local
        )
    )

    beep_enabled, countdown_seconds = (
        get_alarm_settings(
            config,
            no_beep
        )
    )

    print()
    print("=" * 55)
    print(" Course Clicker")
    print("=" * 55)

    print(
        "서버 목표:",
        target_server.strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )[:-3]
    )

    print(
        "사용 offset:",
        f"{offset_ms:.3f} ms",
        f"({source})"
    )

    print(
        "late margin:",
        f"{late_margin_ms:.3f} ms"
    )

    print(
        "PC click 목표:",
        target_local.strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )[:-3]
    )

    print(
        "countdown:",
        (
            f"ON ({countdown_seconds}s)"
            if beep_enabled
            else "OFF"
        )
    )

    if target_local <= datetime.now():
        print()
        print(
            "ERROR: 이미 목표 시각이 지났습니다."
        )
        return

    input(
        "\nEnter를 눌러 ARM → "
        "브라우저로 이동 → "
        "[신청] 버튼 위에 "
        "마우스를 올려두세요: "
    )

    if target_local <= datetime.now():
        print(
            "\nERROR: ARM 중 "
            "목표 시각이 지났습니다."
        )
        return

    alarm_process = start_countdown(
        target_wall_ns,
        enabled=beep_enabled,
        countdown_seconds=countdown_seconds,
    )

    print()
    print("ARMED")

    try:
        result = precise_click(
            target_wall_ns,
            spin_window_ms,
        )

    except KeyboardInterrupt:
        cleanup_countdown(
            alarm_process
        )

        print(
            "\n사용자가 취소했습니다."
        )
        return

    except Exception as e:
        cleanup_countdown(
            alarm_process
        )

        print(
            "\n클릭 취소:",
            e
        )
        return

    cleanup_countdown(
        alarm_process
    )

    call_dt = datetime.fromtimestamp(
        result["call_ns"] / 1e9
    )

    return_dt = datetime.fromtimestamp(
        result["return_ns"] / 1e9
    )

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
        "로컬 trigger 오차:",
        f"{result['trigger_error_ms']:+.3f} ms"
    )

    print(
        "click() 함수 소요:",
        f"{result['click_duration_ms']:.3f} ms"
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--no-beep",
        action="store_true",
        help="countdown beep 끄기",
    )

    parser.add_argument(
        "--test-in",
        type=float,
        help="N초 후 로컬 테스트 클릭",
    )

    args = parser.parse_args()

    config = load_config()

    if args.test_in is not None:
        target = (
            datetime.now()
            + timedelta(
                seconds=args.test_in
            )
        )

        execute(
            target,
            config,
            no_beep=args.no_beep,
            ignore_offset=True,
        )

        return

    target = datetime.strptime(
        config[
            "target_datetime"
        ],
        "%Y-%m-%d %H:%M:%S"
    )

    execute(
        target,
        config,
        no_beep=args.no_beep,
    )


if __name__ == "__main__":
    mp.freeze_support()
    main()