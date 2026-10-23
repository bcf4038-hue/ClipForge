"""Find where the speaker's face is so the 9:16 crop can follow it."""
import cv2

OUT_W, OUT_H = 1080, 1920


def scale_info(src_w, src_h):
    """Scale factor and scaled width used by 'scale ... increase' before cropping."""
    s = max(OUT_W / src_w, OUT_H / src_h)
    return s, src_w * s


def face_centers(path, every=0.25):
    """Sample the video and return [(time, face_center_x or None)] in source pixels."""
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    src_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    step = max(1, int(round(fps * every)))
    samples, i = [], 0
    while True:
        if not cap.grab():
            break
        if i % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            ratio = 480 / frame.shape[0]
            small = cv2.resize(frame, None, fx=ratio, fy=ratio)
            gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6,
                                             minSize=(int(480 * 0.09),) * 2)
            if len(faces):
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                samples.append((i / fps, (x + w / 2) / ratio))
            else:
                samples.append((i / fps, None))
        i += 1
    cap.release()
    return samples, src_w


def crop_segments(samples, src_w, hold=1.0, jump=0.08):
    """Turn noisy face positions into steady camera positions.

    The crop only moves when the face stays somewhere new for `hold` seconds,
    which looks like a deliberate camera cut instead of jitter.
    """
    known = [c for _, c in samples if c is not None]
    if not known:
        return [(0.0, src_w / 2)]
    filled, last = [], known[0]
    for t, c in samples:
        last = c if c is not None else last
        filled.append((t, last))
    # Median filter to drop one-off false detections.
    smooth = []
    for k in range(len(filled)):
        window = sorted(c for _, c in filled[max(0, k - 3):k + 4])
        smooth.append((filled[k][0], window[len(window) // 2]))

    segments = [(0.0, smooth[0][1])]
    pending_since = None
    for t, c in smooth:
        cur = segments[-1][1]
        if abs(c - cur) > src_w * jump:
            if pending_since is None:
                pending_since = t
            elif t - pending_since >= hold:
                segments.append((pending_since, c))
                pending_since = None
        else:
            pending_since = None
    return segments


def crop_x_expr(segments, src_w, src_h):
    """FFmpeg expression for the crop's x offset, switching at each segment time."""
    s, scaled_w = scale_info(src_w, src_h)
    max_x = max(0.0, scaled_w - OUT_W)

    def x_for(cx):
        return int(min(max(cx * s - OUT_W / 2, 0), max_x))

    expr = str(x_for(segments[-1][1]))
    for k in range(len(segments) - 2, -1, -1):
        switch_at = segments[k + 1][0]
        expr = f"if(lt(t,{switch_at:.2f}),{x_for(segments[k][1])},{expr})"
    return expr
