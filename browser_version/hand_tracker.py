"""
=============================================================================
 Project: AI-Powered Hand Gesture Recognition Virtual Mouse System  v2.3
 Description: Real-time hand tracking and computer control using MediaPipe,
               OpenCV, NumPy, and PyAutoGUI. Optimized with adaptive One Euro
               filtering, scale-invariant gestures, hysteresis debounce,
               click state machine, and drag detection.

 IMPROVEMENTS IN v2.3 (Enhanced Left-Click Accuracy for Menus):
   - Improved Click State Machine: More robust IDLE → PINCH_CANDIDATE → 
     PINCH_STABILIZING → CLICK_READY → CLICK_EXECUTED → RELEASE workflow
   - Better Drag/Click Separation: Clear distinction between normal click 
     (short stable pinch) vs drag (continuous movement while pinching)
   - Cursor Position Verification: Double-checks cursor hasn't drifted 
     before executing click  41
   - Menu-Optimized Click: Handles rapid pinches for menu navigation
   - Improved Hand Velocity Check: Prevents clicks during hand movement
   - Enhanced Hysteresis: Better pinch enter/exit behavior
   - Debug HUD Enhancement: Shows click state, stability, velocity, frame count
   - Configuration Presets: All tunable parameters in one place

 IMPROVEMENTS IN v2.2 (Enhanced Left-Click System):
   - Click State Machine: Clear IDLE → CONFIRM → EXECUTE → RELEASE workflow
   - Separate Click vs Drag: Normal pinch = one click; continuous movement = drag
   - Cursor Stability Check: Confirms position before executing click
   - Multi-Stage Confirmation: Pinch stability + hand velocity + cursor position
   - Intelligent Drag Detection: Distinguishes intentional drag from accidental movement
   - Configuration Presets: All thresholds in one place for easy tuning
   - Enhanced Debug HUD: Shows click state, stability metrics, and hand velocity

 IMPROVEMENTS IN v2.1:
   - Click-and-Drag Support: Move cursor while holding left click for selecting
     files, dragging elements, and other drag operations
   - Better Click Accuracy: Tighter pinch thresholds and improved stabilization
   - Simultaneous Cursor Movement: Cursor tracks hand movement during click hold
   - mouseDown/mouseUp API: Proper drag operations instead of instant clicks

 IMPROVEMENTS IN v2.1+ (Enhanced Left-Click Accuracy):
   - Pinch Stability Tracking: Requires sustained pinch distance over 4 frames
   - Hand Movement Velocity Detection: Prevents clicks during rapid hand motion
   - Multi-Condition Click Confidence: Validates pinch using multiple factors
   - Smart Click Cooldown: Prevents accidental re-triggering (0.15s minimum)
   - Temporal Confirmation: Two-stage confirmation process for reliable clicks

 Gestures:
   [1] Index Only                      -> Move Cursor (Hover)
   [2] Pinch (Thumb+Idx)               -> Left Click (+ Drag while moving)
   [3] Index + Middle (V-Sign)         -> Right Click
   [4] Index + Pinky (Above Half)      -> Scroll Up
   [5] Index + Pinky (Below Half)      -> Scroll Down
   [6] Five Fingers (Clockwise Rotate) -> Increase Brightness
   [7] Five Fingers (CCW Rotate)       -> Decrease Brightness
   [8] Thumb Up                        -> Volume Up
   [9] Thumb Down                      -> Volume Down
   [10] Thumb + Index + Middle         -> Close Active Window (Alt+F4)
   [11] Thumb + Index + Pinky          -> Screenshot
   [12] Three Fingers (I+M+P)          -> Minimize Window
   [13] Four Fingers (I+M+R+P)         -> Maximize Window
   [14] Index Only, Pointing RIGHT     -> New Tab (Ctrl+T)
   [15] Index Only, Pointing LEFT      -> Previous Tab (Ctrl+Shift+Tab)
   [16] Pinky Only                     -> mute/unmute
   [17] Fist on RIGHT Side             -> Pause Video (Space)
   [18] Fist on LEFT Side              -> Play Video (Space)
   [19] Three Fingers (Index+Mid+Ring) -> Move to Camera: Zoom In / Move away: Zoom Out



 Requirements: pip install opencv-python mediapipe pyautogui numpy screen_brightness_control
=============================================================================
"""

import cv2
import mediapipe as mp
import pyautogui
import numpy as np
import math
import time
import threading

# --------------------------------------------------
# Configuration & Safety
# --------------------------------------------------
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

# --------------------------------------------------
# IMPROVED v2.3: Enhanced Left-Click Configuration Section
# --------------------------------------------------
# --------------------------------------------------
# IMPROVED v2.6: Enhanced Left-Click Configuration Section
# --------------------------------------------------
class ClickConfig:
    """
    Centralized configuration for left-click behavior.
    Tune these values to adjust click sensitivity, precision locking, and stability requirements.
    """
    # Pinch detection thresholds (scale-normalized, 0.0-1.0)
    PINCH_ENTER = 0.28              # Distance to enter pinch state (tips touch naturally)
    PINCH_EXIT = 0.42               # Distance to exit pinch state (hysteresis)
    
    # Pinch confirmation stages (frames at 30 FPS)
    PINCH_CONFIRMATION_FRAMES = 1   # Ultra-fast 1-frame candidate check (~30ms)
    CLICK_STABLE_FRAMES = 1         # 1-frame position stability check (~30ms)
    
    # Deadzone & Click Position Locking (pixels)
    CLICK_DEADZONE = 10             # Deadzone around click anchor position in pixels
    CLICK_ANCHOR_TOLERANCE = 22     # Max pixel drift tolerance for click anchor
    CLICK_POSITION_TOLERANCE = 22   # Max position variance allowed
    
    # Hand velocity thresholds (scaled units per frame)
    CLICK_VELOCITY_THRESHOLD = 0.55  # Allows natural finger closure motion during click
    
    # Click cooldown and release timing (seconds)
    CLICK_COOLDOWN = 0.12           # Minimum seconds between clicks
    RELEASE_CONFIRMATION_FRAMES = 2 # Frames to confirm pinch release before reset
    
    # Drag detection (intentional movement while pinching)
    DRAG_DETECTION_THRESHOLD = 0.50  # Hand velocity threshold to trigger drag mode
    DRAG_MIN_MOVEMENT = 25           # Pixels required to confirm intentional drag
    DRAG_MOVEMENT_TOLERANCE = 12     # Pixels of tolerance during drag to avoid accidental clicks
    
    # Smooth lerp factor for seamless cursor transitions (0.1 = heavy smoothing, 1.0 = instant)
    CURSOR_SMOOTH_ALPHA = 0.50      # Smooth interpolation factor to prevent jumps
    
    # Stability scoring (low variance = stable pinch)
    PINCH_STABILITY_VARIANCE_THRESHOLD = 0.045  # Flexible stability threshold for camera noise
    
    # Position history for drift detection
    POSITION_HISTORY_SIZE = 4       # Number of recent positions to track for drift
    
    # Velocity smoothing (exponential moving average)
    VELOCITY_ALPHA = 0.3            # 0.3 = 30% new, 70% old


# --------------------------------------------------
# IMPROVED v2.6: Precision-Locked Left-Click State Machine
# --------------------------------------------------
class ClickStateMachine:
    """
    State machine for robust left-click detection with precision mode & drag support.
    
    States:
    - IDLE: No pinch detected, ready for new gesture
    - PINCH_CANDIDATE: Pinch detected, tracking live position to prevent premature anchor locking
    - PINCH_STABILIZING: Pinch confirmed, validating cursor position stability
    - CLICK_READY: All checks passed, executing click at frozen anchor position
    - CLICK_EXECUTED: Click executed, waiting for pinch release
    - WAIT_FOR_RELEASE: Pinch released, confirming release before reset
    - DRAG_MODE: Intentional drag operation (continuous movement beyond DRAG_MIN_MOVEMENT)
    """
    
    IDLE = "IDLE"
    PINCH_CANDIDATE = "PINCH_CANDIDATE"
    PINCH_STABILIZING = "PINCH_STABILIZING"
    CLICK_READY = "CLICK_READY"
    CLICK_EXECUTED = "CLICK_EXECUTED"
    WAIT_FOR_RELEASE = "WAIT_FOR_RELEASE"
    DRAG_MODE = "DRAG_MODE"
    
    def __init__(self):
        self.current_state = self.IDLE
        self.frame_count = 0                    # Frames in current state
        self.last_click_time = 0.0
        self.cursor_position_history = []       # Track last N raw cursor positions
        self.cursor_drift_distance = 0.0        # Current frame's drift from anchor
        self.total_hand_movement = 0.0          # Track total movement from anchor for drag detection
        self.state_entry_time = time.time()
        self.click_anchor = None                # Saved cursor position when pinch candidate begins
        self.click_lock_active = False          # True when precision/click-lock is engaged
        self.click_executed_this_pinch = False  # Flag to prevent double-click on single pinch
        
    def reset(self):
        """Reset to IDLE state and clear anchor/lock flags"""
        self.current_state = self.IDLE
        self.frame_count = 0
        self.cursor_position_history = []
        self.cursor_drift_distance = 0.0
        self.total_hand_movement = 0.0
        self.click_anchor = None
        self.click_lock_active = False
        self.click_executed_this_pinch = False
        self.state_entry_time = time.time()
    
    def _check_cursor_stability(self, cursor_pos):
        """
        Check if raw cursor position has stayed stable relative to recent history and click anchor.
        """
        if not cursor_pos:
            return False
        
        self.cursor_position_history.append(cursor_pos)
        if len(self.cursor_position_history) > ClickConfig.POSITION_HISTORY_SIZE:
            self.cursor_position_history.pop(0)
        
        if len(self.cursor_position_history) < 2:
            return True
        
        # Calculate drift relative to click anchor if available, otherwise consecutive history drift
        if self.click_anchor:
            drift_from_anchor = math.hypot(cursor_pos[0] - self.click_anchor[0], cursor_pos[1] - self.click_anchor[1])
            self.cursor_drift_distance = drift_from_anchor
        else:
            max_drift = 0.0
            for i in range(len(self.cursor_position_history) - 1):
                pos1 = self.cursor_position_history[i]
                pos2 = self.cursor_position_history[i + 1]
                drift = math.hypot(pos2[0] - pos1[0], pos2[1] - pos1[1])
                max_drift = max(max_drift, drift)
            self.cursor_drift_distance = max_drift
        
        return self.cursor_drift_distance < ClickConfig.CLICK_POSITION_TOLERANCE
    
    def update_state(self, is_pinching, cursor_pos, hand_velocity, pinch_stable, current_time, stable_hover_pos=None):
        """
        Update state machine based on current conditions.
        
        Returns:
        - should_click: True if normal click should be executed
        - should_drag: True if drag operation should be active
        - is_active: True if actively processing click/drag
        - output_pos: Precision-locked or live cursor position (tuple)
        - is_click_locked: True if Click Lock mode is active
        """
        should_click = False
        should_drag = False
        is_active = False
        output_pos = cursor_pos
        
        if not cursor_pos:
            return should_click, should_drag, is_active, output_pos, self.click_lock_active

        # Lock click anchor at pre-pinch stable hover position if available to prevent drift during finger closure
        anchor_candidate = stable_hover_pos if stable_hover_pos else cursor_pos

        # Track total hand movement relative to click anchor for drag separation
        if self.click_anchor:
            self.total_hand_movement = math.hypot(cursor_pos[0] - self.click_anchor[0], cursor_pos[1] - self.click_anchor[1])
        else:
            self.total_hand_movement = 0.0

        cursor_stable = self._check_cursor_stability(cursor_pos)
        
        # State machine transitions
        if self.current_state == self.IDLE:
            if is_pinching:
                self.current_state = self.PINCH_CANDIDATE
                self.frame_count = 1
                self.click_anchor = anchor_candidate
                self.click_lock_active = True
                self.cursor_position_history = [cursor_pos]
                self.total_hand_movement = 0.0
                self.click_executed_this_pinch = False
                self.state_entry_time = current_time
                output_pos = anchor_candidate
                is_active = True
            else:
                self.click_lock_active = False
            
        elif self.current_state == self.PINCH_CANDIDATE:
            if is_pinching:
                self.frame_count += 1
                self.click_lock_active = True
                output_pos = self.click_anchor if self.click_anchor else cursor_pos

                if self.frame_count >= ClickConfig.PINCH_CONFIRMATION_FRAMES:
                    self.current_state = self.PINCH_STABILIZING
                    self.frame_count = 0
                is_active = True
            else:
                self.reset()
        
        elif self.current_state == self.PINCH_STABILIZING:
            if is_pinching:
                self.frame_count += 1
                output_pos = self.click_anchor if self.click_anchor else cursor_pos
                self.click_lock_active = True if self.click_anchor else False

                if self.frame_count >= ClickConfig.CLICK_STABLE_FRAMES:
                    self.current_state = self.CLICK_READY
                    self.frame_count = 0
                is_active = True
            else:
                self.reset()
        
        elif self.current_state == self.CLICK_READY:
            if is_pinching:
                self.click_lock_active = True
                output_pos = self.click_anchor if self.click_anchor else cursor_pos
                if (not self.click_executed_this_pinch and 
                    (current_time - self.last_click_time) > ClickConfig.CLICK_COOLDOWN):
                    should_click = True
                    self.click_executed_this_pinch = True
                    self.current_state = self.CLICK_EXECUTED
                    self.last_click_time = current_time
                is_active = True
            else:
                self.reset()
        
        elif self.current_state == self.CLICK_EXECUTED:
            if is_pinching:
                self.click_lock_active = True
                output_pos = self.click_anchor if self.click_anchor else cursor_pos
                is_active = True
                self.frame_count = 0
            else:
                self.current_state = self.WAIT_FOR_RELEASE
                self.frame_count = 1
                output_pos = self.click_anchor if self.click_anchor else cursor_pos
        
        elif self.current_state == self.WAIT_FOR_RELEASE:
            if not is_pinching:
                self.frame_count += 1
                output_pos = self.click_anchor if self.click_anchor else cursor_pos
                if self.frame_count >= ClickConfig.RELEASE_CONFIRMATION_FRAMES:
                    self.reset()
            else:
                self.current_state = self.PINCH_CANDIDATE
                self.frame_count = 1
                self.click_executed_this_pinch = False
                self.click_lock_active = True
                output_pos = self.click_anchor if self.click_anchor else cursor_pos
        
        return should_click, should_drag, is_active, output_pos, self.click_lock_active


# --------------------------------------------------
# One Euro Filter & Landmark Smoothing (adaptive low-pass for mouse smoothing)
# --------------------------------------------------
class LowPassFilter:
    def __init__(self, alpha=0.5):
        self.alpha = alpha
        self.y = None

    def __call__(self, x, alpha=None):
        if alpha is not None:
            self.alpha = alpha
        if self.y is None:
            self.y = x
        else:
            self.y = self.alpha * x + (1.0 - self.alpha) * self.y
        return self.y


class LandmarkFilter:
    """
    Adaptive landmark filter to smooth raw MediaPipe landmark points
    before screen coordinate transformation, eliminating optical tracking jitter.
    """
    def __init__(self, alpha=0.45):
        self.alpha = alpha
        self.x = None
        self.y = None

    def __call__(self, raw_x, raw_y):
        if self.x is None or self.y is None:
            self.x = float(raw_x)
            self.y = float(raw_y)
        else:
            self.x = self.alpha * float(raw_x) + (1.0 - self.alpha) * self.x
            self.y = self.alpha * float(raw_y) + (1.0 - self.alpha) * self.y
        return self.x, self.y

    def reset(self):
        self.x = None
        self.y = None


class OneEuroFilter:
    """
    Adaptive low-pass filter to eliminate cursor jitter when static
    while retaining zero-lag tracking during fast hand movement.
    """
    def __init__(self, t0, x0, min_cutoff=0.010, beta=0.04, d_cutoff=1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.x_filt = LowPassFilter(self._alpha(min_cutoff))
        self.dx_filt = LowPassFilter(self._alpha(d_cutoff))
        self.t_prev = t0
        self.x_prev = x0

    def _alpha(self, cutoff, freq=30.0):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        te = 1.0 / max(freq, 1.0)
        return 1.0 / (1.0 + tau / te)

    def reset(self):
        self.x_filt.y = None
        self.dx_filt.y = None
        self.t_prev = None
        self.x_prev = None

    def __call__(self, t, x):
        if self.t_prev is None:
            self.t_prev = t
            self.x_prev = x
            return x
        d_time = t - self.t_prev
        if d_time <= 0.0001:
            return self.x_prev
        # Clamp d_time to avoid spikes from frame timing variations (e.g. 15ms - 50ms)
        d_time = max(0.015, min(0.050, d_time))
        freq = 1.0 / d_time
        dx = (x - self.x_prev) / d_time
        dx_hat = self.dx_filt(dx, self._alpha(self.d_cutoff, freq))
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        x_hat = self.x_filt(x, self._alpha(cutoff, freq))
        self.t_prev = t
        self.x_prev = x_hat
        return x_hat


class PositionFilter:
    """
    Adaptive filter with smooth soft-deadzone dampening.
    Eliminates camera/hand tremors when static while maintaining continuous,
    zero-lag, silky smooth tracking without shaking or stepping.
    """
    def __init__(self, min_cutoff=0.010, beta=0.04, d_cutoff=1.0, deadzone=3.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.deadzone = deadzone
        self.filter_x = None
        self.filter_y = None
        self.last_output = None
        self.last_float = None

    def __call__(self, t, x, y):
        if self.filter_x is None:
            self.filter_x = OneEuroFilter(t, x, self.min_cutoff, self.beta, self.d_cutoff)
            self.filter_y = OneEuroFilter(t, y, self.min_cutoff, self.beta, self.d_cutoff)
            self.last_float = (float(x), float(y))
            self.last_output = (int(round(x)), int(round(y)))
            return self.last_output
        
        fx = self.filter_x(t, x)
        fy = self.filter_y(t, y)
        
        if self.last_float is not None:
            prev_x, prev_y = self.last_float
            dist = math.hypot(fx - prev_x, fy - prev_y)
            
            # Continuous soft deadzone weight using smooth exponential curve
            # Suppresses micro-jitter when hand is stationary, smoothly transitions to 1.0 for motion
            radius = max(self.deadzone, 0.1)
            weight = 1.0 - math.exp(-((dist / radius) ** 2))
            
            out_x = prev_x + (fx - prev_x) * weight
            out_y = prev_y + (fy - prev_y) * weight
        else:
            out_x, out_y = fx, fy
        
        self.last_float = (out_x, out_y)
        self.last_output = (int(round(out_x)), int(round(out_y)))
        return self.last_output

    def reset(self):
        if self.filter_x:
            self.filter_x.reset()
        if self.filter_y:
            self.filter_y.reset()
        self.last_output = None
        self.last_float = None


# --------------------------------------------------
# Pinch Stability Tracker (improved for v2.3)
# --------------------------------------------------
class PinchStabilityTracker:
    """
    Tracks pinch distance stability over time to prevent accidental clicks
    from transient finger movements or camera noise.
    
    IMPROVED in v2.3:
    - Uses variance calculation for robust stability detection
    - Wider history window for better averaging
    """
    def __init__(self, max_history=5):
        self.max_history = max_history
        self.distance_history = []
        self.time_history = []
        self.stability_score = 0.0
        self.is_stable = False

    def update(self, current_distance, current_time):
        """
        Add new pinch distance reading and calculate stability.
        Returns (is_stable, confidence_score)
        """
        self.distance_history.append((current_distance, current_time))
        self.time_history.append(current_time)

        # Keep only recent history (last 5 frames)
        if len(self.distance_history) > self.max_history:
            self.distance_history.pop(0)
            self.time_history.pop(0)

        # Calculate stability: low variance = stable pinch
        if len(self.distance_history) >= 3:
            distances = [d for d, _ in self.distance_history]
            variance = np.var(distances)
            # Low variance (< threshold) = stable; high variance = unstable
            self.stability_score = max(0.0, 1.0 - (variance / ClickConfig.PINCH_STABILITY_VARIANCE_THRESHOLD))
            self.is_stable = variance < ClickConfig.PINCH_STABILITY_VARIANCE_THRESHOLD
        else:
            self.stability_score = 0.0
            self.is_stable = False

        return self.is_stable, self.stability_score

    def reset(self):
        self.distance_history = []
        self.time_history = []
        self.stability_score = 0.0
        self.is_stable = False


# --------------------------------------------------
# Screen Brightness Control Helper
# --------------------------------------------------
def set_screen_brightness(delta):
    """
    Adjust screen brightness by delta (+5 or -5).
    Uses screen_brightness_control with WMI/CimInstance PowerShell fallback.
    """
    try:
        import screen_brightness_control as sbc
        current = sbc.get_brightness()
        if isinstance(current, list):
            current = current[0] if len(current) > 0 else 50
        new_val = max(0, min(100, int(current) + delta))
        sbc.set_brightness(new_val)
    except Exception:
        try:
            import subprocess
            cmd = f"$b = (Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightness).CurrentBrightness; (Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightnessMethods).WmiSetBrightness(1, [math]::Min(100, [math]::Max(0, $b + ({delta}))))"
            subprocess.run(["powershell", "-Command", cmd], capture_output=True)
        except Exception as e:
            print(f"[ERROR] Failed to set brightness: {e}")


# --------------------------------------------------
# Click Ripple Animation
# --------------------------------------------------
class ClickRipple:
    def __init__(self, center):
        self.center = center
        self.radius = 5.0
        self.max_radius = 35.0
        self.speed = 3.5
        self.active = True

    def update(self):
        self.radius += self.speed
        if self.radius >= self.max_radius:
            self.active = False

    def draw(self, frame):
        if not self.active:
            return
        alpha = 1.0 - (self.radius / self.max_radius)
        color = (0, int(140 * alpha), int(255 * alpha))
        thickness = max(1, int(3.0 * alpha))
        overlay = frame.copy()
        cv2.circle(overlay, self.center, int(self.radius), color, thickness, cv2.LINE_AA)
        cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)


# --------------------------------------------------
# Per-Gesture Debounce Stabilizer
# --------------------------------------------------
class GestureStabilizer:
    """
    Requires a gesture to be held N frames before triggering,
    and released M frames before resetting.
    Fires just_triggered=True ONCE per hold (one-shot).
    """
    def __init__(self, enter_frames=4, exit_frames=4):
        self.enter_frames = enter_frames
        self.exit_frames = exit_frames
        self.consecutive = 0
        self.release_frames = 0
        self.triggered = False
        self.active = False

    def update(self, raw_detected: bool):
        """Returns (just_triggered, is_active)"""
        if raw_detected:
            self.consecutive += 1
            self.release_frames = 0
        else:
            self.consecutive = 0
            self.release_frames += 1
            if self.release_frames >= self.exit_frames:
                self.triggered = False
                self.active = False

        just_triggered = False
        if self.consecutive >= self.enter_frames:
            self.active = True
            if not self.triggered:
                self.triggered = True
                just_triggered = True

        return just_triggered, self.active

    def reset(self):
        self.consecutive = 0
        self.release_frames = 0
        self.triggered = False
        self.active = False


# --------------------------------------------------
# Hand Gesture Controller (IMPROVED v2.3)
# --------------------------------------------------
class HandGestureController:
    """
    Accuracy improvements & refactored features:
    - Dynamic scale-invariant distance thresholding for click detection
    - Hysteresis enter/exit thresholds & debouncing stabilizers
    - One Euro Filter for ultra-smooth cursor movement without jitter
    - Peace sign / V-sign (Index + Middle extended) triggers Close Window (Alt+F4)
    - **NEW v2.3**: Improved click state machine with CLICK_READY state
    - **NEW v2.3**: Better cursor position history tracking
    - **NEW v2.3**: Enhanced drag detection for menu operations
    - **NEW v2.3**: More granular HUD display for troubleshooting
    """

    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=1,
            min_detection_confidence=0.75,
            min_tracking_confidence=0.75
        )

        self.screen_w, self.screen_h = pyautogui.size()

        # Active interaction region (maps webcam window area to screen bounds)
        self.X_MIN, self.X_MAX = 0.15, 0.85
        self.Y_MIN, self.Y_MAX = 0.15, 0.75

        # Position filter for smooth cursor tracking (continuous exponential soft-deadzone eliminates shaking)
        self.pos_filter = PositionFilter(min_cutoff=0.010, beta=0.04, d_cutoff=1.0, deadzone=3.0)
        self.lm_filter_index = LandmarkFilter(alpha=0.45)

        # Scale-invariant pinch thresholds (normalized by hand scale)
        self.PINCH_ENTER = ClickConfig.PINCH_ENTER
        self.PINCH_EXIT  = ClickConfig.PINCH_EXIT
        self.THUMB_OPEN  = 0.58

        # IMPROVED v2.6: Click state machine & hover tracking
        self.click_state_machine = ClickStateMachine()
        self.is_pinching = False
        self.last_click_x = 0      # Last recorded click position
        self.last_click_y = 0
        self.last_hover_pos = None
        self.last_stable_hover_pos = None
        self.last_stable_hover_time = 0.0
        self.frame_cursor_pos = (0, 0)
        self.smooth_cursor_x = None
        self.smooth_cursor_y = None
        
        # Drag operation tracking
        self.drag_active = False
        self.click_just_executed = False

        # Pinch stability tracker
        self.pinch_stability = PinchStabilityTracker(max_history=5)
        self.click_confidence = 0.0
        self.raw_pinch_dist = 0.0

        # Hand movement velocity tracking for accidental click prevention
        self.last_palm_pos = None
        self.last_palm_time = None
        self.hand_velocity = 0.0
        self.movement_velocity_threshold = ClickConfig.CLICK_VELOCITY_THRESHOLD

        # Per-gesture debouncing stabilizers (tuned for high accuracy & minimal latency)
        self.stab_click       = GestureStabilizer(enter_frames=2, exit_frames=2)
        self.stab_close       = GestureStabilizer(enter_frames=5, exit_frames=4)
        self.stab_screenshot  = GestureStabilizer(enter_frames=3, exit_frames=3)
        self.stab_minimize    = GestureStabilizer(enter_frames=4, exit_frames=4)
        self.stab_maximize    = GestureStabilizer(enter_frames=4, exit_frames=4)
        self.stab_right_click = GestureStabilizer(enter_frames=2, exit_frames=3)
        self.stab_vol_up      = GestureStabilizer(enter_frames=3, exit_frames=3)
        self.stab_vol_down    = GestureStabilizer(enter_frames=3, exit_frames=3)
        self.stab_bright_up   = GestureStabilizer(enter_frames=2, exit_frames=3)
        self.stab_bright_down = GestureStabilizer(enter_frames=2, exit_frames=3)
        self.stab_scroll_up   = GestureStabilizer(enter_frames=3, exit_frames=4)
        self.stab_scroll_down = GestureStabilizer(enter_frames=3, exit_frames=4)
        self.stab_swipe_right = GestureStabilizer(enter_frames=3, exit_frames=3)
        self.stab_swipe_left  = GestureStabilizer(enter_frames=3, exit_frames=3)
        self.stab_save_file   = GestureStabilizer(enter_frames=4, exit_frames=4)
        self.stab_pause_video = GestureStabilizer(enter_frames=4, exit_frames=3)
        self.stab_play_video  = GestureStabilizer(enter_frames=4, exit_frames=3)
        self.stab_undo        = GestureStabilizer(enter_frames=4, exit_frames=4)
        self.stab_redo        = GestureStabilizer(enter_frames=4, exit_frames=4)
        self.stab_zoom_in     = GestureStabilizer(enter_frames=2, exit_frames=3)
        self.stab_zoom_out    = GestureStabilizer(enter_frames=2, exit_frames=3)
        self.stab_mute        = GestureStabilizer(enter_frames=3, exit_frames=4)

        # Cooldown guards (seconds)
        self.close_cooldown      = 2.5
        self.screenshot_cooldown = 2.0
        self.minimize_cooldown   = 1.5
        self.maximize_cooldown   = 1.5
        self.right_click_cooldown = 0.6
        self.mute_cooldown        = 1.5

        self.last_close_time       = 0.0
        self.last_screenshot_time  = 0.0
        self.last_minimize_time    = 0.0
        self.last_maximize_time    = 0.0
        self.last_right_click_time = 0.0
        self.last_swipe_time       = 0.0
        self.last_save_file_time   = 0.0
        self.last_pause_video_time = 0.0
        self.last_undo_time        = 0.0
        self.last_redo_time        = 0.0
        self.last_play_video_time  = 0.0
        self.last_mute_time        = 0.0
        self.swipe_cooldown        = 0.8  # seconds between New Tab/Previous Tab triggers

        # Repeat intervals for continuous gestures
        self.volume_repeat_interval = 0.18   # ~5 presses/sec while held
        self.last_volume_time       = 0.0
        self.scroll_repeat_interval = 0.04   # smooth, fluid low-latency scroll
        self.last_scroll_time       = 0.0
        self.scroll_amount          = 50     # comfortable smooth scroll amount
        self.smooth_scroll_palm_y   = None   # low-pass filtered vertical position to eliminate shaking
        self._scroll_pose_grace     = 0      # grace frames preventing dropped gestures and lag
        self._neutral_scroll_start_time = 0.0

        # 5-finger rotation brightness control variables
        self.prev_rotation_angle        = None
        self.accumulated_rotation       = 0.0
        self.brightness_repeat_interval = 0.10
        self.last_brightness_time       = 0.0
        self.pending_brightness_delta   = 5
        self.last_scroll_dir            = None
        self.last_fist_side             = None

        # 3-finger zoom control variables (Index + Middle + Ring)
        self.prev_zoom_scale       = None
        self.accumulated_zoom      = 0.0
        self.zoom_repeat_interval  = 0.15
        self.last_zoom_time        = 0.0

        # Delayed filter reset on neutral pose to avoid cursor jumping
        self._neutral_start = None
        self._filter_reset_delay = 0.4

        # Telemetry
        self.hand_scale      = 0.0
        self.current_gesture = "NONE"
        self.cursor_pos      = (0, 0)
        self.raw_thumb_dist  = 0.0
        self.finger_states   = {k: "FOLDED" for k in ["THUMB","INDEX","MIDDLE","RING","PINKY"]}
        self.latest_screenshot_file = ""
        self.screenshot_triggered   = False

    def _evaluate_two_hands(self, hand_landmarks, frame_w, frame_h):
        lms = hand_landmarks.landmark
        pts = [(lm.x * frame_w, lm.y * frame_h) for lm in lms]
        hand_scale = max(math.hypot(pts[9][0] - pts[0][0], pts[9][1] - pts[0][1]), 1.0)
        
        def nd(i, j):
            return math.hypot(pts[i][0]-pts[j][0], pts[i][1]-pts[j][1]) / hand_scale
            
        def is_extended(tip, pip, mcp):
            d_tw = math.hypot(pts[tip][0]-pts[0][0], pts[tip][1]-pts[0][1])
            d_pw = math.hypot(pts[pip][0]-pts[0][0], pts[pip][1]-pts[0][1])
            return (d_tw > d_pw * 1.05) and (nd(tip, mcp) > 0.50)
            
        thumb_open = (nd(4, 5) > getattr(self, 'THUMB_OPEN', 0.58)) and (nd(4, 9) > 0.48)
        idx_ext = is_extended(8, 6, 5)
        mid_ext = is_extended(12, 10, 9)
        rng_ext = is_extended(16, 14, 13)
        pnk_ext = is_extended(20, 18, 17)
        
        fist_closed = (not idx_ext) and (not mid_ext) and (not rng_ext) and (not pnk_ext) and (not thumb_open)
        open_palm = idx_ext and mid_ext and rng_ext and pnk_ext and thumb_open
        
        return fist_closed, open_palm

    def process_frame(self, frame_rgb, frame_w, frame_h):
        result = self.hands.process(frame_rgb)
        
        self.raw_undo = False
        self.raw_redo = False
        
        if result and result.multi_hand_landmarks:
            if len(result.multi_hand_landmarks) >= 2:
                h1 = result.multi_hand_landmarks[0]
                h2 = result.multi_hand_landmarks[1]
                if h1.landmark[9].x < h2.landmark[9].x:
                    lh, rh = h1, h2
                else:
                    lh, rh = h2, h1
                
                lf_closed, lf_palm = self._evaluate_two_hands(lh, frame_w, frame_h)
                rf_closed, rf_palm = self._evaluate_two_hands(rh, frame_w, frame_h)
                
                if lf_closed and rf_palm:
                    self.raw_undo = True
                if lf_palm and rf_closed:
                    self.raw_redo = True
                    
            hand_landmarks = result.multi_hand_landmarks[0]
            self._update_gestures(hand_landmarks, frame_w, frame_h)
            return hand_landmarks
        else:
            self.current_gesture = "NONE"
            self.hand_scale      = 0.0
            self._reset_all()
            self.is_pinching     = False
            self.finger_states   = {k: "FOLDED" for k in self.finger_states}
            self.pos_filter.reset()
            self.lm_filter_index.reset()
            self._neutral_start  = None
            self.last_palm_pos = None
            self.last_palm_time = None
            self.pinch_stability.reset()
            self.click_state_machine.reset()
            self.prev_zoom_scale = None
            self.accumulated_zoom = 0.0
            # Release mouse button if it was held down
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            return None

    def _reset_all(self):
        for s in [self.stab_click, self.stab_close, self.stab_screenshot,
                  self.stab_minimize, self.stab_maximize,
                  self.stab_right_click, self.stab_vol_up, self.stab_vol_down,
                  self.stab_scroll_up, self.stab_scroll_down,
                  self.stab_bright_up, self.stab_bright_down,
                  self.stab_swipe_right, self.stab_swipe_left,
                  self.stab_save_file, self.stab_pause_video, self.stab_play_video,
                  self.stab_zoom_in, self.stab_zoom_out, self.stab_mute,
                  self.stab_undo, self.stab_redo]:
            s.reset()
        self.prev_rotation_angle = None
        self.accumulated_rotation = 0.0
        self.prev_zoom_scale = None
        self.accumulated_zoom = 0.0
        self.smooth_cursor_x = None
        self.smooth_cursor_y = None
        self.smooth_scroll_palm_y = None
        self._scroll_pose_grace = 0

    def _calculate_hand_velocity(self, palm_pos, current_time):
        """
        Calculate hand movement velocity to detect rapid motion.
        Returns velocity in scaled units per frame.
        
        IMPROVED in v2.3:
        - Better velocity smoothing using VELOCITY_ALPHA
        - More stable readings for click prevention
        """
        if self.last_palm_pos is None or self.last_palm_time is None:
            self.last_palm_pos = palm_pos
            self.last_palm_time = current_time
            return 0.0

        dx = palm_pos[0] - self.last_palm_pos[0]
        dy = palm_pos[1] - self.last_palm_pos[1]
        distance = math.hypot(dx, dy)

        dt = current_time - self.last_palm_time
        if dt > 0:
            velocity = distance / dt / self.hand_scale if self.hand_scale > 0 else 0.0
        else:
            velocity = 0.0

        self.last_palm_pos = palm_pos
        self.last_palm_time = current_time

        # Apply exponential smoothing to velocity
        alpha = ClickConfig.VELOCITY_ALPHA
        self.hand_velocity = alpha * velocity + (1.0 - alpha) * self.hand_velocity

        return self.hand_velocity

    def _calculate_click_confidence(self, d_ti, d_tm, idx_ext, mid_ext, 
                                   stability_score, hand_velocity, raw_click):
        """
        Multi-condition click confidence scoring.
        Combines pinch separation ratio, stability, and velocity.
        """
        confidence = 0.0

        # Distance margin ratio (thumb-index vs thumb-middle difference)
        distance_margin = d_tm - d_ti
        if distance_margin > 0.08:
            confidence += 0.35
        elif distance_margin > 0.04:
            confidence += 0.25
        elif distance_margin > 0.01:
            confidence += 0.15

        # Middle finger separation
        if not mid_ext or d_tm > 0.28:
            confidence += 0.25

        # Pinch stability
        confidence += stability_score * 0.20

        # Hand velocity stability
        if hand_velocity < ClickConfig.CLICK_VELOCITY_THRESHOLD * 0.6:
            confidence += 0.20
        elif hand_velocity < ClickConfig.CLICK_VELOCITY_THRESHOLD:
            confidence += 0.10

        return min(1.0, confidence)

    def _update_gestures(self, landmarks, w, h):
        lms = landmarks.landmark
        pts = [(lm.x * w, lm.y * h) for lm in lms]

        # Calculate hand scale baseline: wrist (0) -> middle MCP (9) distance in pixels
        # Ensures distance thresholds adapt automatically whether hand is near or far from camera
        self.hand_scale = max(
            math.hypot(pts[9][0] - pts[0][0], pts[9][1] - pts[0][1]),
            1.0
        )

        # Scale-normalized Euclidean distance function
        def nd(i, j):
            return math.hypot(pts[i][0]-pts[j][0], pts[i][1]-pts[j][1]) / self.hand_scale

        # Geometry finger extension check (robust across hand tilt and rotation)
        def is_extended(tip, pip, mcp):
            d_tw = math.hypot(pts[tip][0]-pts[0][0], pts[tip][1]-pts[0][1])
            d_pw = math.hypot(pts[pip][0]-pts[0][0], pts[pip][1]-pts[0][1])
            min_dist = 0.42 if tip == 20 else 0.50
            return (d_tw > d_pw * 1.04) and (nd(tip, mcp) > min_dist)

        def is_folded(tip, pip, mcp):
            d_tw = math.hypot(pts[tip][0]-pts[0][0], pts[tip][1]-pts[0][1])
            d_pw = math.hypot(pts[pip][0]-pts[0][0], pts[pip][1]-pts[0][1])
            max_dist = 0.38 if tip == 20 else 0.40
            return (d_tw < d_pw * 0.98) or (nd(tip, mcp) < max_dist)

        # Finger states
        thumb_open = False
        idx_ext  = is_extended(8,  6,  5)
        mid_ext  = is_extended(12, 10, 9)
        rng_ext  = is_extended(16, 14, 13)
        pnk_ext  = is_extended(20, 18, 17)

        idx_fold = is_folded(8,  6,  5)
        mid_fold = is_folded(12, 10, 9)
        rng_fold = is_folded(16, 14, 13)
        pnk_fold = is_folded(20, 18, 17)

        # Dual-guard thumb check (MCP distance + Palm center distance)
        dist_thumb_mcp  = nd(4, 5)
        dist_thumb_palm = nd(4, 9)
        thumb_open = (dist_thumb_mcp > self.THUMB_OPEN) and (dist_thumb_palm > 0.48)

        self.finger_states["THUMB"]  = "OPEN"     if thumb_open else "CLOSED"
        self.finger_states["INDEX"]  = "EXTENDED" if idx_ext    else ("FOLDED" if idx_fold  else "HALF")
        self.finger_states["MIDDLE"] = "EXTENDED" if mid_ext    else ("FOLDED" if mid_fold  else "HALF")
        self.finger_states["RING"]   = "EXTENDED" if rng_ext    else ("FOLDED" if rng_fold  else "HALF")
        self.finger_states["PINKY"]  = "EXTENDED" if pnk_ext    else ("FOLDED" if pnk_fold  else "HALF")

        d_ti = nd(4, 8)   # Thumb-Index tip distance
        d_tm = nd(4, 12)  # Thumb-Middle tip distance
        d_tr = nd(4, 16)  # Thumb-Ring tip distance
        self.raw_pinch_dist = d_ti
        self.raw_thumb_dist = dist_thumb_mcp

        # Thumb vertical direction (normalized image-y coordinate delta)
        thumb_dy = (pts[4][1] - pts[0][1]) / self.hand_scale
        thumb_pointing_up   = thumb_dy < -0.35
        thumb_pointing_down = thumb_dy > 0.35

        # Calculate hand velocity for movement-based click prevention
        palm_pos = (pts[9][0], pts[9][1])
        now = time.time()
        hand_velocity = self._calculate_hand_velocity(palm_pos, now)

        # Update pinch stability tracker
        pinch_stable, stability_score = self.pinch_stability.update(d_ti, now)

        # Precise Left-click detection without forcing idx_ext during finger curl
        pinch_thresh = self.PINCH_EXIT if self.is_pinching else self.PINCH_ENTER
        raw_click_base = (d_ti < pinch_thresh) and (d_ti < d_tm - 0.015) and (d_tm > pinch_thresh * 0.75)

        # Calculate click confidence
        self.click_confidence = self._calculate_click_confidence(
            d_ti, d_tm, idx_ext, mid_ext, stability_score, hand_velocity, raw_click_base
        )

        # High confidence proximity validation
        is_confident_pinch = (d_ti < pinch_thresh * 1.05) and (d_tm - d_ti > 0.025) and (self.click_confidence >= 0.50)
        
        raw_click = raw_click_base or is_confident_pinch

        # New gestures:
        # Crossed fingers = index + middle crossed over each other (cross_distance < 0.38) -> Save File (Ctrl+S)
        # Right/left fist = all four fingers folded, detected by palm position.
        fist_closed = (not idx_ext) and (not mid_ext) and (not rng_ext) and (not pnk_ext) and (not thumb_open)
        cross_distance = nd(8, 12)
        # crossed_fingers gesture (Save File) has been removed

        right_side_fist = False
        left_side_fist = False
        fist_deadzone = 0.05
        if fist_closed:
            if lms[9].x > 0.5 + fist_deadzone:
                right_side_fist = True
                self.last_fist_side = "RIGHT"
            elif lms[9].x < 0.5 - fist_deadzone:
                left_side_fist = True
                self.last_fist_side = "LEFT"
            else:
                # Inside the dead zone: keep whichever side was last locked in
                if self.last_fist_side == "RIGHT":
                    right_side_fist = True
                elif self.last_fist_side == "LEFT":
                    left_side_fist = True
        else:
            self.last_fist_side = None

        # ---- Dynamic Gesture Logic & Detection --------------------------

        # 1. Left Click: Pinch (Thumb + Index tip) with enhanced confirmation
        # (raw_click already incorporates improved logic above)

        # 2. Screenshot: Thumb + Index + Pinky extended, Middle & Ring folded
        raw_screenshot = thumb_open and (d_ti > 0.32) and \
                         idx_ext and pnk_ext and (not mid_ext) and (not rng_ext)

        # 3. Hover (Cursor Navigation): Index extended only
        raw_hover = idx_ext and (not mid_ext) and (not rng_ext) and (not pnk_ext)

        # 4. CLOSE WINDOW: Thumb + Index + Middle extended, Ring & Pinky folded
        raw_close = thumb_open and idx_ext and mid_ext and (not rng_ext) and (not pnk_ext) and (d_ti > 0.30)

        # 5. Right Click: Index + Middle finger extended in V-Sign (cross_distance >= 0.28)
        v_sign_right_click = idx_ext and mid_ext and (not rng_ext) and (not pnk_ext) and (not thumb_open) and (cross_distance >= 0.28)
        thumb_mid_pinch = (d_tm < pinch_thresh) and (d_tm < d_ti - 0.02) and (not mid_fold) and (not fist_closed)
        raw_right_click = v_sign_right_click or thumb_mid_pinch

        # 6. MINIMIZE (Three Fingers): Index + Middle + Pinky up, Ring DOWN, thumb closed
        raw_minimize = idx_ext and mid_ext and (not rng_ext) and pnk_ext and (not thumb_open)

        # 7. MAXIMIZE (Four Fingers): Index + Middle + Ring + Pinky up, thumb closed
        raw_maximize = idx_ext and mid_ext and rng_ext and pnk_ext and (not thumb_open)

        # 8. VOLUME UP: Thumbs-up gesture
        raw_vol_up = thumb_open and (not idx_ext) and (not mid_ext) and (not rng_ext) and (not pnk_ext) and \
                     thumb_pointing_up

        # 9. VOLUME DOWN: Thumbs-down gesture
        raw_vol_down = thumb_open and (not idx_ext) and (not mid_ext) and (not rng_ext) and (not pnk_ext) and \
                       thumb_pointing_down

        # 10. POSITION-BASED SCROLLING: Index + Pinky (Rock-on sign)
        # Top half screen (palm_y < 0.5) -> SCROLL UP
        # Bottom half screen (palm_y >= 0.5) -> SCROLL DOWN
        rock_on_raw = idx_ext and pnk_ext and (not mid_ext) and (not rng_ext) and (d_ti > 0.28)
        if rock_on_raw:
            self._scroll_pose_grace = 3
        elif getattr(self, '_scroll_pose_grace', 0) > 0:
            self._scroll_pose_grace -= 1

        is_scroll_pose = (rock_on_raw or getattr(self, '_scroll_pose_grace', 0) > 0)

        raw_palm_y = lms[9].y
        if not hasattr(self, 'smooth_scroll_palm_y') or self.smooth_scroll_palm_y is None:
            self.smooth_scroll_palm_y = raw_palm_y
        else:
            # Heavy low-pass filter (alpha=0.12): eliminates trembling and sudden camera jerks
            self.smooth_scroll_palm_y = 0.12 * raw_palm_y + 0.88 * self.smooth_scroll_palm_y

        palm_y = self.smooth_scroll_palm_y

        # Solid dead-zone & direction-reversal hysteresis
        # Neutral zone: 0.42 to 0.58 (16% dead-zone in middle - zero scrolling)
        # UP active zone: palm_y < 0.40 (offset < -0.10)
        # DOWN active zone: palm_y > 0.60 (offset > +0.10)
        # Exit thresholds: UP stops if palm_y > 0.45; DOWN stops if palm_y < 0.55
        scroll_enter = 0.10
        scroll_exit  = 0.05
        raw_scroll_up = False
        raw_scroll_down = False

        if is_scroll_pose:
            offset = palm_y - 0.5  # negative = above midline

            if self.last_scroll_dir == "UP":
                if offset < -scroll_exit:
                    raw_scroll_up = True
                else:
                    self.last_scroll_dir = None
                    self._neutral_scroll_start_time = now
            elif self.last_scroll_dir == "DOWN":
                if offset > scroll_exit:
                    raw_scroll_down = True
                else:
                    self.last_scroll_dir = None
                    self._neutral_scroll_start_time = now
            else:
                neutral_duration = now - getattr(self, '_neutral_scroll_start_time', 0.0)
                if offset < -scroll_enter and neutral_duration > 0.12:
                    raw_scroll_up = True
                    self.last_scroll_dir = "UP"
                elif offset > scroll_enter and neutral_duration > 0.12:
                    raw_scroll_down = True
                    self.last_scroll_dir = "DOWN"

            self.scroll_amount = 50
            self.scroll_repeat_interval = 0.04
        else:
            self.last_scroll_dir = None

        # 11. ROTATION-BASED BRIGHTNESS: Five Fingers (Full Open Palm, thumb spread out)
        five_open = idx_ext and mid_ext and rng_ext and pnk_ext and thumb_open
        raw_bright_up = False
        raw_bright_down = False

        if five_open:
            self._rotation_grace = 0
            cur_angle = math.atan2(pts[9][1] - pts[0][1], pts[9][0] - pts[0][0])
            if self.prev_rotation_angle is not None:
                d_angle = cur_angle - self.prev_rotation_angle
                while d_angle > math.pi:
                    d_angle -= 2 * math.pi
                while d_angle < -math.pi:
                    d_angle += 2 * math.pi

                # Ignore micro-tremors below noise threshold (< 0.02 rad / ~1.1 deg)
                if abs(d_angle) >= 0.02:
                    self.accumulated_rotation += d_angle

                rot_step_thresh = 0.08  # ~4.6 degrees threshold per step
                if abs(self.accumulated_rotation) >= rot_step_thresh:
                    steps = int(abs(self.accumulated_rotation) / rot_step_thresh)
                    proportional_delta = min(25, max(5, steps * 5))
                    if self.accumulated_rotation > 0:
                        raw_bright_up = True
                        self.pending_brightness_delta = proportional_delta
                    else:
                        raw_bright_down = True
                        self.pending_brightness_delta = -proportional_delta
            self.prev_rotation_angle = cur_angle
        else:
            self._rotation_grace = getattr(self, '_rotation_grace', 0) + 1
            if self._rotation_grace > 5:
                self.prev_rotation_angle = None
                self.accumulated_rotation = 0.0

        # 12/13. SWIPE LEFT / RIGHT (Index Only, held sideways): Prev / Next
        idx_dx = pts[8][0] - pts[5][0]
        idx_dy = pts[8][1] - pts[5][1]
        idx_angle = math.degrees(math.atan2(idx_dy, idx_dx))  # 0=right, -90=up, ±180=left, 90=down

        # Thumb may sit loose when pointing sideways, so it is not required to be closed;
        # d_ti > 0.32 keeps a pinch (left click) from being read as a tab gesture.
        idx_only = idx_ext and (not mid_ext) and (not rng_ext) and (not pnk_ext) and (d_ti > 0.32)
        raw_swipe_right = idx_only and (-45 <= idx_angle <= 45)                 # pointing RIGHT -> New Tab
        raw_swipe_left  = idx_only and (idx_angle >= 135 or idx_angle <= -135)  # pointing LEFT  -> Previous Tab

        # 14. 3-FINGER CAMERA ZOOM IN / ZOOM OUT (Index + Middle + Ring extended, Pinky folded)
        three_finger_zoom = idx_ext and mid_ext and rng_ext and (not pnk_ext) and (not thumb_open)
        raw_zoom_in = False
        raw_zoom_out = False

        if three_finger_zoom:
            self._zoom_grace = 0
            if self.prev_zoom_scale is not None:
                d_scale = (self.hand_scale - self.prev_zoom_scale) / max(self.prev_zoom_scale, 1.0)
                # Ignore micro noise (< 1.5% scale shift)
                if abs(d_scale) >= 0.015:
                    self.accumulated_zoom += d_scale

                zoom_step_thresh = 0.05  # ~5% scale shift per zoom step
                if abs(self.accumulated_zoom) >= zoom_step_thresh:
                    if self.accumulated_zoom > 0:
                        raw_zoom_in = True
                    else:
                        raw_zoom_out = True
            self.prev_zoom_scale = self.hand_scale
        else:
            self._zoom_grace = getattr(self, '_zoom_grace', 0) + 1
            if self._zoom_grace > 5:
                self.prev_zoom_scale = None
                self.accumulated_zoom = 0.0

        # 15. MUTE/UNMUTE: Pinky only
        raw_mute = pnk_ext and (not idx_ext) and (not mid_ext) and (not rng_ext) and (not thumb_open)

        # ---- Priority Chain & Stabilizers -------------------------------
        # Prevents conflicting gesture triggers simultaneously
        jshot, ashot = self.stab_screenshot.update(raw_screenshot)
        jcls,  acls  = self.stab_close.update(raw_close and not ashot)
        jclk,  aclk  = self.stab_click.update(raw_click and not ashot and not acls)
        jrclk, arclk = self.stab_right_click.update(raw_right_click and not ashot and not acls and not aclk)
        jbu,   abu   = self.stab_bright_up.update(raw_bright_up and not ashot and not acls and not aclk and not arclk)
        jbd,   abd   = self.stab_bright_down.update(raw_bright_down and not ashot and not acls and not aclk and not arclk and not abu)
        jvu,   avu   = self.stab_vol_up.update(raw_vol_up and not ashot and not acls and not aclk and not arclk and not abu and not abd)
        jvd,   avd   = self.stab_vol_down.update(raw_vol_down and not ashot and not acls and not aclk and not arclk and not abu and not abd and not avu)
        jmute, amute = self.stab_mute.update(raw_mute and not ashot and not acls and not aclk and not arclk and not abu and not abd and not avu and not avd)
        jsu,   asu   = self.stab_scroll_up.update(raw_scroll_up and not ashot and not acls and not aclk and not arclk and not abu and not abd and not avu and not avd and not amute)
        jsd,   asd   = self.stab_scroll_down.update(raw_scroll_down and not ashot and not acls and not aclk and not arclk and not abu and not abd and not avu and not avd and not asu and not amute)
        jmax,  amax  = self.stab_maximize.update(raw_maximize and not ashot and not acls and not aclk and not arclk and not abu and not abd and not avu and not avd and not asu and not asd and not amute)
        jmin,  amin  = self.stab_minimize.update(raw_minimize and not ashot and not acls and not aclk and not arclk and not abu and not abd and not avu and not avd and not asu and not asd and not amax and not amute)
        jswr,  aswr  = self.stab_swipe_right.update(raw_swipe_right and not ashot and not acls and not aclk and not arclk and not abu and not abd and not avu and not avd and not asu and not asd and not amax and not amin and not amute)
        jswl,  aswl  = self.stab_swipe_left.update(raw_swipe_left and not ashot and not acls and not aclk and not arclk and not abu and not abd and not avu and not avd and not asu and not asd and not amax and not amin and not aswr and not amute)
        jpause, apause = self.stab_pause_video.update(right_side_fist and not ashot and not acls and not aclk and not arclk and not abu and not abd and not avu and not avd and not asu and not asd and not amax and not amin and not aswr and not aswl and not amute)
        jplay, aplay = self.stab_play_video.update(left_side_fist and not ashot and not acls and not aclk and not arclk and not abu and not abd and not avu and not avd and not asu and not asd and not amax and not amin and not aswr and not aswl and not apause and not amute)
        jzi, azi = self.stab_zoom_in.update(raw_zoom_in and not ashot and not acls and not aclk and not arclk and not abu and not abd and not avu and not avd and not asu and not asd and not amax and not amin and not aswr and not aswl and not apause and not aplay and not amute)
        jzo, azo = self.stab_zoom_out.update(raw_zoom_out and not ashot and not acls and not aclk and not arclk and not abu and not abd and not avu and not avd and not asu and not asd and not amax and not amin and not aswr and not aswl and not apause and not aplay and not azi and not amute)
        jundo, aundo = self.stab_undo.update(getattr(self, 'raw_undo', False) and not ashot and not acls and not aclk and not arclk and not abu and not abd and not avu and not avd and not asu and not asd and not amax and not amin and not aswr and not aswl and not apause and not aplay and not azi and not azo and not amute)
        jredo, aredo = self.stab_redo.update(getattr(self, 'raw_redo', False) and not ashot and not acls and not aclk and not arclk and not abu and not abd and not avu and not avd and not asu and not asd and not amax and not amin and not aswr and not aswl and not apause and not aplay and not azi and not azo and not amute and not aundo)
        
        # Allow cursor movement during hover navigation only
        ahov  = raw_hover and not (ashot or acls or aclk or arclk or abu or abd or avu or avd or amute or asu or asd or amax or amin or aswr or aswl or apause or aplay or azi or azo)

        # ---- Execute System Actions --------------------------------------
        if ashot:
            self.current_gesture = "SCREENSHOT"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if jshot and (now - self.last_screenshot_time) > self.screenshot_cooldown:
                self._trigger_screenshot()
                self.last_screenshot_time = now

        elif acls:
            self.current_gesture = "CLOSE WINDOW"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if jcls and (now - self.last_close_time) > self.close_cooldown:
                pyautogui.hotkey('alt', 'F4')
                self.last_close_time = now

        # IMPROVED v2.6: Left click with precision anchor locking & zero-shake landmark filtering
        elif aclk:
            self.is_pinching = True
            self._neutral_start = None
            
            # Use pre-filtered index tip (8) directly to prevent landmark tracking jitter during pinch
            lm8_x, lm8_y = self.lm_filter_index(lms[8].x, lms[8].y)

            # Map target landmark position to screen coordinates
            ix = np.clip((lm8_x - self.X_MIN) / (self.X_MAX - self.X_MIN), 0.0, 1.0)
            iy = np.clip((lm8_y - self.Y_MIN) / (self.Y_MAX - self.Y_MIN), 0.0, 1.0)
            tx, ty = ix * self.screen_w, iy * self.screen_h
            
            # Always pass through position filter for continuous velocity tracking
            sx, sy = self.pos_filter(now, tx, ty)
            raw_fx = int(np.clip(sx, 0, self.screen_w - 1))
            raw_fy = int(np.clip(sy, 0, self.screen_h - 1))
            
            # Update state machine with raw filtered coordinates and pre-pinch stable hover position
            should_click, should_drag, click_active, target_pos, click_locked = self.click_state_machine.update_state(
                is_pinching=True,
                cursor_pos=(raw_fx, raw_fy),
                hand_velocity=hand_velocity,
                pinch_stable=pinch_stable,
                current_time=now,
                stable_hover_pos=(self.last_stable_hover_pos if (now - self.last_stable_hover_time) < 0.5 else None)
            )
            
            target_fx, target_fy = target_pos

            # Instant precision anchor locking when click_locked is active to prevent lerp sliding/shaking
            if click_locked:
                self.smooth_cursor_x, self.smooth_cursor_y = float(target_fx), float(target_fy)
            else:
                if self.smooth_cursor_x is None:
                    self.smooth_cursor_x, self.smooth_cursor_y = float(target_fx), float(target_fy)
                alpha = ClickConfig.CURSOR_SMOOTH_ALPHA
                self.smooth_cursor_x += (target_fx - self.smooth_cursor_x) * alpha
                self.smooth_cursor_y += (target_fy - self.smooth_cursor_y) * alpha

            fx = int(round(self.smooth_cursor_x))
            fy = int(round(self.smooth_cursor_y))
            
            # Move cursor to smoothed target position
            pyautogui.moveTo(fx, fy)
            self.cursor_pos = (fx, fy)
            self.last_click_x = fx
            self.last_click_y = fy
            
            # Map target screen position back to webcam frame coordinates for non-shaking HUD visuals
            frame_fx = int(((fx / self.screen_w) * (self.X_MAX - self.X_MIN) + self.X_MIN) * w)
            frame_fy = int(((fy / self.screen_h) * (self.Y_MAX - self.Y_MIN) + self.Y_MIN) * h)
            self.frame_cursor_pos = (frame_fx, frame_fy)
            
            # Handle state machine action results
            if should_click:
                # Execute click precisely at locked anchor position
                pyautogui.click(fx, fy)
                self.click_just_executed = True
                self.current_gesture = "LEFT CLICK"
            elif click_locked or click_active:
                self.current_gesture = "LEFT CLICK"
            else:
                self.current_gesture = "HOVER"

        elif arclk:
            self.current_gesture = "RIGHT CLICK"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if jrclk and (now - self.last_right_click_time) > self.right_click_cooldown:
                pyautogui.click(button='right')
                self.last_right_click_time = now

        elif abu:
            self.current_gesture = "BRIGHTNESS UP"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if now - self.last_brightness_time > self.brightness_repeat_interval:
                set_screen_brightness(self.pending_brightness_delta)
                self.last_brightness_time = now
                self.accumulated_rotation = 0.0

        elif abd:
            self.current_gesture = "BRIGHTNESS DOWN"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if now - self.last_brightness_time > self.brightness_repeat_interval:
                set_screen_brightness(self.pending_brightness_delta)
                self.last_brightness_time = now
                self.accumulated_rotation = 0.0

        elif avu:
            self.current_gesture = "VOLUME UP"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if now - self.last_volume_time > self.volume_repeat_interval:
                pyautogui.press('volumeup')
                self.last_volume_time = now

        elif avd:
            self.current_gesture = "VOLUME DOWN"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if now - self.last_volume_time > self.volume_repeat_interval:
                pyautogui.press('volumedown')
                self.last_volume_time = now

        elif amute:
            self.current_gesture = "MUTE TOGGLE"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if jmute and (now - self.last_mute_time) > self.mute_cooldown:
                pyautogui.press('volumemute')
                self.last_mute_time = now

        elif asu:
            self.current_gesture = "SCROLL UP"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if now - self.last_scroll_time > self.scroll_repeat_interval:
                pyautogui.scroll(self.scroll_amount)
                self.last_scroll_time = now

        elif asd:
            self.current_gesture = "SCROLL DOWN"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if now - self.last_scroll_time > self.scroll_repeat_interval:
                pyautogui.scroll(-self.scroll_amount)
                self.last_scroll_time = now

        elif amax:
            self.current_gesture = "MAXIMIZE"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if jmax and (now - self.last_maximize_time) > self.maximize_cooldown:
                pyautogui.hotkey('win', 'up')
                self.last_maximize_time = now

        elif amin:
            self.current_gesture = "MINIMIZE"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if jmin and (now - self.last_minimize_time) > self.minimize_cooldown:
                pyautogui.hotkey('win', 'down')
                self.last_minimize_time = now

        elif aswr:
            self.current_gesture = "NEW TAB"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if jswr and (now - self.last_swipe_time) > self.swipe_cooldown:
                pyautogui.hotkey('ctrl', 't')
                self.last_swipe_time = now

        elif aswl:
            self.current_gesture = "PREVIOUS TAB"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if jswl and (now - self.last_swipe_time) > self.swipe_cooldown:
                pyautogui.hotkey('ctrl', 'shift', 'tab')
                self.last_swipe_time = now

        # Save File gesture (Crossed Fingers -> Ctrl+S) has been removed

        elif apause:
            self.current_gesture = "PAUSE VIDEO"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if jpause and (now - self.last_pause_video_time) > self.swipe_cooldown:
                pyautogui.press('space')
                self.last_pause_video_time = now

        elif aundo:
            self.current_gesture = "UNDO"
            self.is_pinching = False
            if getattr(self, 'drag_active', False):
                pyautogui.mouseUp()
                self.drag_active = False
            if jundo and (now - getattr(self, 'last_undo_time', 0)) > self.swipe_cooldown:
                pyautogui.hotkey('ctrl', 'z')
                self.last_undo_time = now

        elif aredo:
            self.current_gesture = "REDO"
            self.is_pinching = False
            if getattr(self, 'drag_active', False):
                pyautogui.mouseUp()
                self.drag_active = False
            if jredo and (now - getattr(self, 'last_redo_time', 0)) > self.swipe_cooldown:
                pyautogui.hotkey('ctrl', 'y')
                self.last_redo_time = now

        elif aplay:
            self.current_gesture = "PLAY VIDEO"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if jplay and (now - self.last_play_video_time) > self.swipe_cooldown:
                pyautogui.press('space')
                self.last_play_video_time = now

        elif azi:
            self.current_gesture = "ZOOM IN"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if now - self.last_zoom_time > self.zoom_repeat_interval:
                pyautogui.hotkey('ctrl', '+')
                self.last_zoom_time = now
                self.accumulated_zoom = 0.0

        elif azo:
            self.current_gesture = "ZOOM OUT"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            if now - self.last_zoom_time > self.zoom_repeat_interval:
                pyautogui.hotkey('ctrl', '-')
                self.last_zoom_time = now
                self.accumulated_zoom = 0.0

        elif ahov:
            self.current_gesture = "HOVER"
            self.is_pinching = False
            self.click_state_machine.reset()
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False

            # Calculate index fingertip position with landmark pre-filtering
            lm8_x, lm8_y = self.lm_filter_index(lms[8].x, lms[8].y)
            ix = np.clip((lm8_x - self.X_MIN) / (self.X_MAX - self.X_MIN), 0.0, 1.0)
            iy = np.clip((lm8_y - self.Y_MIN) / (self.Y_MAX - self.Y_MIN), 0.0, 1.0)
            tx, ty = ix * self.screen_w, iy * self.screen_h
            sx, sy = self.pos_filter(now, tx, ty)
            raw_fx = int(np.clip(sx, 0, self.screen_w - 1))
            raw_fy = int(np.clip(sy, 0, self.screen_h - 1))

            # Initialize smooth cursor on first hover frame or after reset
            if self.smooth_cursor_x is None:
                self.smooth_cursor_x, self.smooth_cursor_y = float(raw_fx), float(raw_fy)

            # Velocity-adaptive alpha: more responsive during fast movement, gentler when slow.
            # Micro-deadzone (< 1.5px) completely suppresses resting jitter on fine targets.
            dist_px = math.hypot(raw_fx - self.smooth_cursor_x, raw_fy - self.smooth_cursor_y)
            if dist_px < 1.5:
                hover_alpha = 0.0
            else:
                t_ramp = float(np.clip((dist_px - 1.5) / 28.0, 0.0, 1.0))
                hover_alpha = 0.22 + 0.53 * t_ramp  # range [0.22, 0.75]

            self.smooth_cursor_x += (raw_fx - self.smooth_cursor_x) * hover_alpha
            self.smooth_cursor_y += (raw_fy - self.smooth_cursor_y) * hover_alpha

            fx = int(round(self.smooth_cursor_x))
            fy = int(round(self.smooth_cursor_y))

            pyautogui.moveTo(fx, fy)
            self.cursor_pos = (fx, fy)
            self.last_hover_pos = (fx, fy)
            if hand_velocity < ClickConfig.CLICK_VELOCITY_THRESHOLD * 1.5:
                self.last_stable_hover_pos = (fx, fy)
                self.last_stable_hover_time = now

            # Map smoothed screen coordinates back to frame coordinates to eliminate HUD point jitter
            frame_fx = int(((fx / self.screen_w) * (self.X_MAX - self.X_MIN) + self.X_MIN) * w)
            frame_fy = int(((fy / self.screen_h) * (self.Y_MAX - self.Y_MIN) + self.Y_MIN) * h)
            self.frame_cursor_pos = (frame_fx, frame_fy)

        else:
            self.current_gesture = "NONE"
            self.is_pinching = False
            if self.drag_active:
                pyautogui.mouseUp()
                self.drag_active = False
            self.click_state_machine.reset()
            self._neutral_start = self._neutral_start or now
            if (now - self._neutral_start) > self._filter_reset_delay:
                self.pos_filter.reset()
                self.lm_filter_index.reset()
                self.smooth_cursor_x = None
                self.smooth_cursor_y = None
                self._neutral_start = None

    def _trigger_screenshot(self):
        """Take a screenshot with timestamp and notification using PyAutoGUI."""
        import os
        try:
            desktop_path = os.path.expanduser("~/Desktop")
            if not os.path.exists(desktop_path):
                desktop_path = os.path.expanduser("~")
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(desktop_path, f"screenshot_{timestamp}.png")
            pyautogui.screenshot(filename)
            self.latest_screenshot_file = filename
            self.screenshot_triggered = True
        except Exception as e:
            print(f"[ERROR] Screenshot failed: {e}")


# --------------------------------------------------
# Drawing Utilities
# --------------------------------------------------
def draw_corner_rect(frame, top_left, bottom_right, color, thickness, corner_len):
    x1, y1 = top_left
    x2, y2 = bottom_right
    for (sx, sy), (ex, ey) in [
        ((x1, y1), (x1 + corner_len, y1)),
        ((x1, y1), (x1, y1 + corner_len)),
        ((x2, y1), (x2 - corner_len, y1)),
        ((x2, y1), (x2, y1 + corner_len)),
        ((x1, y2), (x1 + corner_len, y2)),
        ((x1, y2), (x1, y2 - corner_len)),
        ((x2, y2), (x2 - corner_len, y2)),
        ((x2, y2), (x2, y2 - corner_len)),
    ]:
        cv2.line(frame, (sx, sy), (ex, ey), color, thickness, cv2.LINE_AA)


def draw_styled_hand(frame, landmarks):
    """Draw hand landmarks on frame."""
    h, w, _ = frame.shape
    for i, lm in enumerate(landmarks.landmark):
        x, y = int(lm.x * w), int(lm.y * h)
        if i == 0:
            cv2.circle(frame, (x, y), 4, (0, 255, 255), -1)
        elif i in [4, 8, 12, 16, 20]:
            cv2.circle(frame, (x, y), 3, (0, 140, 255), -1)
        else:
            cv2.circle(frame, (x, y), 2, (200, 200, 200), -1)


def draw_gesture_banner(frame, text, color, timestamp, index=0):
    """Draw gesture banner at bottom of frame."""
    h, w, _ = frame.shape
    y = h - 40 - (index * 35)
    cv2.rectangle(frame, (10, y - 25), (w - 10, y + 5), color, -1)
    cv2.putText(frame, text, (20, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)


def draw_camera_flash(frame, flash_t):
    """Draw white flash overlay for screenshot."""
    if flash_t and (time.time() - flash_t) < 0.2:
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (frame.shape[1], frame.shape[0]), (255, 255, 255), -1)
        cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)


def draw_sci_fi_hud(frame, controller, fps):
    """Draw enhanced HUD with precision debug information (IMPROVED v2.4)."""
    h, w, _ = frame.shape
    font = cv2.FONT_HERSHEY_SIMPLEX
    
    # HUD panel position (top-left)
    ox, oy = 10, 25
    hud_w = 340
    
    # Background panel
    cv2.rectangle(frame, (ox - 5, oy - 22), (ox + hud_w, oy + 235), (0, 0, 0), -1)
    cv2.rectangle(frame, (ox - 5, oy - 22), (ox + hud_w, oy + 235), (0, 200, 200), 2, cv2.LINE_AA)
    
    # Header
    cv2.putText(frame, "AI NEURAL MOUSE v2.4", (ox, oy), font, 0.45, (0, 255, 255), 2, cv2.LINE_AA)
    
    # Current gesture
    cv2.putText(frame, f"GESTURE: {controller.current_gesture}",
                (ox, oy+25), font, 0.37, (255, 255, 0), 1, cv2.LINE_AA)
    
    # Click State & Click Lock status
    click_state_str = controller.click_state_machine.current_state
    state_color = (255, 255, 255)
    if click_state_str == ClickStateMachine.IDLE:
        state_color = (150, 150, 150)
    elif click_state_str == ClickStateMachine.PINCH_CANDIDATE:
        state_color = (200, 200, 100)
    elif click_state_str == ClickStateMachine.PINCH_STABILIZING:
        state_color = (200, 150, 100)
    elif click_state_str == ClickStateMachine.CLICK_READY:
        state_color = (200, 100, 200)
    elif click_state_str == ClickStateMachine.CLICK_EXECUTED:
        state_color = (0, 140, 255)
    elif click_state_str == ClickStateMachine.DRAG_MODE:
        state_color = (0, 255, 140)
    
    cv2.putText(frame, f"CLICK STATE: {click_state_str}",
                (ox, oy+47), font, 0.37, state_color, 1, cv2.LINE_AA)

    # Click Lock Precision Indicator
    lock_active = controller.click_state_machine.click_lock_active
    lock_txt = "CLICK LOCK: ON" if lock_active else "CLICK LOCK: OFF"
    lock_col = (0, 255, 140) if lock_active else (140, 140, 140)
    cv2.putText(frame, lock_txt, (ox + 195, oy + 47), font, 0.35, lock_col, 1, cv2.LINE_AA)

    # Progress bars for gesture stabilizers
    def stab_row(stab, label, y, color):
        pct  = min(stab.consecutive / max(stab.enter_frames, 1), 1.0)
        txt  = f"{label}: {stab.consecutive}/{stab.enter_frames}"
        if stab.triggered:
            txt += " LOCKED"
        cv2.putText(frame, txt, (ox, y), font, 0.37, color, 1, cv2.LINE_AA)
        bx = ox + 140; bw = hud_w - 150
        cv2.rectangle(frame, (bx, y-8), (bx+bw, y-2), (55,55,55), -1)
        fw = int(bw * pct)
        if fw > 0:
            cv2.rectangle(frame, (bx, y-8), (bx+fw, y-2), color, -1)

    stab_row(controller.stab_click, "CLICK", oy+67, (0,140,255))

    # Click Anchor position
    anchor = controller.click_state_machine.click_anchor
    anchor_str = f"({anchor[0]},{anchor[1]})" if anchor else "NONE"
    cv2.putText(frame, f"CLICK ANCHOR: {anchor_str}",
                (ox, oy+105), font, 0.36, (200, 200, 200), 1, cv2.LINE_AA)
    
    # Drift & Confidence
    cv2.putText(frame,
        f"CLICK DRIFT: {controller.click_state_machine.cursor_drift_distance:.0f}px   CONF: {controller.click_confidence:.0%}",
        (ox, oy+125), font, 0.36, (200,200,200), 1, cv2.LINE_AA)
    
    # Hand Velocity & Frame Count
    cv2.putText(frame,
        f"HAND VELOCITY: {controller.hand_velocity:.2f}   FRAMES: {controller.click_state_machine.frame_count}",
        (ox, oy+145), font, 0.36, (200,200,200), 1, cv2.LINE_AA)
    
    # Stability Status & FPS
    is_stable_pos = controller.click_state_machine.cursor_drift_distance < ClickConfig.CLICK_POSITION_TOLERANCE
    cv2.putText(frame,
        f"STABLE: {'YES' if is_stable_pos else 'NO'}   FPS: {fps:.1f}",
        (ox, oy + 165), font, 0.38, (0, 255, 255), 1, cv2.LINE_AA)

    # Draw Half-Screen Boundary Line & Deadzone Overlay
    half_y = h // 2
    deadzone_px = int(h * 0.03)
    
    cv2.line(frame, (0, half_y - deadzone_px), (w, half_y - deadzone_px), (0, 100, 200), 1, cv2.LINE_AA)
    cv2.line(frame, (0, half_y + deadzone_px), (w, half_y + deadzone_px), (0, 100, 200), 1, cv2.LINE_AA)
    cv2.line(frame, (0, half_y), (w, half_y), (0, 165, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, "--- MIDPOINT BOUNDARY (TOP HALF: SCROLL UP | BOTTOM HALF: SCROLL DOWN) ---", (w // 2 - 240, half_y - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 220, 255), 1, cv2.LINE_AA)
def draw_minimal_hud(frame, controller):
    """
    Draws a compact gesture status box (top-left) and a single
    thin yellow horizontal guide line at the vertical midpoint.
    No gesture logic is affected by this function.
    """
    h, w, _ = frame.shape
    font = cv2.FONT_HERSHEY_SIMPLEX

    # --- 1. Compact gesture status box (top-left) ---
    gesture_text = f"GESTURE: {controller.current_gesture}"
    text_scale = 0.45
    text_thick = 1
    (tw, th), baseline = cv2.getTextSize(gesture_text, font, text_scale, text_thick)
    pad = 6
    box_x1, box_y1 = 8, 8
    box_x2 = box_x1 + tw + pad * 2
    box_y2 = box_y1 + th + baseline + pad * 2

    # Dark semi-transparent background
    overlay = frame.copy()
    cv2.rectangle(overlay, (box_x1, box_y1), (box_x2, box_y2), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    # Thin yellow border
    cv2.rectangle(frame, (box_x1, box_y1), (box_x2, box_y2), (0, 220, 255), 1, cv2.LINE_AA)

    # Gesture name text
    text_x = box_x1 + pad
    text_y = box_y1 + pad + th
    cv2.putText(frame, gesture_text, (text_x, text_y), font, text_scale,
                (0, 220, 255), text_thick, cv2.LINE_AA)

    # --- 2. Single thin yellow horizontal center line ---
    mid_y = h // 2
    cv2.line(frame, (0, mid_y), (w, mid_y), (0, 220, 255), 1, cv2.LINE_AA)


if __name__ == "__main__":
    import sys
    print("[SYSTEM] Starting AI Neural Mouse v2.3 with Enhanced Click State Machine...")
    print("[SYSTEM] Press 'q' or 'ESC' in the webcam window to exit.")
    print("[SYSTEM] v2.3 Features: Enhanced Click State Machine | Better Menu Support | Improved Stability")
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("[ERROR] Could not open webcam.")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)

    controller = HandGestureController()
    ripples = []
    banners = []
    flash_t = None
    prev_gesture = "NONE"
    prev_t = time.time()
    fps = 0.0

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape

        now = time.time()
        dt = now - prev_t
        if dt > 0:
            fps = fps * 0.9 + (1.0 / dt) * 0.1
        prev_t = now

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        lm = controller.process_frame(rgb, w, h)

        if lm:
            draw_styled_hand(frame, lm)
            g = controller.current_gesture

            if "LEFT" in g and controller.is_pinching:
                if not ripples or ripples[-1].radius > 15:
                    ripple_pos = controller.frame_cursor_pos if controller.frame_cursor_pos != (0, 0) else (int(lm.landmark[8].x * w), int(lm.landmark[8].y * h))
                    ripples.append(ClickRipple(ripple_pos))

            if controller.screenshot_triggered:
                flash_t = now
                banners.append(("SCREENSHOT SAVED: " + controller.latest_screenshot_file,
                                 (255, 0, 255), now))
                controller.screenshot_triggered = False

            if g != prev_gesture:
                if g == "MINIMIZE":
                    banners.append(("  MINIMIZE WINDOW  (Win+Down)", (0, 220, 255), now))
                elif g == "MAXIMIZE":
                    banners.append(("  MAXIMIZE WINDOW  (Win+Up)", (0, 255, 150), now))
                elif g == "CLOSE WINDOW":
                    banners.append(("  CLOSE WINDOW  (Alt+F4)", (0, 0, 255), now))
                elif g == "BRIGHTNESS UP":
                    delta_txt = f"+{controller.pending_brightness_delta}%" if hasattr(controller, 'pending_brightness_delta') else "+5%"
                    banners.append((f"  BRIGHTNESS {delta_txt}  (CW Rotate)", (255, 220, 0), now))
                elif g == "BRIGHTNESS DOWN":
                    delta_txt = f"{controller.pending_brightness_delta}%" if hasattr(controller, 'pending_brightness_delta') else "-5%"
                    banners.append((f"  BRIGHTNESS {delta_txt}  (CCW Rotate)", (200, 100, 0), now))
                elif g == "SCROLL UP":
                    banners.append(("  SCROLL UP  (Rock Sign - Top Half)", (255, 255, 180), now))
                elif g == "SCROLL DOWN":
                    banners.append(("  SCROLL DOWN  (Rock Sign - Bottom Half)", (180, 180, 255), now))
                elif g == "NEW TAB":
                    banners.append(("  NEW TAB  (Index Pointing Right)", (255, 90, 90), now))
                elif g == "PREVIOUS TAB":
                    banners.append(("  PREVIOUS TAB  (Index Pointing Left)", (90, 255, 90), now))
                elif g == "SAVE FILE":
                    banners.append(("  SAVE FILE  (Ctrl+S)", (255, 180, 0), now))
                elif g == "PAUSE VIDEO":
                    banners.append(("  PAUSE VIDEO  (Space)", (0, 0, 255), now))
                elif g == "PLAY VIDEO":
                    banners.append(("  PLAY VIDEO  (Space)", (0, 255, 0), now))
                elif g == "UNDO":
                    banners.append(("  UNDO  (Ctrl+Z)", (255, 100, 255), now))
                elif g == "REDO":
                    banners.append(("  REDO  (Ctrl+Y)", (100, 255, 255), now))
                elif g == "UNDO":
                    banners.append(("  UNDO  (Ctrl+Z)", (255, 100, 255), now))
                elif g == "REDO":
                    banners.append(("  REDO  (Ctrl+Y)", (100, 255, 255), now))
                elif g == "UNDO":
                    banners.append(("  UNDO  (Ctrl+Z)", (255, 100, 255), now))
                elif g == "REDO":
                    banners.append(("  REDO  (Ctrl+Y)", (100, 255, 255), now))
                elif g == "UNDO":
                    banners.append(("  UNDO  (Ctrl+Z)", (255, 100, 255), now))
                elif g == "REDO":
                    banners.append(("  REDO  (Ctrl+Y)", (100, 255, 255), now))
                elif g == "MUTE TOGGLE":
                    banners.append(("  MUTE / UNMUTE  (Pinky Only)", (120, 120, 255), now))
                elif g == "RIGHT CLICK":
                    banners.append(("  RIGHT CLICK  (Index + Middle)", (150, 255, 200), now))
                elif g == "LEFT CLICK":
                    banners.append(("  LEFT CLICK  (Thumb+Index Pinch)", (0, 140, 255), now))
                elif g == "LEFT DRAG":
                    banners.append(("  LEFT DRAG  (Move While Clicking)", (0, 255, 140), now))

            prev_gesture = g

        for r in ripples[:]:
            r.update()
            if r.active:
                r.draw(frame)
            else:
                ripples.remove(r)

        draw_camera_flash(frame, flash_t)

        active_banners = [(t, c, ts) for t, c, ts in banners if now - ts < 1.8]
        banners[:] = active_banners
        for i, (txt, col, ts) in enumerate(banners[-2:]):
            draw_gesture_banner(frame, txt, col, ts, index=i)

        draw_minimal_hud(frame, controller)

        cv2.imshow("AI Neural Mouse v2.3 - Enhanced Click State Machine", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:
            break

    cap.release()
    cv2.destroyAllWindows()