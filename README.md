# Course Clicker GUI

A small Tkinter GUI for the calibrated single-click workflow.

## Run from source

```bash
python -m pip install -r requirements.txt
python app.py
```

The app stores user configuration and calibration logs in the platform user-data directory rather than beside the executable.

- macOS: `~/Library/Application Support/CourseClicker/`
- Windows: `%APPDATA%/CourseClicker/`

## Main workflow

1. Run **CALIBRATE** on the same PC/browser/network you plan to use.
2. Run **TEST CLICK** to verify mouse permission, countdown beep, and local trigger timing.
3. Set the target date/time and press **ARM CLICKER**.
4. Put the cursor over the intended button and leave it there.

Calibration is capped at 8 test clicks and uses prior calibration as a starting point when available.

## Packaging note

Build the native executable on the target OS (macOS for `.app`, Windows for `.exe`). The source is structured to work with PyInstaller; `multiprocessing.freeze_support()` is already included.
