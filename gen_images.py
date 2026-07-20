# -*- coding: utf-8 -*-
"""
gen_images.py -- batch-generate every shot's still from LOCAL ComfyUI (free).

Reads spec.json (single source of truth): each segment's `img_prompt` + the
shared `render.style_suffix` -> Z-Image Turbo -> saved into assets/<image>.

Fully standalone: talks to ComfyUI's REST API at render.url, no agent needed.
Deterministic: seed = render.base_seed + segment id (override per shot with a
"seed" field). Re-running reproduces the same frames; bump a shot's seed to
re-roll just that one.

Usage:  python gen_images.py [project_dir]   (default: this script's folder)
"""
import json, os, sys, time, shutil, urllib.request, urllib.parse

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
spec = json.load(open(os.path.join(ROOT, "spec.json"), encoding="utf-8"))
R = spec["render"]
LOCAL = R["url"].rstrip("/")
ASSETS = os.path.join(ROOT, "assets")
os.makedirs(ASSETS, exist_ok=True)


def zimage_graph(prompt, w, h, seed, prefix):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "z_image_turbo_bf16.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen_3_4b.safetensors", "type": "lumina2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"shift": 3, "model": ["1", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "7": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["6", 0]}},
        "8": {"class_type": "EmptySD3LatentImage", "inputs": {
            "width": w, "height": h, "batch_size": 1}},
        "9": {"class_type": "KSampler", "inputs": {
            "seed": seed, "control_after_generate": "fixed",
            "steps": 8, "cfg": 1, "sampler_name": "res_multistep",
            "scheduler": "simple", "denoise": 1,
            "model": ["4", 0], "positive": ["6", 0],
            "negative": ["7", 0], "latent_image": ["8", 0]}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["10", 0]}},
    }


def submit(wf):
    data = json.dumps({"prompt": wf}).encode("utf-8")
    req = urllib.request.Request(f"{LOCAL}/prompt", data=data,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())["prompt_id"]


def wait(pid, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        with urllib.request.urlopen(f"{LOCAL}/history/{pid}") as r:
            h = json.loads(r.read())
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("completed") or st.get("status_str") in ("success", "error"):
                return h[pid]
        time.sleep(1.5)
    raise TimeoutError(pid)


def fetch(img, dest):
    q = urllib.parse.urlencode({"filename": img["filename"],
                                "subfolder": img.get("subfolder", ""),
                                "type": img.get("type", "output")})
    with urllib.request.urlopen(f"{LOCAL}/view?{q}") as r:
        open(dest, "wb").write(r.read())


# reachable?
try:
    urllib.request.urlopen(f"{LOCAL}/system_stats", timeout=5)
except Exception:
    sys.exit("ComfyUI not reachable at %s -- start the server first." % LOCAL)

# archive any existing (e.g. cloud-generated) frames once
bk = os.path.join(ASSETS, "cloud_backup")
if not os.path.exists(bk):
    os.makedirs(bk)
    for s in spec["segments"]:
        p = os.path.join(ASSETS, s["image"])
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(bk, s["image"]))
    print("archived existing frames -> assets/cloud_backup/")

style = R["style_suffix"]
t0 = time.time()
for s in spec["segments"]:
    i = s["id"]
    seed = s.get("seed", R["base_seed"] + i)
    prompt = s["img_prompt"].rstrip() + " " + style
    prefix = "_tmp_%s_s%02d" % (spec["project"], i)
    st = time.time()
    hist = wait(submit(zimage_graph(prompt, R["width"], R["height"], seed, prefix)))
    imgs = [im for out in hist.get("outputs", {}).values() for im in out.get("images", [])]
    if not imgs:
        print("  S%-2d FAILED (no image) -- %s" % (i, hist.get("status")))
        continue
    fetch(imgs[0], os.path.join(ASSETS, s["image"]))
    print("  S%-2d %-24s seed=%d  %4.1fs" % (i, s["image"], seed, time.time() - st))

print("\nDONE %d frames in %.1fs -> %s" % (len(spec["segments"]), time.time() - t0, ASSETS))
