# comy-ui-local-faceless-gen

Local-first pipeline for Lost-Legacy-style animated history videos ("Your Life as a…").
**Images: local ComfyUI (free) · VO: ElevenLabs via Higgsfield MCP · Stitch: ffmpeg.**

`spec.json` is the single source of truth — script, image prompts, style, timing,
voice all live there. To make a new video, copy this folder, rewrite `spec.json`,
and run the four steps below.

## One command

```
python make_video.py [project_dir] [--force-images]
```
Orchestrates all four steps, skipping any whose outputs already exist. If VO is
missing and there's no `gen_voice.py`, it writes `vo_manifest.json` (which shots
need audio + their text) and stops; fill those `v{id}.wav`, re-run, it resumes.

## Pipeline

```
spec.json ─┬─► gen_images.py   → local ComfyUI :8188 → assets/sNN_*.png   [SCRIPT, free]
           ├─► (VO)            → ElevenLabs (Higgsfield MCP, or gen_voice.py) [pluggable]
           ├─► build_captions.py → faster-whisper word-align → captions.ass [SCRIPT]
           └─► assemble.py     → ffmpeg (stills + KB + captions + music) → *_1080p.mp4 [SCRIPT]
```

The VOICE step is the one pluggable seam. Add a `gen_voice.py` (e.g. direct
ElevenLabs API, key from env) and `make_video.py` runs fully unattended.
Without it, the agent fills the VO via the Higgsfield MCP.

## How each image gets its own prompt

`spec.json` holds one `img_prompt` per segment plus a shared `render.style_suffix`.
`gen_images.py` never opens the ComfyUI UI — it builds the Z-Image node graph as
JSON in memory and, **per shot**, injects that shot's text into the graph's
`CLIPTextEncode` node, sets a per-shot seed and output name, then POSTs it to
ComfyUI's `/prompt` REST endpoint. ComfyUI queues the jobs and runs them one at a
time; each returns one PNG, downloaded into `assets/`.

So the graph (the "workflow") is a **fixed template** — only the prompt string,
seed, and filename change between images. `make_zimage_graph.py` writes one frozen
snapshot of that graph (shot 1's prompt) to the ComfyUI UI as `Zimage_Geisha.json`
so you can *see and tweak it visually*; the batch script runs the identical graph,
just parameterized.

```
spec.json[segment N].img_prompt + render.style_suffix
        │
        ▼   (injected into CLIPTextEncode.text, + seed, + filename)
   Z-Image graph  ──POST /prompt──►  ComfyUI :8188  ──►  assets/sNN_*.png
```

### Step 1 — images (unattended, free)
Start ComfyUI (see the `comfyui-local` skill), then:
```
python gen_images.py
```
Z-Image Turbo, seed = `render.base_seed + id` (deterministic; add a `"seed"` field
to a segment to re-roll just that shot). ~30s/frame at 1920×1088. First-ever frames
are backed up to `assets/cloud_backup/`.

### Step 2 — voiceover (agent-driven)
**This step needs the agent** — the Higgsfield MCP isn't a REST key a script can hold.
Ask Claude to generate VO for each segment's `vo` (or `tts` phonetic override) using
`text2speech_v2` / `elevenlabs` / voice_id in `spec.json`, saved as `assets/vN.wav`
(48kHz stereo). ~0.0146 cr/word.
*(For fully-unattended VO later: add a direct ElevenLabs API key + a `gen_voice.py`.
Trade-off: you lose the "Isabella" Higgsfield preset.)*

### Step 3 — captions
```
python build_captions.py
```
Whisper word-timestamps aligned onto the known script text (timing from whisper,
spelling from spec). Writes `plan.json` + `captions.ass`.

### Step 4 — assemble
```
python assemble.py
```
Reads `plan.json`. Locked-off stills (no jitter). Burns captions. Auto-mixes
`assets/music.mp3` at 10% under the VO if present. → `<project>_1080p.mp4`.

## Key spec.json knobs
- `motion`: `false` = still frames (default; zoompan jitters — see memory). `true` = Ken Burns.
- `timing.speed`: pace dial (atempo, pitch-preserving; 1.05–1.15 usable).
- `render.width/height`: 1920×1088 (÷16, ≥1080p). Drop to 1536×864 for ~2× faster local gen.
- `caption_style.margin_v`: raise to lift captions off faces in close-ups.

## Requirements (paths are machine-specific)
- **ComfyUI** with Z-Image Turbo, serving at `render.url` (default `http://127.0.0.1:8188`).
- **Python 3** with `faster-whisper` (used by `build_captions.py`).
- **ffmpeg / ffprobe** — currently hardcoded to `E:\faceless\kannada_reel\bin\`
  in `assemble.py` / `build_captions.py`. Edit those two constants for another machine.

## Cost per 11-min video
Images **0** (local) · VO **~20 cr** (ElevenLabs via MCP) · everything else free.
