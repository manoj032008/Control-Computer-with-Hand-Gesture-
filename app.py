from flask import Flask, render_template, Response, jsonify
import cv2
import time
import threading
import atexit
import platform
import numpy as np

from hand_tracker import (
    HandGestureController,
    draw_styled_hand,
    draw_minimal_hud,
    draw_gesture_banner,
    draw_camera_flash,
    ClickRipple,
)

app = Flask(__name__)

IS_WINDOWS = platform.system() == "Windows"


def open_camera():
    """Open the webcam, using DirectShow only on Windows (it's not valid elsewhere)."""
    camera = None
    if IS_WINDOWS:
        camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if camera is None or not camera.isOpened():
        camera = cv2.VideoCapture(0)
    if camera.isOpened():
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        camera.set(cv2.CAP_PROP_FPS, 30)
    return camera


# Open webcam lazily / robustly
cap = open_camera()
cap_lock = threading.Lock()

if cap.isOpened():
    atexit.register(lambda: cap.release() if cap else None)
else:
    print("[WARNING] Webcam could not be opened at startup. Will retry on request.")
    cap = None

ctrl = HandGestureController()
ctrl_lock = threading.Lock()


def generate_fallback_frame(message="WEBCAM NOT ACCESSIBLE"):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.rectangle(frame, (20, 20), (620, 460), (30, 30, 40), -1)
    cv2.rectangle(frame, (20, 20), (620, 460), (0, 0, 255), 2)
    
    cv2.circle(frame, (320, 240), 40, (50, 50, 70), 1)
    cv2.line(frame, (320, 180), (320, 300), (50, 50, 70), 1)
    cv2.line(frame, (260, 240), (380, 240), (50, 50, 70), 1)
    
    cv2.putText(frame, "SYSTEM STATUS: OFFLINE", (170, 200),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, message, (180, 245),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1, cv2.LINE_AA)
    cv2.putText(frame, "Connect a webcam and restart the application.", (145, 290),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (120, 120, 120), 1, cv2.LINE_AA)
    
    cv2.putText(frame, "ERR_CODE: CAMERA_NOT_FOUND", (35, 440),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (100, 100, 100), 1, cv2.LINE_AA)
    
    ret, buffer = cv2.imencode(".jpg", frame)
    if ret:
        return buffer.tobytes()
    return None


last_cam_retry = 0.0

def generate_frames():
    # These are local to each call, so multiple simultaneous viewers
    # (e.g. "/" and "/live" both open at once) don't stomp on each
    # other's banners/ripples/fps.
    global cap, last_cam_retry
    ripples = []
    banners = []
    flash_t = None
    prev_gesture = "NONE"
    prev_t = time.time()
    fps = 0.0

    while True:
        now = time.time()
        with cap_lock:
            if (cap is None or not cap.isOpened()) and (now - last_cam_retry > 2.0):
                last_cam_retry = now
                if cap is not None:
                    cap.release()
                cap = open_camera()

            if cap is not None and cap.isOpened():
                success, frame = cap.read()
                if not success:
                    # Camera opened but stopped delivering frames: release it
                    # so the retry logic above can reopen it.
                    cap.release()
            else:
                success, frame = False, None

        if not success or frame is None:
            fb = generate_fallback_frame("Camera offline or in use")
            if fb:
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' +
                    fb +
                    b'\r\n'
                )
            time.sleep(0.1)
            continue

        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape

        now = time.time()
        dt = now - prev_t
        if dt > 0:
            fps = fps * 0.9 + (1.0 / dt) * 0.1
        prev_t = now

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        with ctrl_lock:
            lm = ctrl.process_frame(rgb, w, h)
            g = ctrl.current_gesture
            is_pinching = ctrl.is_pinching
            shot_triggered = ctrl.screenshot_triggered
            shot_file = ctrl.latest_screenshot_file
            if shot_triggered:
                ctrl.screenshot_triggered = False
            frame_cursor = getattr(ctrl, 'frame_cursor_pos', (0, 0))
            pending_delta = getattr(ctrl, 'pending_brightness_delta', 5)
            x_min, x_max = ctrl.X_MIN, ctrl.X_MAX
            y_min, y_max = ctrl.Y_MIN, ctrl.Y_MAX

        if lm:
            draw_styled_hand(frame, lm)

            # Click ripple animation
            if "LEFT" in g and is_pinching:
                if not ripples or ripples[-1].radius > 15:
                    ripple_pos = frame_cursor if frame_cursor != (0, 0) else (int(lm.landmark[8].x * w), int(lm.landmark[8].y * h))
                    ripples.append(ClickRipple(ripple_pos))

            # Screenshot flash + banner
            if shot_triggered:
                flash_t = now
                shot_name = shot_file or "screenshot.png"
                banners.append(("SCREENSHOT SAVED: " + shot_name,
                                 (255, 0, 255), now))

            # Action banners on gesture change
            if g != prev_gesture:
                if g == "LEFT CLICK":
                    banners.append(("  LEFT CLICK  (Thumb+Idx Pinch)", (0, 255, 150), now))
                elif g == "LEFT DRAG":
                    banners.append(("  LEFT DRAG  (Move While Clicking)", (0, 255, 140), now))
                elif g == "MINIMIZE":
                    banners.append(("  MINIMIZE WINDOW  (Win+Down)", (0, 220, 255), now))
                elif g == "MAXIMIZE":
                    banners.append(("  MAXIMIZE WINDOW  (Win+Up)", (0, 255, 150), now))
                elif g == "CLOSE WINDOW":
                    banners.append(("  CLOSE WINDOW  (Alt+F4)", (0, 0, 255), now))
                elif g == "BRIGHTNESS UP":
                    banners.append((f"  BRIGHTNESS +{pending_delta}%  (CW Rotate)", (255, 220, 0), now))
                elif g == "BRIGHTNESS DOWN":
                    banners.append((f"  BRIGHTNESS {pending_delta}%  (CCW Rotate)", (200, 100, 0), now))
                elif g == "SCROLL UP":
                    banners.append(("  SCROLL UP  (Rock Sign - Top Half)", (255, 255, 180), now))
                elif g == "SCROLL DOWN":
                    banners.append(("  SCROLL DOWN  (Rock Sign - Bottom Half)", (180, 180, 255), now))
                elif g == "PAUSE VIDEO":
                    banners.append(("  PAUSE VIDEO  (Fist Right)", (255, 100, 100), now))
                elif g == "PLAY VIDEO":
                    banners.append(("  PLAY VIDEO  (Fist Left)", (100, 255, 100), now))
                elif g == "SAVE FILE":
                    banners.append(("  SAVE FILE  (Crossed Index+Middle)", (100, 200, 255), now))
                elif g == "VOLUME UP":
                    banners.append(("  VOLUME UP  (Thumb Up)", (255, 180, 0), now))
                elif g == "VOLUME DOWN":
                    banners.append(("  VOLUME DOWN  (Thumb Down)", (200, 120, 0), now))
                elif g == "MUTE TOGGLE":
                    banners.append(("  MUTE / UNMUTE  (Pinky Only)", (120, 120, 255), now))
                elif g == "RIGHT CLICK":
                    banners.append(("  RIGHT CLICK  (Index + Middle)", (150, 255, 200), now))
                elif g == "PREVIOUS":
                    banners.append(("  PREVIOUS  (Point Right)", (255, 150, 255), now))
                elif g == "NEXT":
                    banners.append(("  NEXT  (Point Left)", (150, 255, 255), now))
                elif g == "ZOOM IN":
                    banners.append(("  ZOOM IN  (3 Fingers Toward Camera)", (0, 255, 255), now))
                elif g == "ZOOM OUT":
                    banners.append(("  ZOOM OUT  (3 Fingers Away From Camera)", (0, 200, 255), now))

            prev_gesture = g
        else:
            prev_gesture = "NONE"

        # Ripples
        for r in ripples[:]:
            r.update()
            if r.active:
                r.draw(frame)
            else:
                ripples.remove(r)

        # Screenshot flash
        draw_camera_flash(frame, flash_t)

        # Banners (prune expired)
        active_banners = [(t, c, ts) for t, c, ts in banners if now - ts < 1.8]
        banners[:] = active_banners
        for i, (txt, col, ts) in enumerate(banners[-2:]):
            draw_gesture_banner(frame, txt, col, ts, index=i)

        # Compact gesture status box + single center line
        draw_minimal_hud(frame, ctrl)

        ret, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ret:
            continue

        frame_bytes = buffer.tobytes()

        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' +
            frame_bytes +
            b'\r\n'
        )


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/live")
def live():
    return render_template("live_demo.html")


@app.route("/video_feed")
def video_feed():
    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/api/start-demo", methods=["GET", "POST"])
def start_demo():
    return jsonify({"status": "running", "message": "Demo is active"})


if __name__ == "__main__":
    # NOTE: debug=True + host="0.0.0.0" would expose the interactive
    # Werkzeug debugger to anyone on the network, which allows remote
    # code execution if any request raises an exception. Keep debug
    # off while listening on all interfaces; set FLASK_DEBUG=1 and
    # bind to 127.0.0.1 instead if you need the debugger locally.
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False, threaded=True)