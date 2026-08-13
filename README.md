# Course Clicker

지정된 서버 목표 시각에 맞춰 **현재 마우스 위치를 한 번 클릭**하는 프로그램입니다.

사용자가 직접 로그인, 과목 선택, 버튼 위치 지정까지 진행하고,  
Course Clicker는 **클릭 타이밍만 자동화**합니다.

<img width="294" height="206" alt="image" src="https://github.com/user-attachments/assets/1997efd5-361a-4410-976a-6af96ded3954" />

---

## 어떤 버전을 사용해야 하나요?

### GUI 버전 — 일반 사용자 권장

Python 설치 없이 사용하려면 **GitHub Releases**에서 운영체제에 맞는 파일을 다운로드하세요.

👉 [Latest Release](https://github.com/sukosmos/course-clicker/releases/latest)

| 운영체제 | 파일 |
|---|---|
| Windows 64-bit | `CourseClicker-Windows-x64.zip` |
| macOS Apple Silicon | `CourseClicker-macOS-Apple-Silicon.zip` |
| macOS Intel | `CourseClicker-macOS-Intel.zip` |

macOS에서 최초 실행 시 보안 경고가 표시될 수 있습니다.

이 경우:

`시스템 설정 → 개인정보 보호 및 보안 → 확인 없이 열기`

를 사용하세요.

---

### CLI 버전 — Python 사용이 편한 사용자

이 repository의 `main` branch는 CLI 버전입니다.

```bash
python calibrate.py
python click.py
```

GUI와 executable packaging 관련 코드는 `2-packaging` branch에서 관리합니다.

| Branch | 용도 |
|---|---|
| `main` | CLI 버전 |
| `2-packaging` | GUI / Packaging / Release |

일반 사용자는 branch를 직접 checkout할 필요 없이 **Releases 사용을 권장합니다.**

---

# CLI 설치

## macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pyautogui
```

마우스 제어 권한이 필요한 경우:

`시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용`

에서 Terminal 또는 사용하는 IDE를 허용하세요.

## Windows

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install pyautogui
```

---

# Calibration

PC, OS, 브라우저, 네트워크 환경마다 delay가 다를 수 있으므로  
**실제로 사용할 컴퓨터에서 직접 calibration하는 것을 권장합니다.**

가능하면 수강신청 최소 10분 전에 다시 calibration하세요.

실행:

```bash
python calibrate.py
```

<img width="426" height="162" alt="image" src="https://github.com/user-attachments/assets/5189b1cb-f0ec-46fa-acaf-f4375957e37a" />


Calibration 중에는 기본적으로 클릭 전에 countdown beep가 재생됩니다.

beep 없이 실행:

```bash
python calibrate.py --no-beep
```

기존 calibration 값을 사용하지 않고 넓은 범위부터 다시 탐색:

```bash
python calibrate.py --full
```

---

## Calibration 진행 방법

각 측정마다:

1. Enter 입력
2. 브라우저로 이동
3. 테스트할 버튼 위에 마우스 올리기
4. 자동 클릭
5. 웹페이지에 표시된 서버 시각 `HH:MM:SS` 입력

예:

```text
PC click 목표: 15:03:05.938
click() 호출:  15:03:05.938
서버 표시:     15:03:08
```

---

# Calibration v4

현재 calibration은 최대 8회의 probe 안에서  
**SAFE / EARLY 경계**를 찾는 방식입니다.

전체 흐름:

```text
Previous Calibration
        ↓
Initial Probe
        ↓
Bracket Search
        ↓
Boundary Refinement
        ↓
No-Early Candidate
        ↓
Final Confirmation
```

### 1. Previous Calibration

이전 calibration 결과가 있다면 해당 값 근처에서 탐색을 시작합니다.

따라서 같은 환경에서 다시 calibration할 경우 더 빠르게 경계를 찾을 수 있습니다.

### 2. Bracket Search

측정 결과를 `SAFE` 또는 `EARLY`로 구분하며 두 결과 사이의 경계를 찾습니다.

```text
SAFE -------- boundary -------- EARLY
```

### 3. Boundary Refinement

경계를 찾으면 중간값을 반복 측정하여 범위를 좁힙니다.

기본 목표 boundary gap은 약 `2 ms`입니다.

### 4. No-Early Candidate

찾은 SAFE boundary보다 약간 보수적인 값을 실제 사용할 후보로 선택합니다.

이 값이 `no_early_offset_ms`입니다.

### 5. Final Confirmation

최종 후보를 바로 저장하지 않고 다시 측정합니다.

```text
SAFE
SAFE
```

**2회 연속 SAFE**가 확인되어야 calibration 결과를 저장합니다.

Confirmation 중 EARLY가 발생하면 offset을 더 보수적으로 조정합니다.

검증에 실패하면 기존 config를 덮어쓰지 않습니다.

---

# Calibration 결과

성공하면 주요 값이 `config.json`에 저장됩니다.

예:

```json
{
  "target_datetime": "2026-08-13 10:00:00",
  "effective_offset_ms": 2062.252,
  "no_early_offset_ms": 2060.752,
  "late_margin_ms": 0.0,
  "spin_window_ms": 20
}
```

### `effective_offset_ms`

SAFE / EARLY 경계의 중앙 추정값입니다.

### `no_early_offset_ms`

실제 클릭 scheduling에 사용하는 보수적인 offset입니다.

실전에서는 이 값을 사용하는 것을 권장합니다.

### `late_margin_ms`

추가 safety margin입니다.

기본값은:

```text
0.0 ms
```

입니다.

---

# 실제 실행 — CLI

먼저 `config.json`에서 목표 시각을 설정합니다.

```json
"target_datetime": "2026-08-13 10:00:00"
```

실행:

```bash
python click.py
```

Enter를 눌러 ARM한 뒤:

```text
로그인 완료
→ 과목 선택 완료
→ 브라우저를 앞으로 가져오기
→ 신청 버튼 위에 마우스 올리기
→ 기다리기
```

목표 시각에 현재 마우스 위치가 **한 번 클릭**됩니다.

---

# GUI 사용

Python 또는 터미널 사용이 익숙하지 않다면  
source를 직접 실행하기보다 **GitHub Releases 사용을 권장합니다.**

👉 [Latest Release](https://github.com/sukosmos/course-clicker/releases/latest)

GUI에서는 다음 기능을 제공합니다.

- 목표 날짜 / 시각 설정
- Calibration
- Test Click
- Countdown beep
- Calibration 재측정
- Windows / macOS packaged application

GUI source 및 packaging workflow는 `2-packaging` branch에서 관리합니다.

---

# 주의사항

- Calibration은 가능하면 **실전과 같은 PC, 브라우저, 네트워크**에서 진행하세요.
- 다른 컴퓨터의 calibration 값을 그대로 사용하지 마세요.
- Mac에서 측정한 값을 Windows에서 그대로 사용하지 마세요.
- 환경이 크게 달라졌다면 다시 calibration하세요.
- 실제 클릭 전에는 마우스를 대상 버튼에서 움직이지 마세요.
- Calibration 중 서버 시각을 잘못 입력했다면 해당 측정을 다시 진행하세요.

---

# Project Structure

```text
main
└── CLI version

2-packaging
└── GUI / Packaging / Release

Releases
└── Windows / macOS packaged application
```




