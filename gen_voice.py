# -*- coding: utf-8 -*-
"""
gen_voice.py -- unattended VO via the DIRECT ElevenLabs API (not the MCP).

Reads the API key from the environment (or a .env file beside this script) so the
secret never lives in code or chat. Generates each segment's `tts` (or `vo`) and
saves assets/v{id}.wav (48 kHz stereo). Once this file exists, make_video.py runs
it automatically -> the whole pipeline is hands-off.

SETUP (you do this once; the key stays on your machine):
  1. Get a key at elevenlabs.io -> Profile -> API Keys.
  2. Put it in a .env file in this folder:   ELEVENLABS_API_KEY=sk_...
     (or set a Windows env var ELEVENLABS_API_KEY). .env is gitignored.
  3. In spec.json "voice", add:  "elevenlabs_voice_id": "<the voice id you picked>"
     (a voice id is not a secret). Optional: "elevenlabs_model", "voice_settings".

Cost: ElevenLabs bills in USD by characters. eleven_multilingual_v2 ~= $0.10 / 1k
chars (~$0.75 for an 11-min script); eleven_turbo_v2_5 ~= $0.05 / 1k (half).

Usage:  python gen_voice.py [project_dir]
"""
import json, os, sys, time, subprocess, urllib.request, urllib.error

ROOT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "assets")
FFMPEG = r"E:\faceless\kannada_reel\bin\ffmpeg.exe"
os.makedirs(ASSETS, exist_ok=True)


def load_key():
    k = os.environ.get("ELEVENLABS_API_KEY")
    if k:
        return k.strip()
    envf = os.path.join(ROOT, ".env")
    if os.path.exists(envf):
        for line in open(envf, encoding="utf-8"):
            line = line.strip()
            if line.startswith("ELEVENLABS_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("No ELEVENLABS_API_KEY found. Put it in a .env file in %s or set the env var." % ROOT)


spec = json.load(open(os.path.join(ROOT, "spec.json"), encoding="utf-8"))
V = spec.get("voice", {})
voice_id = V.get("elevenlabs_voice_id")
if not voice_id:
    sys.exit('spec.json voice.elevenlabs_voice_id is not set. Add the voice id you picked on ElevenLabs.')
model = V.get("elevenlabs_model", "eleven_multilingual_v2")
# lower stability => more dynamic/modulated narration (the lever the MCP hid)
vs = V.get("voice_settings", {"stability": 0.40, "similarity_boost": 0.75,
                              "style": 0.35, "use_speaker_boost": True})
KEY = load_key()

segs = spec["segments"]
todo = [s for s in segs if not os.path.exists(os.path.join(ASSETS, "v%d.wav" % s["id"]))]
if not todo:
    print("all VO present -- nothing to do")
    sys.exit(0)

chars = sum(len(s.get("tts", s["vo"])) for s in todo)
print("ElevenLabs: %d takes, ~%d chars, voice=%s, model=%s" % (len(todo), chars, voice_id, model))

url = "https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=mp3_44100_128" % voice_id
for s in todo:
    text = s.get("tts", s["vo"])
    body = json.dumps({"text": text, "model_id": model, "voice_settings": vs}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "xi-api-key": KEY, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        mp3 = urllib.request.urlopen(req, timeout=120).read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        sys.exit("ElevenLabs HTTP %s on shot %d: %s" % (e.code, s["id"], detail))
    tmp = os.path.join(ASSETS, "v%d.mp3" % s["id"])
    open(tmp, "wb").write(mp3)
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", tmp,
                    "-ar", "48000", "-ac", "2", os.path.join(ASSETS, "v%d.wav" % s["id"])], check=True)
    os.remove(tmp)
    print("  v%-2d  %4d chars  ok" % (s["id"], len(text)))
    time.sleep(0.4)   # be polite to the API

print("\nDONE %d VO takes -> %s" % (len(todo), ASSETS))
