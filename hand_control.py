"""
Hand Gesture PC Control (Tony Stark style)
------------------------------------------
Uses only a webcam. Tracks your PALM (not fingertip) for a steady cursor.

Gestures
  - Move hand               -> move cursor (palm center)
  - Pinch thumb + index     -> left button DOWN (hold to drag); quick pinch = click
  - Pinch thumb + middle    -> right click
  - Pinch thumb + ring      -> DOUBLE click (open file / folder)
  - Peace sign (index+middle up, ring+pinky curled)
                            -> SCROLL MODE. Cursor freezes. Move your hand
                               up/down from where you started: further = faster.
                               Hand above start = scroll up, below = scroll down.
                               Return to the start position to stop.

Keys (in the preview window)
  - q : quit
  - p : pause / resume control

Safety: slam the mouse into the TOP-LEFT screen corner to trigger PyAutoGUI's
failsafe (the script then exits cleanly). The hand-controlled cursor never goes
that far into the corner, so it can't trigger it by accident.

Setup
  python -m venv venv
  venv\\Scripts\\activate          (Windows)   |   source venv/bin/activate (Mac/Linux)
  pip install opencv-python mediapipe pyautogui
  python hand_control.py
"""

import math
import platform
import threading
import time

import cv2
import mediapipe as mp
import pyautogui

# ---------------- Settings (tweak these) ----------------
CAM_INDEX = 0
FRAME_W, FRAME_H = 640, 480
CAM_FPS = 30
MODEL_COMPLEXITY = 1        # 0 = faster / less accurate, 1 = more accurate

# Fraction of the camera frame ignored on each edge. Larger margin means
# you reach screen corners without stretching your arm.
MARGIN_X = 0.18
MARGIN_Y = 0.18

# Cursor smoothing (One Euro filter): steady when slow, responsive when fast.
CURSOR_MIN_CUTOFF = 1.2     # lower = steadier when hovering (but more lag at slow speed)
CURSOR_BETA = 0.012         # higher = less lag during fast moves (but more jitter)

# Pinch detection (distances are relative to palm size)
PINCH_ON = 0.25             # pinch closes below this
PINCH_OFF = 0.40            # pinch releases above this (hysteresis stops flicker)
PINCH_MARGIN = 0.12         # pinching finger must beat the next-closest by this much
PINCH_CONFIRM = 2           # frames a pinch must be seen before it counts
PINCH_SMOOTH = 0.6          # 0-1 weight on the newest measurement (lower = smoother)
CLICK_COOLDOWN = 0.6        # seconds between right/double clicks
DRAG_START_PX = 25          # hand must move this far (screen px) before a held pinch starts dragging
HAND_LOST_GRACE = 6         # frames of lost tracking tolerated before releasing everything

# Scroll
SCROLL_CONFIRM_FRAMES = 5   # pose must be held this many frames; start point is averaged over them
SCROLL_GRACE_FRAMES = 6     # keep scroll mode alive through brief detection dropouts
SCROLL_FILTER = 0.35        # 0-1 smoothing of hand height while scrolling. Lower = steadier
SCROLL_DEADBAND = 0.30      # no scrolling within this distance of the start point (in palm sizes)
SCROLL_FULL_SPEED_AT = 1.5  # distance beyond deadband (palm sizes) that reaches max speed
SCROLL_MAX_SPEED = 25.0     # max speed, in mouse-wheel notches per second
SCROLL_CURVE = 2.0          # 1 = linear. 2+ = very fine control near center, fast at the edges
SCROLL_UNIT = 120 if platform.system() == "Windows" else 1      # pyautogui units per notch
SCROLL_MIN_STEP = 15 if platform.system() == "Windows" else 1   # smallest wheel event sent
FINGER_EXTENDED_RATIO = 1.15  # tip-to-wrist vs knuckle-to-wrist distance for "finger is up"
# ---------------------------------------------------------

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0

mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils

# Palm landmarks: wrist + base knuckle of each finger. These barely move
# when you pinch, which is why the cursor stays stable.
PALM_IDS = (0, 5, 9, 13, 17)
# Fingertips that can pinch with the thumb (landmark 4)
PINCH_TIPS = {"index": 8, "middle": 12, "ring": 16}


# ---------------- Helpers ----------------
def dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def palm_center(lm):
    xs = sum(lm[i].x for i in PALM_IDS) / len(PALM_IDS)
    ys = sum(lm[i].y for i in PALM_IDS) / len(PALM_IDS)
    return xs, ys


def map_range(v, lo, hi, out_max):
    v = (v - lo) / (hi - lo)
    return max(0.0, min(1.0, v)) * out_max


def ema(old, new, weight_new):
    return old + (new - old) * weight_new


def finger_extended(lm, tip, pip):
    """A finger is 'up' if its tip is clearly farther from the wrist than its
    middle joint. Works at any hand rotation."""
    return dist(lm[tip], lm[0]) > dist(lm[pip], lm[0]) * FINGER_EXTENDED_RATIO


def pinch_candidate(ratios):
    """Which finger is pinching the thumb? Only one counts, and it must be
    clearly closer than the others (stops index/middle confusion)."""
    (name, best), (_, second) = sorted(ratios.items(), key=lambda kv: kv[1])[:2]
    if best < PINCH_ON and second - best > PINCH_MARGIN:
        return name
    return None


class OneEuro:
    """One Euro filter: heavy smoothing when the signal moves slowly (kills
    jitter), light smoothing when it moves fast (kills lag)."""

    def __init__(self, min_cutoff, beta, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.reset()

    def reset(self, x=None):
        self.x_prev = x
        self.dx_prev = 0.0
        self.t_prev = None

    @staticmethod
    def _alpha(cutoff, dt):
        r = 2.0 * math.pi * cutoff * dt
        return r / (r + 1.0)

    def __call__(self, x, t):
        dt = (t - self.t_prev) if self.t_prev is not None else 1.0 / 30.0
        dt = min(max(dt, 1e-3), 0.2)
        self.t_prev = t
        if self.x_prev is None:
            self.x_prev = x
            return x
        dx = (x - self.x_prev) / dt
        dx_hat = self.dx_prev + self._alpha(self.d_cutoff, dt) * (dx - self.dx_prev)
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        x_hat = self.x_prev + self._alpha(cutoff, dt) * (x - self.x_prev)
        self.x_prev, self.dx_prev = x_hat, dx_hat
        return x_hat


class Camera:
    """Reads frames on a background thread so the main loop always gets the
    newest frame instead of a stale buffered one (lower latency)."""

    def __init__(self, index, width, height, fps):
        backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(index, backend)
        if not self.cap.isOpened():
            raise SystemExit("Could not open webcam. Try a different CAM_INDEX.")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.running = True
        self._frame = None
        self._lock = threading.Lock()
        self._new = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                self.running = False
                break
            with self._lock:
                self._frame = frame
            self._new.set()

    def read(self, timeout=1.0):
        """Newest frame, or None on timeout / camera failure."""
        if not self._new.wait(timeout):
            return None
        with self._lock:
            frame, self._frame = self._frame, None
            self._new.clear()
        return frame

    def release(self):
        self.running = False
        self._thread.join(timeout=1.0)
        self.cap.release()


# ---------------- Main ----------------
def main():
    screen_w, screen_h = pyautogui.size()
    cam = Camera(CAM_INDEX, FRAME_W, FRAME_H, CAM_FPS)

    hands = mp_hands.Hands(
        max_num_hands=1,
        model_complexity=MODEL_COMPLEXITY,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.7,
    )

    fx = OneEuro(CURSOR_MIN_CUTOFF, CURSOR_BETA)
    fy = OneEuro(CURSOR_MIN_CUTOFF, CURSOR_BETA)
    cur_x, cur_y = (float(v) for v in pyautogui.position())
    resync = True               # reset the cursor filter to the real cursor position

    paused = False
    lost_frames = 0
    fps, last_t = 30.0, time.perf_counter()

    # Pinch state
    palm_size = None
    ratios = {name: 1.0 for name in PINCH_TIPS}
    prev_cand, cand_count = None, 0
    armed = {"middle": True, "ring": True}
    last_click = -1e9
    event_text, event_until = "", 0.0

    # Drag state
    dragging = False
    drag_moving = False
    drag_hx = drag_hy = 0.0     # hand target (screen px) when the button went down

    # Scroll state
    scroll_frames = 0
    scroll_miss = 0
    scroll_anchor_y = 0.0
    scroll_anchor_palm = 1.0
    scroll_filt_y = 0.0
    scroll_samples = []
    scroll_accum = 0.0
    last_scroll_t = time.perf_counter()

    def release_button():
        nonlocal dragging, drag_moving
        if dragging:
            pyautogui.mouseUp()
            dragging = False
            drag_moving = False

    try:
        while True:
            frame = cam.read()
            if frame is None:
                if not cam.running:
                    break
                continue

            t = time.perf_counter()
            fps = ema(fps, 1.0 / max(t - last_t, 1e-3), 0.1)
            last_t = t

            frame = cv2.flip(frame, 1)  # mirror so it feels natural
            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False  # lets MediaPipe skip a copy
            result = hands.process(rgb)

            # Active-area box (preview only)
            x0, x1 = int(MARGIN_X * w), int((1 - MARGIN_X) * w)
            y0, y1 = int(MARGIN_Y * h), int((1 - MARGIN_Y) * h)
            cv2.rectangle(frame, (x0, y0), (x1, y1), (80, 80, 80), 1)

            status = "PAUSED" if paused else "READY"
            locked = False

            if result.multi_hand_landmarks:
                lost_frames = 0
                hand = result.multi_hand_landmarks[0]
                lm = hand.landmark
                mp_draw.draw_landmarks(frame, hand, mp_hands.HAND_CONNECTIONS)

                px, py = palm_center(lm)

                # --- Measurements, normalized by a smoothed palm size ---
                raw_size = 0.5 * (dist(lm[0], lm[9]) + dist(lm[5], lm[17])) or 1e-6
                palm_size = raw_size if palm_size is None else ema(palm_size, raw_size, 0.3)
                for name, tip in PINCH_TIPS.items():
                    r = dist(lm[4], lm[tip]) / palm_size
                    ratios[name] = ema(ratios[name], r, PINCH_SMOOTH)

                # Which finger is pinching, and for how many frames in a row
                cand = pinch_candidate(ratios)
                if cand is not None and cand == prev_cand:
                    cand_count += 1
                else:
                    cand_count = 1 if cand else 0
                prev_cand = cand

                # --- Scroll pose: index + middle up, ring + pinky curled ---
                raw_pose = (
                    finger_extended(lm, 8, 6)
                    and finger_extended(lm, 12, 10)
                    and not finger_extended(lm, 16, 14)
                    and not finger_extended(lm, 20, 18)
                    and ratios["ring"] > PINCH_OFF
                )
                if raw_pose:
                    scroll_miss = 0
                    scroll_frames += 1
                    if scroll_frames == 1:
                        scroll_samples = []
                        scroll_filt_y = py
                        scroll_accum = 0.0
                        last_scroll_t = t
                    scroll_filt_y = ema(scroll_filt_y, py, SCROLL_FILTER)
                    if scroll_frames <= SCROLL_CONFIRM_FRAMES:
                        scroll_samples.append(scroll_filt_y)
                        if scroll_frames == SCROLL_CONFIRM_FRAMES:
                            # Anchor = average over the confirm window (less noisy)
                            scroll_anchor_y = sum(scroll_samples) / len(scroll_samples)
                            scroll_anchor_palm = palm_size
                elif scroll_frames >= SCROLL_CONFIRM_FRAMES and scroll_miss < SCROLL_GRACE_FRAMES:
                    scroll_miss += 1   # brief dropout: hold scroll mode, send nothing
                else:
                    scroll_frames = 0
                    scroll_miss = 0
                scroll_pose = scroll_frames > 0
                scrolling = scroll_frames >= SCROLL_CONFIRM_FRAMES

                if paused:
                    resync = True

                elif scroll_pose:
                    # ===== SCROLL MODE: cursor frozen, no buttons =====
                    release_button()
                    resync = True
                    dt = min(t - last_scroll_t, 0.1)  # frame-rate independent
                    last_scroll_t = t

                    if scrolling:
                        speed = 0.0
                        if raw_pose:
                            # Distance from start, in palm sizes (up = negative)
                            offset = (scroll_filt_y - scroll_anchor_y) / scroll_anchor_palm
                            beyond = abs(offset) - SCROLL_DEADBAND
                            if beyond > 0:
                                s = min(1.0, beyond / SCROLL_FULL_SPEED_AT)
                                speed = SCROLL_MAX_SPEED * (s ** SCROLL_CURVE)
                                direction = 1 if offset < 0 else -1  # hand up -> scroll up
                                scroll_accum += direction * speed * dt * SCROLL_UNIT
                            else:
                                scroll_accum = 0.0

                            # Send whole wheel steps; carry the remainder forward
                            if abs(scroll_accum) >= SCROLL_MIN_STEP:
                                step = int(scroll_accum)
                                pyautogui.scroll(step)
                                scroll_accum -= step
                        status = f"SCROLL {speed:4.1f}/s" if speed else "SCROLL (hold)"

                        # Preview: start line + dead band
                        ay = int(scroll_anchor_y * h)
                        band = int(SCROLL_DEADBAND * scroll_anchor_palm * h)
                        cv2.line(frame, (0, ay), (w, ay), (255, 0, 255), 1)
                        cv2.rectangle(frame, (0, ay - band), (w, ay + band), (120, 0, 120), 1)
                        cv2.circle(frame, (int(px * w), int(scroll_filt_y * h)),
                                   6, (255, 0, 255), -1)
                    else:
                        status = "SCROLL..."

                else:
                    # ===== NORMAL MODE =====
                    # --- Left button: confirmed index pinch = down, open = up ---
                    tx = map_range(px, MARGIN_X, 1 - MARGIN_X, screen_w - 1)
                    ty = map_range(py, MARGIN_Y, 1 - MARGIN_Y, screen_h - 1)

                    if not dragging:
                        if cand == "index" and cand_count >= PINCH_CONFIRM:
                            pyautogui.mouseDown()   # at the (locked) cursor position
                            dragging, drag_moving = True, False
                            drag_hx, drag_hy = tx, ty
                    elif ratios["index"] > PINCH_OFF:
                        release_button()

                    # --- Right click / double click: once per pinch ---
                    for name in armed:
                        if ratios[name] > PINCH_OFF:
                            armed[name] = True
                    if (not dragging and cand in armed and cand_count >= PINCH_CONFIRM
                            and armed[cand] and t - last_click > CLICK_COOLDOWN):
                        if cand == "middle":
                            pyautogui.rightClick()
                            event_text = "RIGHT CLICK"
                        else:
                            pyautogui.doubleClick()
                            event_text = "OPEN"
                        armed[cand] = False
                        last_click = t
                        event_until = t + 0.6

                    # --- Cursor ---
                    # Click lock: freeze the cursor while a pinch is forming/held so
                    # the click lands exactly where you aimed. A held index pinch
                    # unlocks (starts dragging) once the hand moves DRAG_START_PX.
                    if dragging and not drag_moving:
                        if math.hypot(tx - drag_hx, ty - drag_hy) > DRAG_START_PX:
                            drag_moving = True
                    if dragging:
                        locked = not drag_moving
                    else:
                        locked = min(ratios.values()) < PINCH_OFF

                    if locked:
                        resync = True   # filter will restart from the frozen cursor
                    else:
                        if resync:
                            fx.reset(cur_x)
                            fy.reset(cur_y)
                            resync = False
                        # Keep a margin from the corner so the hand can never trip the failsafe
                        cur_x = max(2.0, min(screen_w - 3.0, fx(tx, t)))
                        cur_y = max(2.0, min(screen_h - 3.0, fy(ty, t)))
                        pyautogui.moveTo(int(round(cur_x)), int(round(cur_y)), _pause=False)

                    if t < event_until:
                        status = event_text
                    elif dragging:
                        status = "DRAGGING" if drag_moving else "PINCH (locked)"
                    else:
                        status = "TRACKING"

                # Mark the palm point being tracked (red = cursor locked)
                color = (0, 0, 255) if locked else (0, 255, 0)
                cv2.circle(frame, (int(px * w), int(py * h)), 8, color, -1)

            else:
                # Hand lost: tolerate short dropouts, then release everything
                lost_frames += 1
                if lost_frames > HAND_LOST_GRACE:
                    release_button()
                    scroll_frames = scroll_miss = 0
                    palm_size = None
                    ratios = {name: 1.0 for name in PINCH_TIPS}
                    prev_cand, cand_count = None, 0
                    resync = True
                status += " (no hand)"

            cv2.putText(frame, status, (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (0, 255, 255), 2)
            cv2.putText(frame, f"{fps:.0f} fps", (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (200, 200, 200), 1)
            cv2.imshow("Hand Control  [q quit | p pause]", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("p"):
                paused = not paused
                release_button()
                cur_x, cur_y = (float(v) for v in pyautogui.position())
                resync = True
    except pyautogui.FailSafeException:
        print("PyAutoGUI failsafe triggered (mouse in top-left corner). Exiting.")
    finally:
        try:
            release_button()
        except pyautogui.FailSafeException:
            pass
        cam.release()
        hands.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()