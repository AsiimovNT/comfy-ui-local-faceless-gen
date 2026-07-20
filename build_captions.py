# -*- coding: utf-8 -*-
"""
Geisha pilot — karaoke caption builder (English, 16:9 longform).

Differs from kannada_reel/build_captions.py in one important way: instead of
*estimating* word timings by character weight, this runs faster-whisper with
word_timestamps and ALIGNS those timings onto the known script text. Whisper
supplies the timing; spec.json supplies the spelling. That keeps A/V sync tight
while still rendering "okiya" / "Gion" / "shikomi" correctly (whisper mangles
proper nouns — the same reason the Kannada build used known-text captions).

Inputs :  spec.json, assets/v{id}.wav
Outputs:  plan.json (segment + word timing), captions.ass
"""
import json, os, re, subprocess, sys, difflib

ROOT    = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
ASSETS  = os.path.join(ROOT, "assets")
WORK    = os.path.join(ROOT, "work")
FFPROBE = r"E:\faceless\kannada_reel\bin\ffprobe.exe"
FFMPEG  = r"E:\faceless\kannada_reel\bin\ffmpeg.exe"

spec  = json.load(open(os.path.join(ROOT, "spec.json"), encoding="utf-8"))
segs  = spec["segments"]
LEAD  = spec["timing"]["lead"]
TAIL  = spec["timing"]["tail"]
CS    = spec["caption_style"]
WPL   = CS["words_per_line"]

# Pacing dial. 1.0 = untouched. Raise for more urgency (1.05-1.15 is the usable
# band; past ~1.2 it starts sounding chipmunky). atempo preserves pitch, so this
# adds pace without raising the voice. Applied BEFORE whisper so caption timings
# are measured against the audio that actually ships.
SPEED = float(spec["timing"].get("speed", 1.0))

os.makedirs(WORK, exist_ok=True)


def probe(path):
    out = subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path], text=True).strip()
    return float(out)


STRIP = " \t\r\n,.;:!?—–-\"'()[]“”‘’"
def tokenize(s):
    return [t.strip(STRIP) for t in s.split() if t.strip(STRIP)]

def norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


# ---- 1) whisper word timings ------------------------------------------------
def whisper_words(wav):
    """Return [(start, end, text), ...] using faster-whisper word timestamps."""
    from faster_whisper import WhisperModel
    global _MODEL
    try:
        _MODEL
    except NameError:
        # base is plenty for timing; int8 on CPU is fast for short VO takes
        _MODEL = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _ = _MODEL.transcribe(wav, language="en", word_timestamps=True)
    out = []
    for seg in segments:
        for w in (seg.words or []):
            if norm(w.word):
                out.append((float(w.start), float(w.end), w.word.strip()))
    return out


def align(script_toks, wwords, dur):
    """Map whisper timings onto script tokens. Returns [(start, end), ...]
    aligned 1:1 with script_toks. Unmatched script tokens (mangled proper
    nouns) are interpolated across the surrounding known timings."""
    n = len(script_toks)
    times = [None] * n

    if wwords:
        a = [norm(w[2]) for w in wwords]
        b = [norm(t) for t in script_toks]
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    times[j1 + k] = (wwords[i1 + k][0], wwords[i1 + k][1])

    # fill gaps by interpolating, weighted by token length
    known = [i for i, t in enumerate(times) if t is not None]
    if not known:
        # whisper gave us nothing usable -> pure proportional fallback
        weights = [max(1, len(t)) for t in script_toks]
        total_w = sum(weights)
        t0, t1 = 0.05, max(0.6, dur - 0.12)
        acc = 0.0
        for i, w in enumerate(weights):
            s = t0 + (acc / total_w) * (t1 - t0); acc += w
            e = t0 + (acc / total_w) * (t1 - t0)
            times[i] = (s, e)
        return times

    # leading gap
    first = known[0]
    if first > 0:
        span_s, span_e = 0.0, times[first][0]
        weights = [max(1, len(script_toks[i])) for i in range(first)]
        tw = sum(weights); acc = 0.0
        for i in range(first):
            s = span_s + (acc / tw) * (span_e - span_s); acc += weights[i]
            e = span_s + (acc / tw) * (span_e - span_s)
            times[i] = (s, e)

    # interior gaps
    for idx in range(len(known) - 1):
        i0, i1 = known[idx], known[idx + 1]
        if i1 - i0 <= 1:
            continue
        span_s, span_e = times[i0][1], times[i1][0]
        if span_e <= span_s:
            span_e = span_s + 0.01 * (i1 - i0)
        gap = list(range(i0 + 1, i1))
        weights = [max(1, len(script_toks[i])) for i in gap]
        tw = sum(weights); acc = 0.0
        for i, w in zip(gap, weights):
            s = span_s + (acc / tw) * (span_e - span_s); acc += w
            e = span_s + (acc / tw) * (span_e - span_s)
            times[i] = (s, e)

    # trailing gap
    last = known[-1]
    if last < n - 1:
        span_s, span_e = times[last][1], max(times[last][1] + 0.3, dur - 0.10)
        gap = list(range(last + 1, n))
        weights = [max(1, len(script_toks[i])) for i in gap]
        tw = sum(weights); acc = 0.0
        for i, w in zip(gap, weights):
            s = span_s + (acc / tw) * (span_e - span_s); acc += w
            e = span_s + (acc / tw) * (span_e - span_s)
            times[i] = (s, e)

    return times


# ---- 2) build plan + global word events -------------------------------------
plan, events = [], []
start = 0.0
for s in segs:
    i   = s["id"]
    wav = os.path.join(ASSETS, "v%d.wav" % i)
    if not os.path.exists(wav):
        sys.exit("missing VO: %s" % wav)
    if abs(SPEED - 1.0) > 1e-3:
        sped = os.path.join(WORK, "v%d_s.wav" % i)
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", wav,
                        "-filter:a", "atempo=%.4f,aresample=48000" % SPEED,
                        "-ar", "48000", "-ac", "2", sped], check=True)
        wav = sped                      # assemble.py picks this up too
    dur = probe(wav)
    seg_dur = round(LEAD + dur + TAIL, 3)

    toks  = tokenize(s["vo"])
    times = align(toks, whisper_words(wav), dur)

    gbase = start + LEAD
    chunks = [list(range(j, min(j + WPL, len(toks)))) for j in range(0, len(toks), WPL)]
    for ch in chunks:
        chunk_words = [toks[k] for k in ch]
        for pos, k in enumerate(ch):
            ws = gbase + times[k][0]
            # hold the highlight until the next word actually starts
            we = gbase + (times[k + 1][0] if k + 1 < len(toks) else times[k][1])
            if we <= ws:
                we = ws + 0.08
            events.append([round(ws, 3), round(we, 3), chunk_words, pos])

    plan.append({"seg": i, "image": s["image"], "kb": s.get("kb", "push_in"),
                 "title_card": s.get("title_card"), "seg_dur": seg_dur,
                 "start": round(start, 3), "vo_start": round(start + LEAD, 3),
                 "vo_dur": round(dur, 3)})
    start = round(start + seg_dur, 3)

total = round(start, 3)
json.dump({"plan": plan, "total": total, "events": events},
          open(os.path.join(ROOT, "plan.json"), "w"), indent=1)


# ---- 3) ASS -----------------------------------------------------------------
def cs_time(t):
    if t < 0:
        t = 0
    h = int(t // 3600); t -= h * 3600
    m = int(t // 60);   t -= m * 60
    sec = int(t); c = int(round((t - sec) * 100))
    if c == 100:
        sec += 1; c = 0
    return "%d:%02d:%02d.%02d" % (h, m, sec, c)


HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: %d
PlayResY: %d
WrapStyle: 1
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Kar,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,1.0,0,1,%d,2,2,120,120,%d,1
""" % (spec["width"], spec["height"], CS["font"], CS["size"],
       CS["outline_px"], CS["margin_v"])

ACT_ON  = r"{\1c%s\3c&H101010&\bord9}" % CS["active_colour_bgr"]
ACT_OFF = r"{\r}"

lines = [HEAD, "[Events]",
         "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
for ws, we, chunk, pos in events:
    parts = [(ACT_ON + w + ACT_OFF) if idx == pos else w
             for idx, w in enumerate(chunk)]
    lines.append("Dialogue: 0,%s,%s,Kar,,0,0,0,,%s"
                 % (cs_time(ws), cs_time(we), " ".join(parts)))

open(os.path.join(ROOT, "captions.ass"), "w", encoding="utf-8").write("\n".join(lines))

print("TOTAL=%.2fs  segments=%d  caption events=%d" % (total, len(plan), len(events)))
for p in plan:
    print("  S%-2d %-24s seg=%6.2fs vo=%6.2fs start=%7.2f"
          % (p["seg"], p["image"], p["seg_dur"], p["vo_dur"], p["start"]))
