# -*- coding: utf-8 -*-
"""
Geisha pilot — assembler.

Per-segment A/V sync strategy (same as the reel pipeline): each shot's video
length is derived from its own VO length (LEAD + vo + TAIL), so audio and video
can never drift. Ken Burns runs zoompan on a PRE-SCALED still (raw -loop 1 on
the source PNG is pathologically slow — hit this on the Kannada build).

Run AFTER build_captions.py (needs plan.json + captions.ass).
Outputs: geisha_pilot_1080p.mp4
"""
import json, os, subprocess, sys

ROOT   = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "assets")
WORK   = os.path.join(ROOT, "work")
FFMPEG = r"E:\faceless\kannada_reel\bin\ffmpeg.exe"

spec = json.load(open(os.path.join(ROOT, "spec.json"), encoding="utf-8"))
data = json.load(open(os.path.join(ROOT, "plan.json"), encoding="utf-8"))
plan = data["plan"]
spec_by_id = {s["id"]: s for s in spec["segments"]}
ANIM = os.path.join(ASSETS, "anim")

W, H, FPS = spec["width"], spec["height"], spec["fps"]
LEAD = spec["timing"]["lead"]
PRE_W, PRE_H = W * 4, H * 4          # pre-scale canvas for smooth zoompan
ZOOM = 0.12                          # total travel

# Ken Burns is OFF by default. zoompan recomputes the crop origin each frame and
# TRUNCATES it to whole pixels, so slow moves snap between integer positions and
# read as jitter. Pre-scaling (now 4x) reduces it but never removes it. Stills
# avoid the problem entirely. Set "motion": true in spec.json to re-enable.
MOTION = bool(spec.get("motion", False))

os.makedirs(WORK, exist_ok=True)

def run(args):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        print(p.stdout[-4000:])
        sys.exit("ffmpeg failed: %s" % " ".join(args[:6]))


def kb_expr(mode, n):
    """Linear Ken Burns over exactly n frames, using output-frame index `on`."""
    d = max(1, n - 1)
    ctr_x, ctr_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if mode == "pull_out":
        return ("%f-%f*on/%d" % (1 + ZOOM, ZOOM, d), ctr_x, ctr_y)
    if mode == "pan_left":
        return ("1.10", "(iw-iw/zoom)*(1-on/%d)" % d, ctr_y)
    if mode == "pan_right":
        return ("1.10", "(iw-iw/zoom)*(on/%d)" % d, ctr_y)
    return ("1+%f*on/%d" % (ZOOM, d), ctr_x, ctr_y)   # push_in


def enable_expr(pattern):
    """ffmpeg overlay enable= expression (commas escaped for the filtergraph).
    t is segment-local seconds. Add patterns here to extend the engine."""
    if pattern == "blink":     # brief closed state every ~2.7s
        return r"lt(mod(t+2.2\,2.7)\,0.10)"
    if pattern == "flicker":   # fast gentle pulsing (~6 Hz, on ~half)
        return r"lt(mod(t\,0.16)\,0.08)"
    if pattern == "drift":     # slow on/off breathing for ambient elements
        return r"lt(mod(t\,2.0)\,1.0)"
    return r"lt(mod(t+2.2\,2.7)\,0.10)"


def anim_overlays(seg):
    """Region overlay files that actually exist for this segment, else []."""
    out = []
    stem = os.path.splitext(seg["image"])[0]
    for blk in seg.get("animate", []):
        p = os.path.join(ANIM, "%s__%s_0.png" % (stem, blk["element"]))
        if os.path.exists(p):
            out.append((p, blk["pattern"]))
    return out


# ---- 1) per-segment video ---------------------------------------------------
seg_files = []
for p in plan:
    i   = p["seg"]
    src = os.path.join(ASSETS, p["image"])
    if not os.path.exists(src):
        sys.exit("missing image: %s" % src)

    n = max(2, int(round(p["seg_dur"] * FPS)))
    dur = p["seg_dur"]
    overlays = anim_overlays(spec_by_id.get(i, {}))

    if overlays:
        # content-aware limited animation: base still + region overlays composited
        # with per-pattern timing. Each overlay is transparent except its region.
        scl = "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,fps=%d,setsar=1" % (W, H, W, H, FPS)
        args = [FFMPEG, "-y", "-loglevel", "error", "-loop", "1", "-t", "%.3f" % dur, "-i", src]
        for ov, _ in overlays:
            args += ["-loop", "1", "-t", "%.3f" % dur, "-i", ov]
        fc = ["[0:v]%s[b]" % scl]
        for idx in range(len(overlays)):
            fc.append("[%d:v]%s[r%d]" % (idx + 1, scl, idx))
        prev = "b"
        for idx, (_, pat) in enumerate(overlays):
            lab = "c%d" % idx
            fc.append("[%s][r%d]overlay=0:0:enable=%s[%s]" % (prev, idx, enable_expr(pat), lab))
            prev = lab
        final = prev
        if p.get("title_card"):
            t_in, t_hold = 0.4, dur - 0.8
            fc.append("[%s]drawtext=text='%s':fontfile='C\\:/Windows/Fonts/impact.ttf':"
                      "fontsize=110:fontcolor=white:borderw=8:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2:"
                      "alpha='if(lt(t\\,%f)\\,t/%f\\,if(lt(t\\,%f)\\,1\\,max(0\\,1-(t-%f)/0.4)))'[vout]"
                      % (final, t_in, t_in, t_hold, t_hold))
            final = "vout"
        out = os.path.join(WORK, "seg%02d.mp4" % i)
        run(args + ["-filter_complex", ";".join(fc), "-map", "[%s]" % final,
                    "-frames:v", str(n), "-r", str(FPS), "-c:v", "libx264",
                    "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", out])
        seg_files.append(out)
        print("  video S%-2d %-24s %6.2fs (%d frames, anim:%s)"
              % (i, p["image"], dur, n, "+".join(o[1] for o in overlays)))
        continue

    if MOTION:
        pre = os.path.join(WORK, "pre%d.png" % i)
        run([FFMPEG, "-y", "-loglevel", "error", "-i", src,
             "-vf", "scale=%d:%d:force_original_aspect_ratio=increase,"
                    "crop=%d:%d" % (PRE_W, PRE_H, PRE_W, PRE_H), pre])
        z, x, y = kb_expr(p["kb"], n)
        vf = ("zoompan=z='%s':x='%s':y='%s':d=%d:s=%dx%d:fps=%d" % (z, x, y, n, W, H, FPS))
    else:
        # locked-off still: scale to frame, no per-frame resampling => no jitter
        pre = src
        vf = ("scale=%d:%d:force_original_aspect_ratio=increase,"
              "crop=%d:%d,fps=%d" % (W, H, W, H, FPS))

    # title card burned onto its segment, fading in/out
    if p.get("title_card"):
        t_in, t_hold = 0.4, p["seg_dur"] - 0.8
        vf += (",drawtext=text='%s':fontfile='C\\:/Windows/Fonts/impact.ttf':"
               "fontsize=110:fontcolor=white:borderw=8:bordercolor=black:"
               "x=(w-text_w)/2:y=(h-text_h)/2:"
               "alpha='if(lt(t,%f),t/%f,if(lt(t,%f),1,max(0,1-(t-%f)/0.4)))'"
               % (p["title_card"], t_in, t_in, t_hold, t_hold))

    out = os.path.join(WORK, "seg%02d.mp4" % i)
    run([FFMPEG, "-y", "-loglevel", "error", "-loop", "1", "-i", pre,
         "-vf", vf, "-frames:v", str(n), "-r", str(FPS),
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", out])
    seg_files.append(out)
    print("  video S%-2d %-24s %6.2fs (%d frames, %s)"
          % (i, p["image"], p["seg_dur"], n, p["kb"] if MOTION else "still"))


# ---- 2) per-segment audio padded to exact seg_dur ---------------------------
aud_files = []
for p in plan:
    i = p["seg"]
    # prefer the tempo-adjusted take build_captions.py made (spec.timing.speed)
    sped = os.path.join(WORK, "v%d_s.wav" % i)
    src = sped if os.path.exists(sped) else os.path.join(ASSETS, "v%d.wav" % i)
    out = os.path.join(WORK, "a%02d.wav" % i)
    ms = int(round(LEAD * 1000))
    run([FFMPEG, "-y", "-loglevel", "error", "-i", src,
         "-af", "adelay=%d|%d,apad,aresample=48000" % (ms, ms),
         "-t", "%.3f" % p["seg_dur"], "-ar", "48000", "-ac", "2", out])
    aud_files.append(out)


# ---- 3) concat ---------------------------------------------------------------
def concat(files, out, extra):
    lst = out + ".txt"
    with open(lst, "w", encoding="utf-8") as f:
        for p in files:
            f.write("file '%s'\n" % p.replace("\\", "/"))
    run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", lst] + extra + [out])

vcat = os.path.join(WORK, "video_all.mp4")
acat = os.path.join(WORK, "audio_all.wav")
concat(seg_files, vcat, ["-c", "copy"])
concat(aud_files, acat, ["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"])


# ---- 4) burn captions + mux (optional music bed) -----------------------------
music = os.path.join(ASSETS, "music.mp3")
final = os.path.join(ROOT, "geisha_pilot_1080p.mp4")

# run from ROOT so the subtitles filter takes a bare relative filename
# (avoids Windows drive-letter escaping inside filtergraphs)
args = [FFMPEG, "-y", "-loglevel", "error", "-i", vcat, "-i", acat]
if os.path.exists(music):
    args += ["-stream_loop", "-1", "-i", music,
             "-filter_complex",
             "[2:a]volume=0.10,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[m];"
             "[1:a][m]amix=inputs=2:duration=first:dropout_transition=0[aout]",
             "-map", "0:v", "-map", "[aout]"]
else:
    args += ["-map", "0:v", "-map", "1:a"]
args += ["-vf", "subtitles=captions.ass",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-shortest", final]
p = subprocess.run(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
if p.returncode != 0:
    print(p.stdout[-4000:]); sys.exit("final mux failed")

print("\nDONE -> %s  (%.2fs)" % (final, data["total"]))
