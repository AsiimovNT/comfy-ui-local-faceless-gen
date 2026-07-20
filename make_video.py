# -*- coding: utf-8 -*-
"""
make_video.py -- one-command orchestrator for the whole pipeline.

    python make_video.py [project_dir] [--force-images]

Runs, in order, skipping any step whose outputs already exist:
  1. images   -> gen_images.py         (local ComfyUI; needs the server up)
  2. voice    -> gen_voice.py IF present, else emits vo_manifest.json + stops
  3. captions -> build_captions.py      (faster-whisper word alignment)
  4. assemble -> assemble.py            (ffmpeg: stills + captions + music)

The VOICE step is the one pluggable seam. Two ways to satisfy it:
  * Drop a gen_voice.py beside this file (e.g. direct ElevenLabs API) and it
    runs unattended -> fully automatic, one command, finished video.
  * Leave it out: the orchestrator writes vo_manifest.json listing exactly which
    shots need audio + their text, and stops. Generate those v{id}.wav (e.g. the
    agent via the Higgsfield MCP), then re-run -- it resumes at captions.
"""
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:]]
if args and not args[0].startswith("--"):
    ROOT = os.path.abspath(args.pop(0))
FORCE_IMAGES = "--force-images" in args

PY = sys.executable
spec = json.load(open(os.path.join(ROOT, "spec.json"), encoding="utf-8"))
segs = spec["segments"]
ASSETS = os.path.join(ROOT, "assets")


def step(title):
    print("\n" + "=" * 62 + "\n== %s\n" % title + "=" * 62)

def run(script):
    r = subprocess.run([PY, os.path.join(ROOT, script), ROOT])
    if r.returncode != 0:
        sys.exit("!! %s failed (exit %d)" % (script, r.returncode))


# ---- 1. IMAGES --------------------------------------------------------------
step("1/4  IMAGES  (local ComfyUI)")
missing_img = [s["image"] for s in segs if not os.path.exists(os.path.join(ASSETS, s["image"]))]
if FORCE_IMAGES or missing_img:
    print("generating %d frames..." % (len(segs) if FORCE_IMAGES else len(missing_img)))
    run("gen_images.py")
else:
    print("all %d frames present -- skip (use --force-images to regenerate)" % len(segs))


# ---- 2. VOICE ---------------------------------------------------------------
step("2/4  VOICE")
def missing_vo():
    return [s for s in segs if not os.path.exists(os.path.join(ASSETS, "v%d.wav" % s["id"]))]

need = missing_vo()
if need and os.path.exists(os.path.join(ROOT, "gen_voice.py")):
    print("generating %d VO takes via gen_voice.py..." % len(need))
    run("gen_voice.py")
    need = missing_vo()

if need:
    manifest = {"voice": spec["voice"],
                "todo": [{"id": s["id"], "wav": "assets/v%d.wav" % s["id"],
                          "text": s.get("tts", s["vo"])} for s in need]}
    mp = os.path.join(ROOT, "vo_manifest.json")
    json.dump(manifest, open(mp, "w", encoding="utf-8"), indent=1)
    print("\n%d shots still need voiceover. Wrote %s" % (len(need), mp))
    print("Generate those v{id}.wav (agent via Higgsfield MCP, or add gen_voice.py),")
    print("then re-run: python make_video.py")
    sys.exit(2)
print("all %d VO takes present." % len(segs))


# ---- 3. CAPTIONS ------------------------------------------------------------
step("3/4  CAPTIONS  (whisper word-align)")
run("build_captions.py")


# ---- 4. ASSEMBLE ------------------------------------------------------------
step("4/4  ASSEMBLE  (ffmpeg)")
run("assemble.py")

out = os.path.join(ROOT, "%s_1080p.mp4" % spec["project"])
print("\n" + "=" * 62)
print("DONE -> %s" % (out if os.path.exists(out) else "(see assemble output)"))
