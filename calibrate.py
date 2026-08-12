# v4
import argparse
import csv
import multiprocessing as mp
import shutil
from datetime import datetime
from pathlib import Path

from utils import (
    CONFIG_PATH,
    classify_boundary,
    cleanup_countdown,
    closest_server_datetime,
    future_wall_ns_with_fraction,
    load_config,
    precise_click,
    prewarm_input,
    save_config,
    start_countdown,
)


BACKUP_PATH = Path(__file__).with_name(
    "config.json.bak"
)

CSV_PATH = Path(__file__).with_name(
    "calibration_v4.csv"
)


def append_log(row):
    exists = CSV_PATH.exists()

    fields = [
        "attempt",
        "phase",
        "candidate_ms",
        "actual_threshold_ms",
        "result",
        "target_local",
        "click_call",
        "trigger_error_ms",
        "click_duration_ms",
        "server_time",
    ]

    with open(
        CSV_PATH,
        "a",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields
        )

        if not exists:
            writer.writeheader()

        writer.writerow(row)


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

    countdown = int(
        alarm.get(
            "countdown_seconds",
            3
        )
    )

    return enabled, countdown


def get_prior(config):
    """
    이전 calibration 값이 있으면 적극 활용.
    """

    calibration = config.get(
        "calibration",
        {}
    )

    last = calibration.get(
        "last_result",
        {}
    )

    if "boundary_estimate_ms" in last:
        return (
            float(
                last[
                    "boundary_estimate_ms"
                ]
            ),
            True,
        )

    if "effective_offset_ms" in config:
        return (
            float(
                config[
                    "effective_offset_ms"
                ]
            ),
            True,
        )

    if "no_early_offset_ms" in config:
        return (
            float(
                config[
                    "no_early_offset_ms"
                ]
            ),
            True,
        )

    return (
        float(
            calibration.get(
                "default_guess_ms",
                2000.0
            )
        ),
        False,
    )


def read_server_time(call_ns):
    """
    명백한 오타를 잡기 위해
    PC click과 30초 이상 차이나면 재입력.
    """

    while True:
        value = input(
            "웹페이지 서버 표시 시각 "
            "(HH:MM:SS): "
        ).strip()

        try:
            server_dt = (
                closest_server_datetime(
                    value,
                    call_ns
                )
            )

        except Exception:
            print(
                "형식 오류. 예: 15:03:07"
            )
            continue

        click_dt = datetime.fromtimestamp(
            call_ns / 1e9
        )

        diff = abs(
            (
                server_dt
                - click_dt
            ).total_seconds()
        )

        if diff > 30:
            print()
            print(
                f"주의: click 시각과 "
                f"{diff:.1f}초 차이납니다."
            )
            print(
                "오타 가능성이 있으므로 "
                "다시 입력해주세요."
            )
            continue

        return value


def current_bracket(
    safe_values,
    early_values
):
    """
    EARLY 관측을 보수적으로 우선한다.

    upper = 관측된 EARLY 중 가장 작은 threshold
    lower = upper보다 작은 SAFE 중 가장 큰 threshold
    """

    if not safe_values:
        return None

    if not early_values:
        return None

    upper = min(
        early_values
    )

    valid_safe = [
        value
        for value in safe_values
        if value < upper
    ]

    if not valid_safe:
        return None

    lower = max(
        valid_safe
    )

    return lower, upper


def probe(
    candidate_ms,
    attempt,
    max_attempts,
    phase,
    config,
    beep_enabled,
    countdown_seconds,
):
    prepare_seconds = float(
        config.get(
            "calibration",
            {}
        ).get(
            "prepare_seconds",
            5
        )
    )

    spin_window_ms = float(
        config.get(
            "spin_window_ms",
            20
        )
    )

    print()
    print(
        "=" * 55
    )

    print(
        f"[{attempt}/{max_attempts}] "
        f"{phase}"
    )

    print(
        f"candidate offset: "
        f"{candidate_ms:.3f} ms"
    )

    input(
        "Enter → 브라우저로 이동 → "
        "테스트 버튼 위에 마우스를 두세요: "
    )

    # candidate가 서버 정수 초 경계에
    # 위치하도록 local fraction 선택
    fraction_ms = (
        -candidate_ms
    ) % 1000.0

    target_wall_ns = (
        future_wall_ns_with_fraction(
            fraction_ms,
            prepare_seconds
        )
    )

    target_dt = datetime.fromtimestamp(
        target_wall_ns / 1e9
    )

    print(
        "PC click 목표:",
        target_dt.strftime(
            "%H:%M:%S.%f"
        )[:-3]
    )

    alarm_process = start_countdown(
        target_wall_ns,
        enabled=beep_enabled,
        countdown_seconds=countdown_seconds,
    )

    result = precise_click(
        target_wall_ns,
        spin_window_ms
    )

    cleanup_countdown(
        alarm_process
    )

    call_ns = result["call_ns"]

    call_dt = datetime.fromtimestamp(
        call_ns / 1e9
    )

    print()
    print(
        "click() 호출:",
        call_dt.strftime(
            "%H:%M:%S.%f"
        )[:-3]
    )

    print(
        "trigger 오차:",
        f"{result['trigger_error_ms']:+.3f} ms"
    )

    print(
        "click() 함수 소요:",
        f"{result['click_duration_ms']:.3f} ms"
    )

    server_hms = read_server_time(
        call_ns
    )

    (
        safe,
        threshold_ms,
        _,
    ) = classify_boundary(
        candidate_ms,
        call_ns,
        server_hms
    )

    status = (
        "SAFE"
        if safe
        else "EARLY"
    )

    print()
    print(
        f"판정: {status}"
    )

    print(
        "실제 probe threshold:",
        f"{threshold_ms:.3f} ms"
    )

    append_log({
        "attempt": attempt,
        "phase": phase,
        "candidate_ms":
            f"{candidate_ms:.3f}",
        "actual_threshold_ms":
            f"{threshold_ms:.3f}",
        "result": status,
        "target_local":
            target_dt.isoformat(
                timespec="milliseconds"
            ),
        "click_call":
            call_dt.isoformat(
                timespec="milliseconds"
            ),
        "trigger_error_ms":
            f"{result['trigger_error_ms']:.3f}",
        "click_duration_ms":
            f"{result['click_duration_ms']:.3f}",
        "server_time": server_hms,
    })

    return safe, threshold_ms


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--no-beep",
        action="store_true",
        help="calibration countdown beep 끄기",
    )

    parser.add_argument(
        "--full",
        action="store_true",
        help="이전 calibration을 덜 신뢰하고 넓게 탐색",
    )

    args = parser.parse_args()

    config = load_config()

    if CONFIG_PATH.exists():
        shutil.copy2(
            CONFIG_PATH,
            BACKUP_PATH
        )

    prewarm_input()

    calibration = config.get(
        "calibration",
        {}
    )

    max_attempts = int(
        calibration.get(
            "max_attempts",
            8
        )
    )

    # hard cap
    max_attempts = min(
        max_attempts,
        8
    )

    target_gap_ms = float(
        calibration.get(
            "target_gap_ms",
            2.0
        )
    )

    guard_ms = float(
        calibration.get(
            "guard_ms",
            0.5
        )
    )

    backoff_ms = float(
        calibration.get(
            "backoff_ms",
            1.0
        )
    )

    beep_enabled, countdown_seconds = (
        get_alarm_settings(
            config,
            args.no_beep
        )
    )

    prior, has_prior = get_prior(
        config
    )

    if args.full:
        has_prior = False

    if has_prior:
        step_ms = float(
            calibration.get(
                "quick_initial_step_ms",
                8.0
            )
        )

        print(
            f"이전 calibration "
            f"{prior:.3f} ms에서 시작합니다."
        )

    else:
        step_ms = float(
            calibration.get(
                "full_initial_step_ms",
                128.0
            )
        )

        print(
            f"초기 추정값 "
            f"{prior:.3f} ms에서 시작합니다."
        )

    print()
    print(
        f"최대 시도: {max_attempts}회"
    )

    print(
        f"목표 boundary gap: "
        f"{target_gap_ms:.1f} ms 이하"
    )

    print(
        f"beep: "
        f"{'ON' if beep_enabled else 'OFF'}"
    )

    safe_values = []
    early_values = []

    attempt = 0

    # ========================================================
    # Phase 1: bracket 찾기
    # ========================================================

    candidate = prior

    attempt += 1

    safe, threshold = probe(
        candidate,
        attempt,
        max_attempts,
        "INITIAL PROBE",
        config,
        beep_enabled,
        countdown_seconds,
    )

    if safe:
        safe_values.append(
            threshold
        )
        direction = +1

    else:
        early_values.append(
            threshold
        )
        direction = -1

    current_candidate = candidate

    # confirmation을 위해 최소 2회는 남겨둔다.
    search_limit = (
        max_attempts - 2
    )

    while (
        current_bracket(
            safe_values,
            early_values
        )
        is None
        and attempt < search_limit
    ):
        next_candidate = (
            current_candidate
            + direction * step_ms
        )

        attempt += 1

        safe, threshold = probe(
            next_candidate,
            attempt,
            max_attempts,
            "BRACKET SEARCH",
            config,
            beep_enabled,
            countdown_seconds,
        )

        if safe:
            safe_values.append(
                threshold
            )
        else:
            early_values.append(
                threshold
            )

        bracket = current_bracket(
            safe_values,
            early_values
        )

        if bracket is not None:
            break

        # 아직 같은 방향이면 더 크게 이동
        current_candidate = (
            next_candidate
        )

        step_ms *= 2.0

    bracket = current_bracket(
        safe_values,
        early_values
    )

    if bracket is None:
        print()
        print(
            "SAFE/EARLY 경계를 "
            "8회 예산 안에서 찾지 못했습니다."
        )

        print(
            "환경 변화가 큰 경우 "
            "`python calibrate.py --full`로 "
            "다시 시도하세요."
        )

        return

    low, high = bracket

    # ========================================================
    # Phase 2: boundary refinement
    # ========================================================

    while (
        high - low > target_gap_ms
        and attempt < search_limit
    ):
        candidate = (
            low + high
        ) / 2.0

        attempt += 1

        safe, threshold = probe(
            candidate,
            attempt,
            max_attempts,
            "BOUNDARY SEARCH",
            config,
            beep_enabled,
            countdown_seconds,
        )

        if safe:
            safe_values.append(
                threshold
            )
        else:
            early_values.append(
                threshold
            )

        new_bracket = current_bracket(
            safe_values,
            early_values
        )

        if new_bracket is None:
            print()
            print(
                "측정 결과에 jitter가 크게 "
                "발생했습니다."
            )
            return

        low, high = new_bracket

        print()
        print(
            "현재 boundary:",
            f"{low:.3f}"
            f" ~ {high:.3f} ms"
        )

        print(
            "gap:",
            f"{high-low:.3f} ms"
        )

    # ========================================================
    # Phase 3: no-early candidate
    # ========================================================

    boundary_estimate = (
        low + high
    ) / 2.0

    # 가장 빠른 SAFE boundary보다
    # 약간 더 보수적으로
    final_offset = (
        low - guard_ms
    )

    print()
    print("=" * 55)

    print(
        "검색 완료 boundary:",
        f"{low:.3f}"
        f" ~ {high:.3f} ms"
    )

    print(
        "no-early 후보:",
        f"{final_offset:.3f} ms"
    )

    # ========================================================
    # Phase 4: 남은 budget으로 confirmation
    # ========================================================

    consecutive_safe = 0
    confirmation_early = 0

    while (
        attempt < max_attempts
        and consecutive_safe < 2
    ):
        attempt += 1

        safe, threshold = probe(
            final_offset,
            attempt,
            max_attempts,
            "FINAL CONFIRMATION",
            config,
            beep_enabled,
            countdown_seconds,
        )

        if safe:
            consecutive_safe += 1

        else:
            confirmation_early += 1

            # EARLY 발생 시 더 보수적으로 이동
            final_offset = min(
                final_offset,
                threshold - backoff_ms
            )

            consecutive_safe = 0

            print()
            print(
                "EARLY 관측 → offset을 "
                f"{final_offset:.3f} ms로 "
                "보수적으로 조정"
            )

    if consecutive_safe < 2:
        print()
        print(
            "최종 후보를 2회 연속 SAFE로 "
            "검증하지 못했습니다."
        )

        print(
            "안전을 위해 config를 "
            "업데이트하지 않습니다."
        )

        return

    # ========================================================
    # Save
    # ========================================================

    config[
        "effective_offset_ms"
    ] = round(
        boundary_estimate,
        3
    )

    config[
        "no_early_offset_ms"
    ] = round(
        final_offset,
        3
    )

    calibration["version"] = 4

    calibration[
        "last_result"
    ] = {
        "boundary_low_ms":
            round(low, 3),

        "boundary_high_ms":
            round(high, 3),

        "boundary_gap_ms":
            round(
                high - low,
                3
            ),

        "boundary_estimate_ms":
            round(
                boundary_estimate,
                3
            ),

        "no_early_offset_ms":
            round(
                final_offset,
                3
            ),

        "attempts":
            attempt,

        "confirmation_early_count":
            confirmation_early,

        "calibrated_at":
            datetime.now().isoformat(
                timespec="seconds"
            ),
    }

    config[
        "calibration"
    ] = calibration

    save_config(
        config
    )

    print()
    print("=" * 55)
    print(" CALIBRATION COMPLETE")
    print("=" * 55)

    print(
        "boundary:",
        f"{low:.3f}"
        f" ~ {high:.3f} ms"
    )

    print(
        "boundary gap:",
        f"{high-low:.3f} ms"
    )

    print(
        "no-early offset:",
        f"{final_offset:.3f} ms"
    )

    print(
        "총 시도:",
        f"{attempt}/{max_attempts}"
    )

    print(
        "최종 confirmation:",
        "2 SAFE 연속"
    )

    print()
    print(
        "config.json 업데이트 완료"
    )


if __name__ == "__main__":
    mp.freeze_support()
    main()