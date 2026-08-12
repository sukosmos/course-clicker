# Course Clicker

지정된 서버 목표 시각에 맞춰 **현재 마우스 위치를 한 번 클릭**하는 Python 스크립트입니다.

사용자가 직접 로그인, 과목 선택, 버튼 위치 지정까지 하고, 프로그램은 클릭 타이밍만 자동화합니다.

**중요: config에 실제 날짜와 시각 확인 `"target_datetime": "2026-08-12 10:00:00",`**

**중요: 수강신청 10분 전 캘리브래이션 업데이트합니다, 새로고침 금지**

## 파일

```text
course-clicker/
├── config.json
├── calibrate.py
└── click.py
```

## 설치

### macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pyautogui
```

macOS에서는:

```text
시스템 설정
→ 개인정보 보호 및 보안
→ 손쉬운 사용(Accessibility)
```

에서 Terminal 또는 사용하는 IDE에 권한을 허용해야 할 수 있습니다.

### Windows

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install pyautogui
```

---

# Calibration

각 PC/네트워크마다 delay가 다르므로 **각자 calibration을 해야 합니다.**

<img width="426" height="162" alt="image" src="https://github.com/user-attachments/assets/5189b1cb-f0ec-46fa-acaf-f4375957e37a" />


```bash
python calibrate.py
```

프로그램의 안내에 따라:

1. Enter 입력
2. 브라우저로 이동
3. 테스트할 버튼 위에 마우스 올리기
4. 자동 클릭 후 웹페이지가 보여주는 서버 시각 입력

예:

```text
click() 호출: 15:03:05.500
서버 표시:    15:03:07
```

여러 번 반복하면 프로그램이 가능한 delay 범위를 자동으로 좁힙니다.

성공 예:

```text
delay range:
2061.252 ~ 2067.663 ms

midpoint:
2064.458 ms

no-early offset:
2061.252 ms
```

결과는 자동으로 `config.json`에 저장됩니다.

Mac에서 측정한 값을 Windows에서 그대로 쓰지 말고 **각 컴퓨터에서 따로 calibration**하세요.

---

# config.json

예:

```json
{
  "target_datetime": "2026-08-12 10:00:00",
  "effective_offset_ms": 2064.458,
  "offset_range_ms": [
    2061.252,
    2067.663
  ],
  "no_early_offset_ms": 2061.252,
  "late_margin_ms": 5.0,
  "spin_window_ms": 20
}
```

 `no_early_offset_ms`를 사용하는 것을 권장합니다.

`late_margin_ms`는 추가 안전 여유입니다.

---

# 실제 실행

목표 시각 수정:

```json
"target_datetime": "2026-08-12 10:00:00"
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

목표 시각에 현재 마우스 위치가 한 번 클릭됩니다.

<img width="294" height="206" alt="image" src="https://github.com/user-attachments/assets/1997efd5-361a-4410-976a-6af96ded3954" />

---

# 중요

Calibration은 가능하면 **실전과 같은 PC, 브라우저, 네트워크**에서 진행하세요.

네트워크나 서버 부하가 바뀌면 delay도 달라질 수 있으므로 가능하면 수강신청 직전에 다시 calibration하는 것이 좋습니다.

Calibration 중 서버 시각을 잘못 입력했다면 중단하고 다시 실행하세요.
