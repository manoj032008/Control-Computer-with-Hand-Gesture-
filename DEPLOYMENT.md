# Hand Gesture Control System — Deployment Guide

## Project Structure (after setup)

```
mk/
├── hand_tracker.py              # Original Python desktop app (unchanged)
├── app.py                       # Flask server (unchanged, for local use)
├── requirements.txt             # Flask app requirements (unchanged)
│
├── browser_version/             # ← DEPLOY THIS FOLDER to Vercel/Netlify
│   ├── index.html               # Full website + live demo
│   ├── gesture_logic.js         # All 19 gestures (unchanged)
│   ├── hand_tracker.py          # Reference copy (documentation)
│   ├── static/                  # Screenshots etc.
│   ├── vercel.json              # ← NEW: Vercel config
│   └── netlify.toml             # ← NEW: Netlify config
│
└── companion/                   # ← NEW: Desktop companion app
    ├── gesture_companion.py     # WebSocket server for OS-level actions
    ├── requirements.txt         # websockets, pyautogui, pycaw, etc.
    ├── start_companion.bat      # Windows one-click launcher
    ├── start_companion.sh       # Linux/macOS launcher
    └── README.md                # Setup instructions
```

---

## Quick Start — Deploy to Vercel (Recommended)

### Option A: CLI deploy
```bash
# Install Vercel CLI if not already installed
npm install -g vercel

# Deploy from the browser_version folder
cd browser_version
vercel --prod
# Follow the prompts; set Root Directory to . (current dir)
```

### Option B: GitHub → Vercel (automatic CI/CD)
1. Push this repo to GitHub
2. Go to https://vercel.com → New Project → Import your repo
3. Set **Root Directory** to `browser_version`
4. Leave all other settings default
5. Click **Deploy**

Vercel reads `vercel.json` automatically and sets the correct COOP/COEP headers
required for MediaPipe WASM (SharedArrayBuffer support).

---

## Quick Start — Deploy to Netlify

### Option A: CLI deploy
```bash
npm install -g netlify-cli
cd browser_version
netlify deploy --prod --dir .
```

### Option B: Drag & Drop
1. Go to https://app.netlify.com/drop
2. Drag the `browser_version/` folder onto the page
3. Done — Netlify reads `netlify.toml` for headers automatically.

---

## Enable OS-Level Gesture Actions (Companion App)

Browser gestures (hover, click, scroll, zoom) work immediately after deployment.
For OS-level actions (volume, brightness, window management, screenshot), users
must run the companion app on their local machine:

### Windows
```batch
cd companion
pip install -r requirements.txt
python gesture_companion.py
# Or double-click start_companion.bat
```

### macOS / Linux
```bash
cd companion
pip install -r requirements.txt
python gesture_companion.py
# Or ./start_companion.sh
```

Once running, the website HUD shows **"Companion: Connected ✓"** and all 19
gestures are fully active.

---

## What Works Where

| Gesture | Browser (Deployed) | + Companion |
|---------|:------------------:|:-----------:|
| Hover / Move Cursor (overlay) | ✅ | ✅ |
| Left Click | ✅ | ✅ |
| Right Click | ⚠️ HUD | ✅ |
| Scroll Up / Down | ✅ | ✅ |
| Zoom In / Out | ✅ (CSS zoom) | ✅ |
| New Tab / Prev Tab | ⚠️ HUD | ✅ |
| Save File (Ctrl+S) | ✅ keyboard event | ✅ |
| Pause / Play (Space) | ✅ keyboard event | ✅ |
| Volume Up / Down | ⚠️ HUD | ✅ |
| Mute Toggle | ⚠️ HUD | ✅ |
| Brightness Up / Down | ⚠️ HUD | ✅ |
| Close Window (Alt+F4) | ⚠️ HUD | ✅ |
| Minimize Window | ⚠️ HUD | ✅ |
| Maximize Window | ⚠️ HUD | ✅ |
| Screenshot | ⚠️ HUD | ✅ |

✅ = executes automatically  
⚠️ HUD = recognized and shown in HUD, requires companion for OS execution

---

## Background Operation

| Scenario | Tracking Status |
|---------|----------------|
| Browser tab active + companion running | Full 19-gesture control |
| Browser tab hidden (switched away) | Browser throttles MediaPipe; tracking slows |
| Companion running (desktop only) | Companion stays alive; browser tracking paused |
| `python hand_tracker.py` (original) | Full background tracking on *all* desktop apps |

> **For true always-on system control**: Run the original `python hand_tracker.py`
> directly. The browser website is for demos and when visitors don't have Python.

---

## Local Testing (before deployment)

```bash
# Test website locally (Python simple server — no Flask needed)
cd browser_version
python -m http.server 8080
# Open http://localhost:8080

# In a separate terminal: test companion
cd companion
python gesture_companion.py
```

> Note: When testing locally over `http://` (not `https://`), some browsers block
> `ws://` connections from `https://` pages. Use the HTTP server above for local
> testing, or Chrome with `--disable-web-security` flag.

---

## Security Notes

- The companion WebSocket is bound exclusively to `127.0.0.1` — no external access is possible.
- The website connects to `ws://127.0.0.1:8765` — this only works if the companion is running on the *same machine as the browser*.
- The companion validates all commands against a strict allowlist of 16 strings.
- No API keys, tokens, or secrets are used anywhere in the system.

---

## Files Modified (Summary)

| File | Change |
|------|--------|
| `browser_version/index.html` | Added companion status badge to HUD; upgraded OS-action handlers to send WebSocket commands when companion is connected; added companion client script block |
| `browser_version/vercel.json` | **New**: Vercel static deployment config with COOP/COEP headers |
| `browser_version/netlify.toml` | **New**: Netlify publish config with security headers |
| `companion/gesture_companion.py` | **New**: Secure WebSocket server for OS-level commands |
| `companion/requirements.txt` | **New**: Companion dependencies |
| `companion/start_companion.bat` | **New**: Windows launcher |
| `companion/start_companion.sh` | **New**: Linux/macOS launcher |
| `companion/README.md` | **New**: Setup guide |

**Zero changes to:**
- `browser_version/gesture_logic.js` (all 19 gestures preserved)
- `browser_version/hand_tracker.py` (reference copy, untouched)
- `hand_tracker.py` (original Python app, untouched)
- `app.py` (Flask server, untouched)
- `requirements.txt` (Flask requirements, untouched)
