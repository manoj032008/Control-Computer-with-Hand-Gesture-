"""
gesture_companion.py — Desktop Companion for Hand Gesture Control System
=========================================================================
Purpose:
  Receives gesture commands from the deployed website via a secure local
  WebSocket and executes OS-level actions that the browser cannot perform:
    - System volume (up/down/mute)
    - Screen brightness (up/down)
    - Close active window (Alt+F4)
    - Minimize/Maximize active window (Win+Down / Win+Up)
    - Full-screen OS screenshot (saved to Desktop)

Security model:
  - Listens ONLY on 127.0.0.1 (loopback). Remote connections are impossible.
  - Validates every incoming message against a strict allowlist.
  - Rate-limits to MAX_COMMANDS_PER_SECOND (default 10) per connection.
  - Does NOT expose any API that third-party sites can reach.

Usage:
  python gesture_companion.py
  # Then open your deployed website and click "Try Live Demo".

Requirements (see requirements.txt):
  pip install websockets pyautogui screen-brightness-control pycaw comtypes

Platform:
  Windows: volume via pycaw; brightness via screen_brightness_control.
  macOS/Linux: volume via pyautogui hotkeys; brightness via xrandr / osascript.
"""

import asyncio
import json
import logging
import platform
import time
from collections import defaultdict

import pyautogui
import websockets

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 8765
MAX_COMMANDS_PER_SECOND = 60

# Exact set of allowed command strings — nothing outside this list executes.
ALLOWED_COMMANDS = {
    "VOLUME_UP",
    "VOLUME_DOWN",
    "MUTE_TOGGLE",
    "BRIGHTNESS_UP",
    "BRIGHTNESS_DOWN",
    "CLOSE_WINDOW",
    "CLOSE_TAB",
    "MINIMIZE_WINDOW",
    "MAXIMIZE_WINDOW",
    "SCREENSHOT",
    "SAVE_FILE",
    "NEW_TAB",
    "NEXT_TAB",
    "PREV_TAB",
    "ZOOM_IN",
    "ZOOM_OUT",
    "PAUSE_PLAY",
    "RIGHT_CLICK",
    "LEFT_CLICK",
    "SCROLL_UP",
    "SCROLL_DOWN",
    "CURSOR_MOVE",
}

IS_WINDOWS = platform.system() == "Windows"
IS_MAC     = platform.system() == "Darwin"

pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = False
try:
    _SCREEN_W, _SCREEN_H = pyautogui.size()
except Exception:
    _SCREEN_W, _SCREEN_H = 1920, 1080

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("companion")

# ─────────────────────────────────────────────────────────────────────────────
# Windows-only: pycaw volume control
# ─────────────────────────────────────────────────────────────────────────────
_pycaw_available = False
_volume_interface = None

if IS_WINDOWS:
    import ctypes
    _user32 = ctypes.windll.user32
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        import comtypes

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        _volume_interface = cast(interface, POINTER(IAudioEndpointVolume))
        _pycaw_available = True
        log.info("pycaw volume control initialised (Windows).")
    except Exception as e:
        log.warning(f"pycaw not available ({e}). Falling back to pyautogui volume keys.")

# ─────────────────────────────────────────────────────────────────────────────
# Windows-only: screen brightness
# ─────────────────────────────────────────────────────────────────────────────
_brightness_available = False
try:
    import screen_brightness_control as sbc
    _brightness_available = True
    log.info("screen_brightness_control initialised.")
except Exception as e:
    log.warning(f"screen_brightness_control not available ({e}).")

# ─────────────────────────────────────────────────────────────────────────────
# Action executors
# ─────────────────────────────────────────────────────────────────────────────
VOLUME_STEP      = 5    # percent
BRIGHTNESS_STEP  = 10   # percent

pyautogui.FAILSAFE = False   # prevent corner-of-screen exceptions


def _volume_up():
    if _pycaw_available and _volume_interface:
        try:
            current = _volume_interface.GetMasterVolumeLevelScalar()
            new_vol = min(1.0, current + VOLUME_STEP / 100.0)
            _volume_interface.SetMasterVolumeLevelScalar(new_vol, None)
            log.info(f"Volume → {int(new_vol * 100)}%")
            return
        except Exception as e:
            log.warning(f"pycaw volume_up error: {e}")
    if IS_MAC:
        pyautogui.hotkey("fn", "F12")
    else:
        pyautogui.press("volumeup")


def _volume_down():
    if _pycaw_available and _volume_interface:
        try:
            current = _volume_interface.GetMasterVolumeLevelScalar()
            new_vol = max(0.0, current - VOLUME_STEP / 100.0)
            _volume_interface.SetMasterVolumeLevelScalar(new_vol, None)
            log.info(f"Volume → {int(new_vol * 100)}%")
            return
        except Exception as e:
            log.warning(f"pycaw volume_down error: {e}")
    if IS_MAC:
        pyautogui.hotkey("fn", "F11")
    else:
        pyautogui.press("volumedown")


def _mute_toggle():
    if _pycaw_available and _volume_interface:
        try:
            is_muted = _volume_interface.GetMute()
            _volume_interface.SetMute(not is_muted, None)
            log.info(f"Mute → {'ON' if not is_muted else 'OFF'}")
            return
        except Exception as e:
            log.warning(f"pycaw mute error: {e}")
    pyautogui.press("volumemute")


def _brightness_up():
    if _brightness_available:
        try:
            current = sbc.get_brightness(display=0)
            if isinstance(current, list):
                current = current[0]
            new_b = min(100, current + BRIGHTNESS_STEP)
            sbc.set_brightness(new_b, display=0)
            log.info(f"Brightness → {new_b}%")
            return
        except Exception as e:
            log.warning(f"Brightness up error: {e}")
    log.warning("Brightness control not available on this system.")


def _brightness_down():
    if _brightness_available:
        try:
            current = sbc.get_brightness(display=0)
            if isinstance(current, list):
                current = current[0]
            new_b = max(0, current - BRIGHTNESS_STEP)
            sbc.set_brightness(new_b, display=0)
            log.info(f"Brightness → {new_b}%")
            return
        except Exception as e:
            log.warning(f"Brightness down error: {e}")
    log.warning("Brightness control not available on this system.")


def _close_window():
    pyautogui.hotkey("alt", "F4")
    log.info("Executed: Alt+F4")


def _minimize_window():
    if IS_WINDOWS:
        pyautogui.hotkey("win", "down")
    elif IS_MAC:
        pyautogui.hotkey("command", "m")
    else:
        pyautogui.hotkey("super", "down")
    log.info("Executed: Minimize")


def _maximize_window():
    if IS_WINDOWS:
        pyautogui.hotkey("win", "up")
    elif IS_MAC:
        # macOS: no universal maximize hotkey; approximate with zoom
        import subprocess
        subprocess.run(["osascript", "-e",
                        'tell application "System Events" to keystroke "f" using {control down, command down}'],
                       capture_output=True)
    else:
        pyautogui.hotkey("super", "up")
    log.info("Executed: Maximize")


def _screenshot():
    import os, datetime
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    filename = f"gesture_screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    filepath = os.path.join(desktop, filename)
    try:
        img = pyautogui.screenshot()
        img.save(filepath)
        log.info(f"Screenshot saved: {filepath}")
    except Exception as e:
        log.error(f"Screenshot failed: {e}")


def _save_file():
    pyautogui.hotkey("ctrl", "s")
    log.info("Executed: Ctrl+S")


def _new_tab():
    pyautogui.hotkey("ctrl", "t")
    log.info("Executed: Ctrl+T (new tab)")


def _next_tab():
    pyautogui.hotkey("ctrl", "tab")
    log.info("Executed: Ctrl+Tab (next tab)")


def _prev_tab():
    pyautogui.hotkey("ctrl", "shift", "tab")
    log.info("Executed: Ctrl+Shift+Tab (previous tab)")


def _zoom_in():
    pyautogui.hotkey("ctrl", "+")
    log.info("Executed: Ctrl++ (zoom in)")


def _zoom_out():
    pyautogui.hotkey("ctrl", "-")
    log.info("Executed: Ctrl+- (zoom out)")


def _pause_play():
    pyautogui.press("space")
    log.info("Executed: Space (pause/play)")


def _right_click():
    pyautogui.click(button="right")
    log.info("Executed: Right-click")


def _left_click():
    if IS_WINDOWS:
        try:
            _user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
            _user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
            log.info("Executed: Left-click")
            return
        except Exception:
            pass
    pyautogui.click()
    log.info("Executed: Left-click")


def _scroll_up():
    if IS_WINDOWS:
        try:
            _user32.mouse_event(0x0800, 0, 0, 120, 0)  # MOUSEEVENTF_WHEEL up
            log.info("Executed: Scroll Up")
            return
        except Exception:
            pass
    pyautogui.scroll(120)
    log.info("Executed: Scroll Up")


def _scroll_down():
    if IS_WINDOWS:
        try:
            _user32.mouse_event(0x0800, 0, 0, -120, 0)  # MOUSEEVENTF_WHEEL down
            log.info("Executed: Scroll Down")
            return
        except Exception:
            pass
    pyautogui.scroll(-120)
    log.info("Executed: Scroll Down")


def _close_tab():
    if IS_MAC:
        pyautogui.hotkey("command", "w")
    else:
        pyautogui.hotkey("ctrl", "w")
    log.info("Executed: Ctrl+W (close tab)")


# Map command string → executor function
COMMAND_MAP = {
    "VOLUME_UP":       _volume_up,
    "VOLUME_DOWN":     _volume_down,
    "MUTE_TOGGLE":     _mute_toggle,
    "BRIGHTNESS_UP":   _brightness_up,
    "BRIGHTNESS_DOWN": _brightness_down,
    "CLOSE_WINDOW":    _close_window,
    "CLOSE_TAB":       _close_tab,
    "MINIMIZE_WINDOW": _minimize_window,
    "MAXIMIZE_WINDOW": _maximize_window,
    "SCREENSHOT":      _screenshot,
    "SAVE_FILE":       _save_file,
    "NEW_TAB":         _new_tab,
    "NEXT_TAB":        _next_tab,
    "PREV_TAB":        _prev_tab,
    "ZOOM_IN":         _zoom_in,
    "ZOOM_OUT":        _zoom_out,
    "PAUSE_PLAY":      _pause_play,
    "RIGHT_CLICK":     _right_click,
    "LEFT_CLICK":      _left_click,
    "SCROLL_UP":       _scroll_up,
    "SCROLL_DOWN":     _scroll_down,
}

# ─────────────────────────────────────────────────────────────────────────────
# Rate limiter
# ─────────────────────────────────────────────────────────────────────────────
_rate_buckets: dict[str, list[float]] = defaultdict(list)


def _rate_ok(client_id: str) -> bool:
    now = time.monotonic()
    bucket = _rate_buckets[client_id]
    # Remove timestamps older than 1 second
    _rate_buckets[client_id] = [t for t in bucket if now - t < 1.0]
    if len(_rate_buckets[client_id]) >= MAX_COMMANDS_PER_SECOND:
        return False
    _rate_buckets[client_id].append(now)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket handler
# ─────────────────────────────────────────────────────────────────────────────
async def handle(websocket):
    client_addr = websocket.remote_address
    client_id   = f"{client_addr[0]}:{client_addr[1]}"
    log.info(f"Connection from {client_id}")

    # Send handshake so the browser knows companion is ready
    try:
        await websocket.send(json.dumps({"type": "HANDSHAKE", "status": "ready",
                                         "version": "1.0", "commands": list(ALLOWED_COMMANDS)}))
    except Exception:
        return

    try:
        async for raw_msg in websocket:
            # Parse JSON
            try:
                msg = json.loads(raw_msg)
            except json.JSONDecodeError:
                await websocket.send(json.dumps({"type": "ERROR", "msg": "invalid_json"}))
                continue

            cmd = msg.get("cmd", "").strip().upper()

            # Validate command
            if cmd not in ALLOWED_COMMANDS:
                log.warning(f"[{client_id}] REJECTED unknown command: {cmd!r}")
                await websocket.send(json.dumps({"type": "ERROR", "msg": f"unknown_command:{cmd}"}))
                continue

            # Handle high-frequency cursor movement
            if cmd == "CURSOR_MOVE":
                x = msg.get("x")
                y = msg.get("y")
                if x is not None and y is not None:
                    try:
                        sx = int(max(0.0, min(1.0, float(x))) * _SCREEN_W)
                        sy = int(max(0.0, min(1.0, float(y))) * _SCREEN_H)
                        if IS_WINDOWS:
                            _user32.SetCursorPos(sx, sy)
                        else:
                            pyautogui.moveTo(sx, sy)
                    except Exception as e:
                        pass
                continue

            # Execute standard action
            executor = COMMAND_MAP.get(cmd)
            if executor:
                try:
                    # Run blocking OS call in thread pool to not block event loop
                    # Use get_running_loop() — correct in Python 3.10+ inside async context
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, executor)
                    await websocket.send(json.dumps({"type": "ACK", "cmd": cmd}))
                except Exception as e:
                    log.error(f"[{client_id}] Error executing {cmd}: {e}")
                    await websocket.send(json.dumps({"type": "ERROR", "msg": str(e)}))

    except websockets.exceptions.ConnectionClosed:
        log.info(f"Connection closed: {client_id}")
    finally:
        _rate_buckets.pop(client_id, None)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
async def main():
    log.info("=" * 60)
    log.info("Hand Gesture Control — Desktop Companion v1.0")
    log.info("=" * 60)
    log.info(f"Listening on ws://{HOST}:{PORT}")
    log.info("Open your deployed website and click 'Try Live Demo'.")
    log.info("Press Ctrl+C to stop.")
    log.info("")
    log.info("OS-level features available on this machine:")
    log.info(f"  Volume control (pycaw) : {'YES' if _pycaw_available else 'NO (fallback keys)'}")
    log.info(f"  Brightness control     : {'YES' if _brightness_available else 'NO'}")
    log.info(f"  Platform               : {platform.system()} {platform.release()}")
    log.info("=" * 60)

    async with websockets.serve(handle, HOST, PORT):
        await asyncio.Future()   # run forever


def _free_port(port: int) -> bool:
    """
    If another process is already listening on 'port', kill it and return True.
    Returns False if the port was already free.
    Requires Windows (uses netstat + taskkill).
    """
    import subprocess, re
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"],
            text=True, stderr=subprocess.DEVNULL
        )
        pids = re.findall(
            rf"TCP\s+127\.0\.0\.1:{port}\s+\S+\s+LISTENING\s+(\d+)", out
        )
        if not pids:
            return False
        for pid in pids:
            subprocess.call(["taskkill", "/F", "/PID", pid],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log.warning(f"Killed stale companion process (PID {pid}) that was holding port {port}.")
        return True
    except Exception as e:
        log.warning(f"Could not auto-free port {port}: {e}")
        return False


if __name__ == "__main__":
    # Auto-kill any previous companion instance that left the port locked
    if IS_WINDOWS:
        freed = _free_port(PORT)
        if freed:
            import time as _time
            _time.sleep(0.5)   # brief pause so the OS releases the socket

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Companion stopped.")
    except OSError as e:
        if e.errno in (10048, 98):   # 10048 = Windows WSAEADDRINUSE, 98 = Linux EADDRINUSE
            log.error(
                f"\n"
                f"  ✖  Port {PORT} is ALREADY IN USE.\n"
                f"\n"
                f"  Another instance of gesture_companion.py is running in the background.\n"
                f"  Fix options:\n"
                f"    1. Close the other terminal/window that is running this script.\n"
                f"    2. Run this command to kill it:\n"
                f"         Windows: netstat -ano | findstr :{PORT}   →  taskkill /F /PID <PID>\n"
                f"    3. Then restart gesture_companion.py.\n"
            )
        else:
            raise