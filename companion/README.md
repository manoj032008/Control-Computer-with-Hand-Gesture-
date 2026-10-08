# Desktop Companion — Setup Guide

## What is this?

The **Desktop Companion** is a small local Python server that lets the deployed
Hand Gesture Control website execute OS-level actions that browsers cannot
perform directly:

| Action | Requires Companion |
|--------|:-----------------:|
| Volume Up / Down / Mute | ✅ |
| Screen Brightness Up / Down | ✅ |
| Close Active Window (Alt+F4) | ✅ |
| Minimize / Maximize Window | ✅ |
| Full-screen OS Screenshot | ✅ |
| Scroll Up / Down (page) | ❌ (works in browser) |
| Left Click / Hover | ❌ (works in browser) |
| Zoom In / Out (browser) | ❌ (works in browser) |

---

## Requirements

- **Python 3.9+**
- Windows, macOS, or Linux

---

## Installation (Windows)

```batch
# Option A — double-click
start_companion.bat

# Option B — manual
pip install -r requirements.txt
python gesture_companion.py
```

## Installation (macOS / Linux)

```bash
chmod +x start_companion.sh
./start_companion.sh

# Or manually:
pip install -r requirements.txt
python gesture_companion.py
```

---

## How it works

1. The companion binds a WebSocket server on **`ws://127.0.0.1:8765`** (loopback only).
2. When the deployed website detects a gesture that requires OS access, it sends a
   JSON command (e.g. `{"cmd": "VOLUME_UP"}`) to this server.
3. The companion validates the command, checks the rate limit, and executes the action.
4. If the companion is not running, OS-action gestures still show in the HUD as
   **"HUD Only"** — the browser stays fully functional for all other gestures.

---

## Security

- The server **only binds to `127.0.0.1`** — it is physically unreachable from any other machine.
- Only **exactly 16 command strings** are accepted; any other input is silently dropped.
- Commands are limited to **10 per second** per connection.
- No secrets, no tokens, no remote endpoints are exposed.

---

## Companion Status in the Website

Once the companion is running and you click **Try Live Demo**, you will see:
- 🟢 **Companion: Connected** — OS-level gestures are fully active.
- 🔴 **Companion: Not running** — Only browser gestures execute; OS gestures show in HUD.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: pycaw` | Run `pip install pycaw comtypes` (Windows only) |
| `ModuleNotFoundError: screen_brightness_control` | Run `pip install screen-brightness-control` |
| Volume gestures not working | Ensure pycaw installed; check Windows audio permissions |
| Brightness gestures not working | Some laptops restrict brightness via driver (use display settings) |
| Website shows "Companion: Not running" | Make sure `gesture_companion.py` is running *before* clicking Try Live Demo |
| Port 8765 in use | Edit `PORT = 8765` in `gesture_companion.py` and update the website's `COMPANION_WS_URL` |

---

## Background Operation

The companion runs continuously in the background **on your desktop** while you use
the deployed website. This means:

- You can switch browser tabs — the companion remains active.
- You can use other apps — the companion remains active.
- The **webcam tracking** runs in the browser tab; if you switch away, the browser
  may throttle the frame rate. To maintain full tracking across all apps, use the
  original `python hand_tracker.py` directly (standalone desktop app).
