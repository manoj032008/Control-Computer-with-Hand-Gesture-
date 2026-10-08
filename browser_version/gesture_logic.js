/**
 * gesture_logic.js — Full JavaScript translation of hand_tracker.py (v2.3+)
 *
 * SOURCE OF TRUTH: browser_version/hand_tracker.py (reference copy, not modified)
 *
 * All 19 gestures, thresholds, stabilizers, cooldowns, priority chain,
 * ClickStateMachine, LowPassFilter, OneEuroFilter, PositionFilter,
 * PinchStabilityTracker, and GestureStabilizer are faithfully translated
 * from the Python original. No logic has been simplified or invented.
 *
 * BROWSER LIMITATIONS (clearly marked):
 *   - System volume, brightness, Alt+F4, Win+Up/Down: HUD-display only.
 *     These require a desktop backend (e.g. PyAutoGUI / OS API).
 *   - Cursor control (moveTo): simulated via a custom overlay cursor element.
 *   - Screenshot: uses Canvas API (browser-side only).
 *   - Scroll, keyboard events (Space, Ctrl+T, etc.): dispatched natively.
 */

// =============================================================================
// CONFIG — mirrors ClickConfig class in hand_tracker.py exactly
// =============================================================================
export const ClickConfig = {
  PINCH_ENTER:                    0.28,
  PINCH_EXIT:                     0.42,
  PINCH_CONFIRMATION_FRAMES:      1,
  CLICK_STABLE_FRAMES:            1,
  CLICK_DEADZONE:                 10,
  CLICK_ANCHOR_TOLERANCE:         22,
  CLICK_POSITION_TOLERANCE:       22,
  CLICK_VELOCITY_THRESHOLD:       0.55,
  CLICK_COOLDOWN:                 0.12,
  RELEASE_CONFIRMATION_FRAMES:    2,
  DRAG_DETECTION_THRESHOLD:       0.50,
  DRAG_MIN_MOVEMENT:              25,
  DRAG_MOVEMENT_TOLERANCE:        12,
  CURSOR_SMOOTH_ALPHA:            0.50,
  PINCH_STABILITY_VARIANCE_THRESHOLD: 0.045,
  POSITION_HISTORY_SIZE:          4,
  VELOCITY_ALPHA:                 0.3,
};

// =============================================================================
// LowPassFilter — mirrors LowPassFilter class in hand_tracker.py
// =============================================================================
export class LowPassFilter {
  constructor(alpha = 0.5) {
    this.alpha = alpha;
    this.y = null;
  }
  apply(x, alpha = null) {
    if (alpha !== null) this.alpha = alpha;
    if (this.y === null) { this.y = x; }
    else { this.y = this.alpha * x + (1.0 - this.alpha) * this.y; }
    return this.y;
  }
}

// =============================================================================
// OneEuroFilter — mirrors OneEuroFilter class in hand_tracker.py
// =============================================================================
// OneEuroFilter — tuned for low latency and high accuracy
// =============================================================================
export class OneEuroFilter {
  constructor(t0, x0, minCutoff = 0.60, beta = 0.008, dCutoff = 1.0) {
    this.minCutoff = minCutoff;
    this.beta      = beta;
    this.dCutoff   = dCutoff;
    this.xFilt     = new LowPassFilter(this._alpha(minCutoff));
    this.dxFilt    = new LowPassFilter(this._alpha(dCutoff));
    this.tPrev     = t0;
    this.xPrev     = x0;
  }
  _alpha(cutoff, freq = 30.0) {
    const tau = 1.0 / (2.0 * Math.PI * cutoff);
    const te  = 1.0 / Math.max(freq, 1.0);
    return 1.0 / (1.0 + tau / te);
  }
  reset() {
    this.xFilt.y  = null;
    this.dxFilt.y = null;
    this.tPrev = null;
    this.xPrev = null;
  }
  call(t, x) {
    if (this.tPrev === null) { this.tPrev = t; this.xPrev = x; return x; }
    let dt = t - this.tPrev;
    if (dt <= 0.0001) return this.xPrev;
    dt = Math.max(0.015, Math.min(0.050, dt));
    const freq   = 1.0 / dt;
    const dx     = (x - this.xPrev) / dt;
    const dxHat  = this.dxFilt.apply(dx, this._alpha(this.dCutoff, freq));
    const cutoff = this.minCutoff + this.beta * Math.abs(dxHat);
    const xHat   = this.xFilt.apply(x, this._alpha(cutoff, freq));
    this.tPrev = t;
    this.xPrev = xHat;
    return xHat;
  }
}

// =============================================================================
// LandmarkFilter — fast response
// =============================================================================
export class LandmarkFilter {
  constructor(alpha = 0.75) {
    this.alpha = alpha;
    this.x = null; this.y = null;
  }
  apply(rawX, rawY) {
    if (this.x === null) { this.x = rawX; this.y = rawY; }
    else {
      this.x = this.alpha * rawX + (1.0 - this.alpha) * this.x;
      this.y = this.alpha * rawY + (1.0 - this.alpha) * this.y;
    }
    return [this.x, this.y];
  }
  reset() { this.x = null; this.y = null; }
}

// =============================================================================
// PositionFilter — responsive deadzone filter
// =============================================================================
export class PositionFilter {
  constructor(minCutoff = 0.60, beta = 0.008, dCutoff = 1.0, deadzone = 1.5) {
    this.minCutoff = minCutoff; this.beta = beta;
    this.dCutoff   = dCutoff;  this.deadzone = deadzone;
    this.filterX   = null;     this.filterY  = null;
    this.lastOutput = null;    this.lastFloat = null;
  }
  apply(t, x, y) {
    if (this.filterX === null) {
      this.filterX = new OneEuroFilter(t, x, this.minCutoff, this.beta, this.dCutoff);
      this.filterY = new OneEuroFilter(t, y, this.minCutoff, this.beta, this.dCutoff);
      this.lastFloat  = [x, y];
      this.lastOutput = [Math.round(x), Math.round(y)];
      return this.lastOutput;
    }
    const fx = this.filterX.call(t, x);
    const fy = this.filterY.call(t, y);
    if (this.lastFloat) {
      const [px, py] = this.lastFloat;
      const dist   = Math.hypot(fx - px, fy - py);
      const radius = Math.max(this.deadzone, 0.1);
      const weight = 1.0 - Math.exp(-((dist / radius) ** 2));
      const outX   = px + (fx - px) * weight;
      const outY   = py + (fy - py) * weight;
      this.lastFloat  = [outX, outY];
      this.lastOutput = [Math.round(outX), Math.round(outY)];
    } else {
      this.lastFloat  = [fx, fy];
      this.lastOutput = [Math.round(fx), Math.round(fy)];
    }
    return this.lastOutput;
  }
  reset() {
    if (this.filterX) { this.filterX.reset(); this.filterY.reset(); }
    this.lastOutput = null; this.lastFloat = null;
  }
}

// =============================================================================
// PinchStabilityTracker — mirrors PinchStabilityTracker in hand_tracker.py
// =============================================================================
export class PinchStabilityTracker {
  constructor(maxHistory = 5) {
    this.maxHistory = maxHistory;
    this.distanceHistory = [];
    this.stabilityScore  = 0.0;
    this.isStable        = false;
  }
  update(currentDistance, currentTime) {
    this.distanceHistory.push([currentDistance, currentTime]);
    if (this.distanceHistory.length > this.maxHistory)
      this.distanceHistory.shift();
    if (this.distanceHistory.length >= 3) {
      const dists    = this.distanceHistory.map(d => d[0]);
      const mean     = dists.reduce((a, b) => a + b, 0) / dists.length;
      const variance = dists.reduce((a, b) => a + (b - mean) ** 2, 0) / dists.length;
      this.stabilityScore = Math.max(0, 1.0 - variance / ClickConfig.PINCH_STABILITY_VARIANCE_THRESHOLD);
      this.isStable = variance < ClickConfig.PINCH_STABILITY_VARIANCE_THRESHOLD;
    } else {
      this.stabilityScore = 0.0;
      this.isStable = false;
    }
    return [this.isStable, this.stabilityScore];
  }
  reset() {
    this.distanceHistory = [];
    this.stabilityScore = 0.0;
    this.isStable = false;
  }
}

// =============================================================================
// GestureStabilizer — mirrors GestureStabilizer in hand_tracker.py
// Fires justTriggered=true ONCE per hold, requires enterFrames to activate
// =============================================================================
export class GestureStabilizer {
  constructor(enterFrames = 4, exitFrames = 4) {
    this.enterFrames   = enterFrames;
    this.exitFrames    = exitFrames;
    this.consecutive   = 0;
    this.releaseFrames = 0;
    this.triggered     = false;
    this.active        = false;
  }
  /** Returns [justTriggered, isActive] */
  update(rawDetected) {
    if (rawDetected) {
      this.consecutive++;
      this.releaseFrames = 0;
    } else {
      this.consecutive = 0;
      this.releaseFrames++;
      if (this.releaseFrames >= this.exitFrames) {
        this.triggered = false;
        this.active    = false;
      }
    }
    let justTriggered = false;
    if (this.consecutive >= this.enterFrames) {
      this.active = true;
      if (!this.triggered) {
        this.triggered    = true;
        justTriggered = true;
      }
    }
    return [justTriggered, this.active];
  }
  reset() {
    this.consecutive   = 0;
    this.releaseFrames = 0;
    this.triggered     = false;
    this.active        = false;
  }
}

// =============================================================================
// ClickStateMachine — mirrors ClickStateMachine in hand_tracker.py exactly
// =============================================================================
export class ClickStateMachine {
  constructor() {
    this.IDLE              = 'IDLE';
    this.PINCH_CANDIDATE   = 'PINCH_CANDIDATE';
    this.PINCH_STABILIZING = 'PINCH_STABILIZING';
    this.CLICK_READY       = 'CLICK_READY';
    this.CLICK_EXECUTED    = 'CLICK_EXECUTED';
    this.WAIT_FOR_RELEASE  = 'WAIT_FOR_RELEASE';
    this.DRAG_MODE         = 'DRAG_MODE';
    this.reset();
  }
  reset() {
    this.currentState             = this.IDLE;
    this.frameCount               = 0;
    this.lastClickTime            = 0.0;
    this.cursorPositionHistory    = [];
    this.cursorDriftDistance      = 0.0;
    this.totalHandMovement        = 0.0;
    this.stateEntryTime           = performance.now() / 1000;
    this.clickAnchor              = null;
    this.clickLockActive          = false;
    this.clickExecutedThisPinch   = false;
  }
  _checkCursorStability(cursorPos, sf = 1.0) {
    if (!cursorPos) return false;
    this.cursorPositionHistory.push(cursorPos);
    if (this.cursorPositionHistory.length > ClickConfig.POSITION_HISTORY_SIZE)
      this.cursorPositionHistory.shift();
    if (this.cursorPositionHistory.length < 2) return true;
    if (this.clickAnchor) {
      const dx = cursorPos[0] - this.clickAnchor[0];
      const dy = cursorPos[1] - this.clickAnchor[1];
      this.cursorDriftDistance = Math.hypot(dx, dy);
    } else {
      let maxDrift = 0;
      for (let i = 0; i < this.cursorPositionHistory.length - 1; i++) {
        const p1 = this.cursorPositionHistory[i];
        const p2 = this.cursorPositionHistory[i + 1];
        maxDrift = Math.max(maxDrift, Math.hypot(p2[0] - p1[0], p2[1] - p1[1]));
      }
      this.cursorDriftDistance = maxDrift;
    }
    return this.cursorDriftDistance < (ClickConfig.CLICK_POSITION_TOLERANCE * sf);
  }
  updateState(isPinching, cursorPos, handVelocity, pinchStable, currentTime, stableHoverPos = null, sf = 1.0) {
    let shouldClick = false, shouldDrag = false, isActive = false;
    let outputPos = cursorPos;
    if (!cursorPos) return { shouldClick, shouldDrag, isActive, outputPos, isClickLocked: this.clickLockActive };

    const anchorCandidate = stableHoverPos || cursorPos;

    if (this.clickAnchor)
      this.totalHandMovement = Math.hypot(cursorPos[0] - this.clickAnchor[0], cursorPos[1] - this.clickAnchor[1]);
    else
      this.totalHandMovement = 0;

    this._checkCursorStability(cursorPos, sf);

    if (this.currentState === this.IDLE) {
      if (isPinching) {
        this.currentState = this.PINCH_CANDIDATE;
        this.frameCount   = 1;
        this.clickAnchor  = anchorCandidate;
        this.clickLockActive = true;
        this.cursorPositionHistory = [cursorPos];
        this.totalHandMovement = 0;
        this.clickExecutedThisPinch = false;
        this.stateEntryTime = currentTime;
        outputPos = anchorCandidate;
        isActive  = true;
      } else {
        this.clickLockActive = false;
      }
    } else if (this.currentState === this.PINCH_CANDIDATE) {
      if (isPinching) {
        this.frameCount++;
        this.clickLockActive = true;
        outputPos = this.clickAnchor || cursorPos;
        if (this.frameCount >= ClickConfig.PINCH_CONFIRMATION_FRAMES) {
          this.currentState = this.PINCH_STABILIZING;
          this.frameCount   = 0;
        }
        isActive = true;
      } else { this.reset(); }
    } else if (this.currentState === this.PINCH_STABILIZING) {
      if (isPinching) {
        this.frameCount++;
        outputPos = this.clickAnchor || cursorPos;
        this.clickLockActive = !!this.clickAnchor;
        if (this.frameCount >= ClickConfig.CLICK_STABLE_FRAMES) {
          this.currentState = this.CLICK_READY;
          this.frameCount   = 0;
        }
        isActive = true;
      } else { this.reset(); }
    } else if (this.currentState === this.CLICK_READY) {
      if (isPinching) {
        this.clickLockActive = true;
        outputPos = this.clickAnchor || cursorPos;
        if (!this.clickExecutedThisPinch &&
            (currentTime - this.lastClickTime) > ClickConfig.CLICK_COOLDOWN) {
          shouldClick = true;
          this.clickExecutedThisPinch = true;
          this.currentState = this.CLICK_EXECUTED;
          this.lastClickTime = currentTime;
        }
        isActive = true;
      } else { this.reset(); }
    } else if (this.currentState === this.CLICK_EXECUTED) {
      if (isPinching) {
        this.clickLockActive = true;
        outputPos = this.clickAnchor || cursorPos;
        isActive = true; this.frameCount = 0;
      } else {
        this.currentState = this.WAIT_FOR_RELEASE;
        this.frameCount   = 1;
        outputPos = this.clickAnchor || cursorPos;
      }
    } else if (this.currentState === this.WAIT_FOR_RELEASE) {
      if (!isPinching) {
        this.frameCount++;
        outputPos = this.clickAnchor || cursorPos;
        if (this.frameCount >= ClickConfig.RELEASE_CONFIRMATION_FRAMES) this.reset();
      } else {
        this.currentState = this.PINCH_CANDIDATE;
        this.frameCount   = 1;
        this.clickExecutedThisPinch = false;
        this.clickLockActive = true;
        outputPos = this.clickAnchor || cursorPos;
      }
    }
    return { shouldClick, shouldDrag, isActive, outputPos, isClickLocked: this.clickLockActive };
  }
}

// =============================================================================
// GestureEngine — Main class, mirrors HandGestureController._update_gestures()
//
// Usage:
//   const engine = new GestureEngine(videoWidth, videoHeight);
//   engine.onGestureResult = (result) => { /* use result */ };
//   // Each MediaPipe frame:
//   engine.processLandmarks(landmarks);  // landmarks = results.multiHandLandmarks[0]
// =============================================================================
export class GestureEngine {
  constructor(videoW, videoH) {
    this.videoW = videoW;
    this.videoH = videoH;

    // Active region (covers entire screen effortlessly including top navbar & tabs)
    this.X_MIN = 0.08; this.X_MAX = 0.92;
    this.Y_MIN = 0.05; this.Y_MAX = 0.85;

    this.THUMB_OPEN  = 0.58;
    this.PINCH_ENTER = ClickConfig.PINCH_ENTER;
    this.PINCH_EXIT  = ClickConfig.PINCH_EXIT;

    this.isPinching         = false;
    this.handScale          = 0;
    this.currentGesture     = 'NONE';
    this.fingerStates       = { THUMB:'CLOSED', INDEX:'FOLDED', MIDDLE:'FOLDED', RING:'FOLDED', PINKY:'FOLDED' };
    this.rawPinchDist       = 0;
    this.clickConfidence    = 0;
    this.cursorPos          = [0, 0];
    // cursorNorm: normalized [0..1] cursor position — use this for viewport mapping in index.html
    // so the cursor is correctly positioned regardless of videoW/videoH vs window size.
    this.cursorNorm         = [0, 0];
    // lastClickNorm: saved at the moment shouldClick fires, used to dispatch click at exact position.
    this.lastClickNorm      = null;
    this.smoothCursorX      = null;
    this.smoothCursorY      = null;
    // Smoothed normalized cursor (tracks cursorNorm with light EMA to remove residual jitter)
    this.smoothNormX        = null;
    this.smoothNormY        = null;
    this.lastHoverPos       = null;
    this.lastStableHoverPos = null;
    this.lastStableHoverTime = 0;

    this.posFilter      = new PositionFilter(0.010, 0.04, 1.0, 3.0);
    this.lmFilterIndex  = new LandmarkFilter(0.45);
    this.clickStateMachine = new ClickStateMachine();
    this.pinchStability    = new PinchStabilityTracker(5);

    this.lastPalmPos  = null;
    this.lastPalmTime = null;
    this.handVelocity = 0;
    this.dragActive   = false;

    // Per-gesture stabilizers — enter/exit frames match hand_tracker.py exactly
    this.stabClick      = new GestureStabilizer(2, 2);
    this.stabClose      = new GestureStabilizer(5, 4);
    this.stabScreenshot = new GestureStabilizer(3, 3);
    this.stabMinimize   = new GestureStabilizer(4, 4);
    this.stabMaximize   = new GestureStabilizer(4, 4);
    this.stabRightClick = new GestureStabilizer(2, 3);
    this.stabVolUp      = new GestureStabilizer(3, 3);
    this.stabVolDown    = new GestureStabilizer(3, 3);
    this.stabBrightUp   = new GestureStabilizer(2, 3);
    this.stabBrightDown = new GestureStabilizer(2, 3);
    this.stabScrollUp   = new GestureStabilizer(3, 4);
    this.stabScrollDown = new GestureStabilizer(3, 4);
    this.stabSwipeRight = new GestureStabilizer(3, 3);
    this.stabSwipeLeft  = new GestureStabilizer(3, 3);
    this.stabPauseVideo = new GestureStabilizer(4, 3);
    this.stabPlayVideo  = new GestureStabilizer(4, 3);
    this.stabZoomIn     = new GestureStabilizer(2, 3);
    this.stabZoomOut    = new GestureStabilizer(2, 3);
    this.stabMute       = new GestureStabilizer(3, 4);

    // Cooldowns (seconds)
    this.closeCooldown      = 2.5;
    this.screenshotCooldown = 2.0;
    this.minimizeCooldown   = 1.5;
    this.maximizeCooldown   = 1.5;
    this.rightClickCooldown = 0.6;
    this.muteCooldown       = 1.5;
    this.swipeCooldown      = 0.8;

    this.lastCloseTime      = 0;
    this.lastScreenshotTime = 0;
    this.lastMinimizeTime   = 0;
    this.lastMaximizeTime   = 0;
    this.lastRightClickTime = 0;
    this.lastSwipeTime      = 0;
    this.lastPauseVideoTime = 0;
    this.lastPlayVideoTime  = 0;
    this.lastMuteTime       = 0;

    this.volumeRepeatInterval    = 0.18;
    this.lastVolumeTime          = 0;
    this.scrollRepeatInterval    = 0.11;
    this.lastScrollTime          = 0;
    this.scrollAmount            = 80;
    this.smoothScrollPalmY       = null;
    this._scrollPoseGrace        = 0;
    this._neutralStartTime       = 0;
    this.brightnessRepeatInterval = 0.10;
    this.lastBrightnessTime      = 0;
    this.pendingBrightnessDelta  = 5;
    this.zoomRepeatInterval      = 0.15;
    this.lastZoomTime            = 0;

    this.prevRotationAngle   = null;
    this.accumulatedRotation = 0;
    this._rotationGrace      = 0;
    this.prevZoomScale       = null;
    this.accumulatedZoom     = 0;
    this._zoomGrace          = 0;
    this.lastScrollDir       = null;
    this.lastFistSide        = null;
    this._neutralStart       = null;
    this._filterResetDelay   = 0.4;

    this.onGestureResult = null;
  }

  processLandmarks(landmarks) {
    if (!landmarks) { this._handleNoHand(); return; }
    this._updateGestures(landmarks);
  }

  _handleNoHand() {
    this.currentGesture = 'NONE';
    this.handScale      = 0;
    this._resetAll();
    this.isPinching     = false;
    this.fingerStates   = { THUMB:'CLOSED', INDEX:'FOLDED', MIDDLE:'FOLDED', RING:'FOLDED', PINKY:'FOLDED' };
    this.posFilter.reset();
    this.lmFilterIndex.reset();
    this._neutralStart  = null;
    this.lastPalmPos    = null;
    this.lastPalmTime   = null;
    this.pinchStability.reset();
    this.clickStateMachine.reset();
    this.prevZoomScale  = null;
    this.accumulatedZoom = 0;
    this.dragActive     = false;
    this._emit({ gesture: 'NONE', cursorPos: this.cursorPos, fingerStates: this.fingerStates, handScale: 0 });
  }

  _resetAll() {
    for (const s of [
      this.stabClick, this.stabClose, this.stabScreenshot,
      this.stabMinimize, this.stabMaximize, this.stabRightClick,
      this.stabVolUp, this.stabVolDown,
      this.stabScrollUp, this.stabScrollDown,
      this.stabBrightUp, this.stabBrightDown,
      this.stabSwipeRight, this.stabSwipeLeft,
      this.stabPauseVideo, this.stabPlayVideo,
      this.stabZoomIn, this.stabZoomOut, this.stabMute,
    ]) s.reset();
    this.prevRotationAngle   = null;
    this.accumulatedRotation = 0;
    this.prevZoomScale       = null;
    this.accumulatedZoom     = 0;
    this.smoothCursorX       = null;
    this.smoothCursorY       = null;
    this.smoothScrollPalmY   = null;
    this._scrollPoseGrace    = 0;
  }

  _calculateHandVelocity(palmPos, now) {
    if (this.lastPalmPos === null) {
      this.lastPalmPos  = palmPos;
      this.lastPalmTime = now;
      return 0;
    }
    const dist = Math.hypot(palmPos[0] - this.lastPalmPos[0], palmPos[1] - this.lastPalmPos[1]);
    const dt   = now - this.lastPalmTime;
    const rawV = dt > 0 ? (dist / dt / Math.max(this.handScale, 1)) : 0;
    this.lastPalmPos  = palmPos;
    this.lastPalmTime = now;
    const a = ClickConfig.VELOCITY_ALPHA;
    this.handVelocity = a * rawV + (1 - a) * this.handVelocity;
    return this.handVelocity;
  }

  _calcClickConfidence(dTi, dTm, idxExt, midExt, stabilityScore, handVelocity) {
    let c = 0;
    const dm = dTm - dTi;
    if      (dm > 0.08) c += 0.35;
    else if (dm > 0.04) c += 0.25;
    else if (dm > 0.01) c += 0.15;
    if (!midExt || dTm > 0.28) c += 0.25;
    c += stabilityScore * 0.20;
    if      (handVelocity < ClickConfig.CLICK_VELOCITY_THRESHOLD * 0.6) c += 0.20;
    else if (handVelocity < ClickConfig.CLICK_VELOCITY_THRESHOLD)       c += 0.10;
    return Math.min(1.0, c);
  }

  _updateGestures(lms) {
    const W = this.videoW, H = this.videoH;
    const pts = lms.map(lm => [lm.x * W, lm.y * H]);

    this.handScale = Math.max(Math.hypot(pts[9][0]-pts[0][0], pts[9][1]-pts[0][1]), 1);
    const nd = (i,j) => Math.hypot(pts[i][0]-pts[j][0], pts[i][1]-pts[j][1]) / this.handScale;

    const isExtended = (tip, pip, mcp) => {
      const dTW = Math.hypot(pts[tip][0]-pts[0][0], pts[tip][1]-pts[0][1]);
      const dPW = Math.hypot(pts[pip][0]-pts[0][0], pts[pip][1]-pts[0][1]);
      const minDist = tip === 20 ? 0.42 : 0.50;
      return (dTW > dPW * 1.04) && (nd(tip, mcp) > minDist);
    };
    const isFolded = (tip, pip, mcp) => {
      const dTW = Math.hypot(pts[tip][0]-pts[0][0], pts[tip][1]-pts[0][1]);
      const dPW = Math.hypot(pts[pip][0]-pts[0][0], pts[pip][1]-pts[0][1]);
      const maxDist = tip === 20 ? 0.38 : 0.40;
      return (dTW < dPW * 0.98) || (nd(tip, mcp) < maxDist);
    };

    const idxExt = isExtended(8,  6,  5);
    const midExt = isExtended(12, 10, 9);
    const rngExt = isExtended(16, 14, 13);
    const pnkExt = isExtended(20, 18, 17);
    const idxFold = isFolded(8,  6,  5);
    const midFold = isFolded(12, 10, 9);
    const rngFold = isFolded(16, 14, 13);
    const pnkFold = isFolded(20, 18, 17);

    const distThumbMcp  = nd(4, 5);
    const distThumbPalm = nd(4, 9);
    const thumbOpen = (distThumbMcp > this.THUMB_OPEN) && (distThumbPalm > 0.48);

    this.fingerStates = {
      THUMB:  thumbOpen ? 'OPEN'     : 'CLOSED',
      INDEX:  idxExt   ? 'EXTENDED' : (idxFold ? 'FOLDED' : 'HALF'),
      MIDDLE: midExt   ? 'EXTENDED' : (midFold ? 'FOLDED' : 'HALF'),
      RING:   rngExt   ? 'EXTENDED' : (rngFold ? 'FOLDED' : 'HALF'),
      PINKY:  pnkExt   ? 'EXTENDED' : (pnkFold ? 'FOLDED' : 'HALF'),
    };

    const dTi = nd(4, 8);
    const dTm = nd(4, 12);
    this.rawPinchDist = dTi;

    const thumbDy = (pts[4][1] - pts[0][1]) / this.handScale;
    const thumbPointingUp   = thumbDy < -0.35;
    const thumbPointingDown = thumbDy >  0.35;

    const palmPos = [pts[9][0], pts[9][1]];
    const now = performance.now() / 1000;
    const handVelocity = this._calculateHandVelocity(palmPos, now);
    const [pinchStable, stabilityScore] = this.pinchStability.update(dTi, now);

    const pinchThresh  = this.isPinching ? this.PINCH_EXIT : this.PINCH_ENTER;
    const rawClickBase = (dTi < pinchThresh) && (dTi < dTm - 0.015) && (dTm > pinchThresh * 0.75);
    this.clickConfidence = this._calcClickConfidence(dTi, dTm, idxExt, midExt, stabilityScore, handVelocity);
    const isConfidentPinch = (dTi < pinchThresh * 1.05) && (dTm - dTi > 0.025) && (this.clickConfidence >= 0.50);
    const rawClick = rawClickBase || isConfidentPinch;

    // Fist
    const fistClosed = !idxExt && !midExt && !rngExt && !pnkExt && !thumbOpen;
    const crossDistance = nd(8, 12);
    const fistDeadzone = 0.05;
    let rightSideFist = false, leftSideFist = false;
    if (fistClosed) {
      if      (lms[9].x > 0.5 + fistDeadzone) { rightSideFist = true;  this.lastFistSide = 'RIGHT'; }
      else if (lms[9].x < 0.5 - fistDeadzone) { leftSideFist  = true;  this.lastFistSide = 'LEFT';  }
      else {
        if      (this.lastFistSide === 'RIGHT') rightSideFist = true;
        else if (this.lastFistSide === 'LEFT')  leftSideFist  = true;
      }
    } else { this.lastFistSide = null; }

    // Raw gesture conditions
    const rawHover = idxExt && !midExt && !rngExt && !pnkExt;
    const vSignRightClick = idxExt && midExt && !rngExt && !pnkExt && !thumbOpen && (crossDistance >= 0.28);
    const thumbMidPinch   = (dTm < pinchThresh) && (dTm < dTi - 0.02) && !midFold && !fistClosed;
    const rawRightClick   = vSignRightClick || thumbMidPinch;

    // Scroll (rock-on position-based, mirrors hand_tracker.py exactly)
    const rockOnRaw = idxExt && pnkExt && !midExt && !rngExt && (dTi > 0.28);
    if (rockOnRaw) {
      this._scrollPoseGrace = 3;
    } else if ((this._scrollPoseGrace || 0) > 0) {
      this._scrollPoseGrace--;
    }
    const rockOn = rockOnRaw || ((this._scrollPoseGrace || 0) > 0);

    const rawPalmY = lms[9].y;
    if (this.smoothScrollPalmY === null || this.smoothScrollPalmY === undefined) {
      this.smoothScrollPalmY = rawPalmY;
    } else {
      // Heavy low-pass filter (alpha=0.12): eliminates trembling and sudden camera jerks
      this.smoothScrollPalmY = 0.12 * rawPalmY + 0.88 * this.smoothScrollPalmY;
    }
    const palmY = this.smoothScrollPalmY;

    // Solid dead-zone & direction-reversal hysteresis
    // Neutral zone: 0.42 to 0.58 (16% dead-zone in middle - zero scrolling)
    // UP active zone: palmY < 0.40 (offset < -0.10)
    // DOWN active zone: palmY > 0.60 (offset > +0.10)
    // Exit thresholds: UP stops if palmY > 0.45; DOWN stops if palmY < 0.55
    const SCROLL_ENTER = 0.10;
    const SCROLL_EXIT  = 0.05;
    let rawScrollUp = false, rawScrollDown = false;

    if (rockOn) {
      const offset = palmY - 0.5;

      if (this.lastScrollDir === 'UP') {
        if (offset < -SCROLL_EXIT) {
          rawScrollUp = true;
        } else {
          this.lastScrollDir = null;
          this._neutralStartTime = now;
        }
      } else if (this.lastScrollDir === 'DOWN') {
        if (offset > SCROLL_EXIT) {
          rawScrollDown = true;
        } else {
          this.lastScrollDir = null;
          this._neutralStartTime = now;
        }
      } else {
        const neutralDuration = now - (this._neutralStartTime || 0);
        if (offset < -SCROLL_ENTER && neutralDuration > 0.12) {
          rawScrollUp = true;
          this.lastScrollDir = 'UP';
        } else if (offset > SCROLL_ENTER && neutralDuration > 0.12) {
          rawScrollDown = true;
          this.lastScrollDir = 'DOWN';
        }
      }

      this.scrollAmount = 50;
      this.scrollRepeatInterval = 0.04; // 40ms interval for fluid, non-laggy continuous scroll
    } else {
      this.lastScrollDir = null;
    }

    // Brightness rotation (5 fingers open)
    const fiveOpen = idxExt && midExt && rngExt && pnkExt && thumbOpen;
    let rawBrightUp = false, rawBrightDown = false;
    if (fiveOpen) {
      this._rotationGrace = 0;
      const curAngle = Math.atan2(pts[9][1]-pts[0][1], pts[9][0]-pts[0][0]);
      if (this.prevRotationAngle !== null) {
        let dA = curAngle - this.prevRotationAngle;
        while (dA >  Math.PI) dA -= 2*Math.PI;
        while (dA < -Math.PI) dA += 2*Math.PI;
        if (Math.abs(dA) >= 0.02) this.accumulatedRotation += dA;
        const ROT_STEP = 0.08;
        if (Math.abs(this.accumulatedRotation) >= ROT_STEP) {
          const steps = Math.floor(Math.abs(this.accumulatedRotation) / ROT_STEP);
          const propDelta = Math.min(25, Math.max(5, steps * 5));
          if (this.accumulatedRotation > 0) { rawBrightUp = true; this.pendingBrightnessDelta =  propDelta; }
          else                              { rawBrightDown = true; this.pendingBrightnessDelta = -propDelta; }
        }
      }
      this.prevRotationAngle = curAngle;
    } else {
      this._rotationGrace = (this._rotationGrace || 0) + 1;
      if (this._rotationGrace > 5) { this.prevRotationAngle = null; this.accumulatedRotation = 0; }
    }

    const rawVolUp    = thumbOpen && !idxExt && !midExt && !rngExt && !pnkExt && thumbPointingUp;
    const rawVolDown  = thumbOpen && !idxExt && !midExt && !rngExt && !pnkExt && thumbPointingDown;
    const rawClose    = thumbOpen && idxExt && midExt && !rngExt && !pnkExt && (dTi > 0.30);
    const rawScreenshot = thumbOpen && (dTi > 0.32) && idxExt && pnkExt && !midExt && !rngExt;
    const rawMinimize = idxExt && midExt && !rngExt && pnkExt && !thumbOpen;
    const rawMaximize = idxExt && midExt && rngExt  && pnkExt && !thumbOpen;

    // Swipe (index angle)
    const idxDx   = pts[8][0] - pts[5][0];
    const idxDy   = pts[8][1] - pts[5][1];
    const idxAngleDeg = Math.atan2(idxDy, idxDx) * (180 / Math.PI);
    const idxOnly = idxExt && !midExt && !rngExt && !pnkExt && (dTi > 0.32);
    const rawSwipeRight = idxOnly && (idxAngleDeg >= -45 && idxAngleDeg <=  45);
    const rawSwipeLeft  = idxOnly && (idxAngleDeg >= 135 || idxAngleDeg <= -135);

    const rawMute = pnkExt && !idxExt && !midExt && !rngExt && !thumbOpen;

    // 3-finger zoom (Index + Middle + Ring, pinky folded, thumb closed)
    const threeFingerZoom = idxExt && midExt && rngExt && !pnkExt && !thumbOpen;
    let rawZoomIn = false, rawZoomOut = false;
    if (threeFingerZoom) {
      this._zoomGrace = 0;
      if (this.prevZoomScale !== null) {
        const dScale = (this.handScale - this.prevZoomScale) / Math.max(this.prevZoomScale, 1);
        if (Math.abs(dScale) >= 0.015) this.accumulatedZoom += dScale;
        const ZOOM_STEP = 0.05;
        if (Math.abs(this.accumulatedZoom) >= ZOOM_STEP) {
          if (this.accumulatedZoom > 0) rawZoomIn  = true;
          else                          rawZoomOut = true;
        }
      }
      this.prevZoomScale = this.handScale;
    } else {
      this._zoomGrace = (this._zoomGrace || 0) + 1;
      if (this._zoomGrace > 5) { this.prevZoomScale = null; this.accumulatedZoom = 0; }
    }

    // ---- Priority chain — exact order from hand_tracker.py ----
    const [jshot,  ashot]  = this.stabScreenshot.update(rawScreenshot);
    const [jcls,   acls]   = this.stabClose.update(rawClose && !ashot);
    const [jclk,   aclk]   = this.stabClick.update(rawClick && !ashot && !acls);
    const [jrclk,  arclk]  = this.stabRightClick.update(rawRightClick && !ashot && !acls && !aclk);
    const [jbu,    abu]    = this.stabBrightUp.update(rawBrightUp && !ashot && !acls && !aclk && !arclk);
    const [jbd,    abd]    = this.stabBrightDown.update(rawBrightDown && !ashot && !acls && !aclk && !arclk && !abu);
    const [jvu,    avu]    = this.stabVolUp.update(rawVolUp && !ashot && !acls && !aclk && !arclk && !abu && !abd);
    const [jvd,    avd]    = this.stabVolDown.update(rawVolDown && !ashot && !acls && !aclk && !arclk && !abu && !abd && !avu);
    const [jmute,  amute]  = this.stabMute.update(rawMute && !ashot && !acls && !aclk && !arclk && !abu && !abd && !avu && !avd);
    const [jsu,    asu]    = this.stabScrollUp.update(rawScrollUp && !ashot && !acls && !aclk && !arclk && !abu && !abd && !avu && !avd && !amute);
    const [jsd,    asd]    = this.stabScrollDown.update(rawScrollDown && !ashot && !acls && !aclk && !arclk && !abu && !abd && !avu && !avd && !asu && !amute);
    const [jmax,   amax]   = this.stabMaximize.update(rawMaximize && !ashot && !acls && !aclk && !arclk && !abu && !abd && !avu && !avd && !asu && !asd && !amute);
    const [jmin,   amin]   = this.stabMinimize.update(rawMinimize && !ashot && !acls && !aclk && !arclk && !abu && !abd && !avu && !avd && !asu && !asd && !amax && !amute);
    const [jswr,   aswr]   = this.stabSwipeRight.update(rawSwipeRight && !ashot && !acls && !aclk && !arclk && !abu && !abd && !avu && !avd && !asu && !asd && !amax && !amin && !amute);
    const [jswl,   aswl]   = this.stabSwipeLeft.update(rawSwipeLeft && !ashot && !acls && !aclk && !arclk && !abu && !abd && !avu && !avd && !asu && !asd && !amax && !amin && !aswr && !amute);
    const [jpause, apause] = this.stabPauseVideo.update(rightSideFist && !ashot && !acls && !aclk && !arclk && !abu && !abd && !avu && !avd && !asu && !asd && !amax && !amin && !aswr && !aswl && !amute);
    const [jplay,  aplay]  = this.stabPlayVideo.update(leftSideFist && !ashot && !acls && !aclk && !arclk && !abu && !abd && !avu && !avd && !asu && !asd && !amax && !amin && !aswr && !aswl && !apause && !amute);
    const [jzi,    azi]    = this.stabZoomIn.update(rawZoomIn && !ashot && !acls && !aclk && !arclk && !abu && !abd && !avu && !avd && !asu && !asd && !amax && !amin && !aswr && !aswl && !apause && !aplay && !amute);
    const [jzo,    azo]    = this.stabZoomOut.update(rawZoomOut && !ashot && !acls && !aclk && !arclk && !abu && !abd && !avu && !avd && !asu && !asd && !amax && !amin && !aswr && !aswl && !apause && !aplay && !azi && !amute);
    const ahov = rawHover && !(ashot||acls||aclk||arclk||abu||abd||avu||avd||amute||asu||asd||amax||amin||aswr||aswl||apause||aplay||azi||azo);

    // Canvas coordinate mapper (mirrors X_MIN/X_MAX clipping in hand_tracker.py)
    const mapToCanvas = (lmX, lmY) => {
      const ix = Math.max(0, Math.min(1, (lmX - this.X_MIN) / (this.X_MAX - this.X_MIN)));
      const iy = Math.max(0, Math.min(1, (lmY - this.Y_MIN) / (this.Y_MAX - this.Y_MIN)));
      return [ix * W, iy * H];
    };

    // Result object — action flags consumed by index.html
    const result = {
      gesture: 'NONE',
      cursorPos: this.cursorPos,
      // cursorNorm: normalized [0..1] position ready to multiply by window.innerWidth/Height
      cursorNorm: this.cursorNorm,
      // lastClickNorm: the exact normalized position when shouldClick fired — use this for click dispatch
      lastClickNorm: this.lastClickNorm,
      fingerStates: this.fingerStates,
      handScale: this.handScale,
      clickConfidence: this.clickConfidence,
      rawPinchDist: this.rawPinchDist,
      clickState: this.clickStateMachine.currentState,
      // Browser-executable actions
      doClick: false, doRightClick: false,
      doScrollUp: false, doScrollDown: false, scrollAmount: this.scrollAmount,
      doScreenshot: false,
      doNewTab: false, doPrevTab: false,
      doZoomIn: false, doZoomOut: false,
      doPausePlay: false, doMute: false,
      // OS-only (display label only, no browser action possible)
      osAction: null,
    };

    if (ashot) {
      this.currentGesture = 'SCREENSHOT'; this.isPinching = false;
      if (jshot && (now - this.lastScreenshotTime) > this.screenshotCooldown) {
        result.doScreenshot = true;
        this.lastScreenshotTime = now;
      }
    } else if (acls) {
      this.currentGesture = 'CLOSE WINDOW'; this.isPinching = false;
      if (jcls && (now - this.lastCloseTime) > this.closeCooldown) {
        result.osAction = 'CLOSE_WINDOW';
        this.lastCloseTime = now;
      }
    } else if (aclk) {
      this.isPinching = true;
      this._neutralStart = null;
      const [lm8x, lm8y] = this.lmFilterIndex.apply(lms[8].x, lms[8].y);
      const [canvX, canvY] = mapToCanvas(lm8x, lm8y);
      const [sx, sy] = this.posFilter.apply(now, canvX, canvY);
      const rawFx = Math.round(Math.max(0, Math.min(W-1, sx)));
      const rawFy = Math.round(Math.max(0, Math.min(H-1, sy)));
      const stableHover = (now - this.lastStableHoverTime) < 0.5 ? this.lastStableHoverPos : null;
      const sm = this.clickStateMachine.updateState(true, [rawFx, rawFy], handVelocity, pinchStable, now, stableHover, W / 640.0);
      const [tFx, tFy] = sm.outputPos || [rawFx, rawFy];
      if (sm.isClickLocked) {
        this.smoothCursorX = tFx; this.smoothCursorY = tFy;
      } else {
        if (this.smoothCursorX === null) { this.smoothCursorX = tFx; this.smoothCursorY = tFy; }
        const a = ClickConfig.CURSOR_SMOOTH_ALPHA;
        this.smoothCursorX += (tFx - this.smoothCursorX) * a;
        this.smoothCursorY += (tFy - this.smoothCursorY) * a;
      }
      this.cursorPos = [Math.round(this.smoothCursorX), Math.round(this.smoothCursorY)];
      // Compute normalized cursor position [0..1] for accurate viewport mapping in index.html
      this.cursorNorm = [
        Math.max(0, Math.min(1, this.smoothCursorX / W)),
        Math.max(0, Math.min(1, this.smoothCursorY / H)),
      ];
      this.currentGesture = sm.shouldClick ? 'LEFT CLICK' : (sm.isActive ? 'LEFT CLICK' : 'HOVER');
      if (sm.shouldClick) {
        result.doClick = true;
        // Snapshot the normalized click position so index.html dispatches at the exact location
        this.lastClickNorm = [this.cursorNorm[0], this.cursorNorm[1]];
        result.lastClickNorm = this.lastClickNorm;
      }
    } else if (arclk) {
      this.currentGesture = 'RIGHT CLICK'; this.isPinching = false;
      if (jrclk && (now - this.lastRightClickTime) > this.rightClickCooldown) {
        result.doRightClick = true;
        this.lastRightClickTime = now;
      }
    } else if (abu) {
      this.currentGesture = 'BRIGHTNESS UP'; this.isPinching = false;
      if (now - this.lastBrightnessTime > this.brightnessRepeatInterval) {
        result.osAction = 'BRIGHTNESS_UP';
        this.lastBrightnessTime = now; this.accumulatedRotation = 0;
      }
    } else if (abd) {
      this.currentGesture = 'BRIGHTNESS DOWN'; this.isPinching = false;
      if (now - this.lastBrightnessTime > this.brightnessRepeatInterval) {
        result.osAction = 'BRIGHTNESS_DOWN';
        this.lastBrightnessTime = now; this.accumulatedRotation = 0;
      }
    } else if (avu) {
      this.currentGesture = 'VOLUME UP'; this.isPinching = false;
      if (now - this.lastVolumeTime > this.volumeRepeatInterval) {
        result.osAction = 'VOLUME_UP';
        this.lastVolumeTime = now;
      }
    } else if (avd) {
      this.currentGesture = 'VOLUME DOWN'; this.isPinching = false;
      if (now - this.lastVolumeTime > this.volumeRepeatInterval) {
        result.osAction = 'VOLUME_DOWN';
        this.lastVolumeTime = now;
      }
    } else if (amute) {
      this.currentGesture = 'MUTE TOGGLE'; this.isPinching = false;
      if (jmute && (now - this.lastMuteTime) > this.muteCooldown) {
        result.doMute = true;
        this.lastMuteTime = now;
      }
    } else if (asu) {
      this.currentGesture = 'SCROLL UP'; this.isPinching = false;
      if (now - this.lastScrollTime > this.scrollRepeatInterval) {
        result.doScrollUp = true; result.scrollAmount = this.scrollAmount;
        this.lastScrollTime = now;
      }
    } else if (asd) {
      this.currentGesture = 'SCROLL DOWN'; this.isPinching = false;
      if (now - this.lastScrollTime > this.scrollRepeatInterval) {
        result.doScrollDown = true; result.scrollAmount = this.scrollAmount;
        this.lastScrollTime = now;
      }
    } else if (amax) {
      this.currentGesture = 'MAXIMIZE'; this.isPinching = false;
      if (jmax && (now - this.lastMaximizeTime) > this.maximizeCooldown) {
        result.osAction = 'MAXIMIZE';
        this.lastMaximizeTime = now;
      }
    } else if (amin) {
      this.currentGesture = 'MINIMIZE'; this.isPinching = false;
      if (jmin && (now - this.lastMinimizeTime) > this.minimizeCooldown) {
        result.osAction = 'MINIMIZE';
        this.lastMinimizeTime = now;
      }
    } else if (aswr) {
      this.currentGesture = 'NEW TAB'; this.isPinching = false;
      if (jswr && (now - this.lastSwipeTime) > this.swipeCooldown) {
        result.doNewTab = true;
        this.lastSwipeTime = now;
      }
    } else if (aswl) {
      this.currentGesture = 'PREVIOUS TAB'; this.isPinching = false;
      if (jswl && (now - this.lastSwipeTime) > this.swipeCooldown) {
        result.doPrevTab = true;
        this.lastSwipeTime = now;
      }
    } else if (apause) {
      this.currentGesture = 'PAUSE VIDEO'; this.isPinching = false;
      if (jpause && (now - this.lastPauseVideoTime) > this.swipeCooldown) {
        result.doPausePlay = true;
        this.lastPauseVideoTime = now;
      }
    } else if (aplay) {
      this.currentGesture = 'PLAY VIDEO'; this.isPinching = false;
      if (jplay && (now - this.lastPlayVideoTime) > this.swipeCooldown) {
        result.doPausePlay = true;
        this.lastPlayVideoTime = now;
      }
    } else if (azi) {
      this.currentGesture = 'ZOOM IN'; this.isPinching = false;
      if (now - this.lastZoomTime > this.zoomRepeatInterval) {
        result.doZoomIn = true;
        this.lastZoomTime = now; this.accumulatedZoom = 0;
      }
    } else if (azo) {
      this.currentGesture = 'ZOOM OUT'; this.isPinching = false;
      if (now - this.lastZoomTime > this.zoomRepeatInterval) {
        result.doZoomOut = true;
        this.lastZoomTime = now; this.accumulatedZoom = 0;
      }
    } else if (ahov) {
      this.currentGesture = 'HOVER'; this.isPinching = false;
      this.clickStateMachine.reset(); this.dragActive = false;
      const [lm8x, lm8y] = this.lmFilterIndex.apply(lms[8].x, lms[8].y);
      const [canvX, canvY] = mapToCanvas(lm8x, lm8y);
      const [sx, sy] = this.posFilter.apply(now, canvX, canvY);
      const rawFx = Math.max(0, Math.min(W-1, sx));
      const rawFy = Math.max(0, Math.min(H-1, sy));
      if (this.smoothCursorX === null) { this.smoothCursorX = rawFx; this.smoothCursorY = rawFy; }
      // Velocity-adaptive smoothing:
      //   distPx < 4px  → alpha 0.12  (nearly still: heavy smoothing, suppresses tremor)
      //   distPx = 30px → alpha 0.65  (clearly moving: responsive)
      //   Hard deadzone: if cursor hasn't moved >2px from last smooth position, hold it still.
      const distPx = Math.hypot(rawFx - this.smoothCursorX, rawFy - this.smoothCursorY);
      if (distPx > 1.2) {
        const tRamp  = Math.max(0, Math.min(1, (distPx - 1.2) / 18.0));
        const hAlpha = 0.40 + 0.55 * tRamp;
        this.smoothCursorX += (rawFx - this.smoothCursorX) * hAlpha;
        this.smoothCursorY += (rawFy - this.smoothCursorY) * hAlpha;
      }
      this.cursorPos = [Math.round(this.smoothCursorX), Math.round(this.smoothCursorY)];
      // Normalized [0..1] for viewport mapping
      this.cursorNorm = [
        Math.max(0, Math.min(1, this.smoothCursorX / W)),
        Math.max(0, Math.min(1, this.smoothCursorY / H)),
      ];
      this.lastHoverPos = this.cursorPos;
      if (handVelocity < ClickConfig.CLICK_VELOCITY_THRESHOLD * 1.5) {
        this.lastStableHoverPos  = this.cursorPos;
        this.lastStableHoverTime = now;
      }
    } else {
      this.currentGesture = 'NONE'; this.isPinching = false; this.dragActive = false;
      this.clickStateMachine.reset();
      this._neutralStart = this._neutralStart || now;
      if ((now - this._neutralStart) > this._filterResetDelay) {
        this.posFilter.reset(); this.lmFilterIndex.reset();
        this.smoothCursorX = null; this.smoothCursorY = null;
        this._neutralStart = null;
      }
    }

    result.gesture      = this.currentGesture;
    result.cursorPos    = this.cursorPos;
    result.cursorNorm   = this.cursorNorm;
    result.lastClickNorm = this.lastClickNorm;
    result.fingerStates = this.fingerStates;
    result.handScale    = this.handScale;
    result.clickState   = this.clickStateMachine.currentState;
    this._emit(result);
  }

  _emit(result) {
    if (typeof this.onGestureResult === 'function') this.onGestureResult(result);
  }
}
