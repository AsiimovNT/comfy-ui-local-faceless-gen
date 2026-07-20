# -*- coding: utf-8 -*-
"""
gen_anim.py -- general content-aware limited-animation generator.

For every segment that declares an `animate` list in spec.json, this inpaints
each region's variant state (eyes-closed, brighter-flame, ...) changing ONLY the
masked area, then saves it as a transparent-background overlay (region opaque,
everything else clear, edges feathered). assemble.py later composites these onto
the base still with per-pattern timing.

This is format-agnostic: the schema + engine don't know about geisha. A new video
just needs `animate` blocks authored from what's in each frame (the vision pass).

Schema (per segment):
  "animate": [
    {"element":"eyes","pattern":"blink","shape":"ellipse",
     "mask":[x0,y0,x1,y1],                      # normalized 0..1
     "prompt":"both eyes fully closed, ...",     # target state of the region
     "variants":1, "denoise":0.85}
  ]

Usage:  python gen_anim.py [project_dir]
"""
import json, os, sys, time, uuid, urllib.request
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
spec = json.load(open(os.path.join(ROOT, "spec.json"), encoding="utf-8"))
R = spec["render"]
LOCAL = R["url"].rstrip("/")
ASSETS = os.path.join(ROOT, "assets")
ANIM = os.path.join(ASSETS, "anim")
os.makedirs(ANIM, exist_ok=True)
STYLE = R["style_suffix"]
FEATHER = 8   # px, soft edge so composited regions blend seamlessly


def upload(path):
    name = "anim_" + os.path.basename(path)
    b = "----ff" + uuid.uuid4().hex
    data = open(path, "rb").read()
    body = (("--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"%s\"\r\n"
             "Content-Type: image/png\r\n\r\n" % (b, name)).encode() + data +
            ("\r\n--%s\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--%s--\r\n" % (b, b)).encode())
    req = urllib.request.Request(LOCAL + "/upload/image", data=body,
                                 headers={"Content-Type": "multipart/form-data; boundary=" + b})
    return json.loads(urllib.request.urlopen(req).read())["name"]


def inpaint(src_name, mask_name, prompt, seed, denoise):
    wf = {
      "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "z_image_turbo_bf16.safetensors", "weight_dtype": "default"}},
      "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "lumina2", "device": "default"}},
      "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
      "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"shift": 3, "model": ["1", 0]}},
      "5": {"class_type": "LoadImage", "inputs": {"image": src_name}},
      "6": {"class_type": "LoadImageMask", "inputs": {"image": mask_name, "channel": "red"}},
      "7": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["3", 0]}},
      "8": {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["7", 0], "mask": ["6", 0]}},
      "9": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt + ", " + STYLE, "clip": ["2", 0]}},
      "10": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["9", 0]}},
      "11": {"class_type": "KSampler", "inputs": {
            "seed": seed, "control_after_generate": "fixed", "steps": 8, "cfg": 1,
            "sampler_name": "res_multistep", "scheduler": "simple", "denoise": denoise,
            "model": ["4", 0], "positive": ["9", 0], "negative": ["10", 0], "latent_image": ["8", 0]}},
      "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
      "13": {"class_type": "SaveImage", "inputs": {"filename_prefix": "_anim_tmp", "images": ["12", 0]}},
    }
    pid = json.loads(urllib.request.urlopen(urllib.request.Request(
        LOCAL + "/prompt", data=json.dumps({"prompt": wf}).encode(),
        headers={"Content-Type": "application/json"})).read())["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < 300:
        h = json.loads(urllib.request.urlopen(LOCAL + "/history/" + pid).read())
        if pid in h and (h[pid].get("status", {}).get("completed") or
                         h[pid].get("status", {}).get("status_str") in ("success", "error")):
            for out in h[pid].get("outputs", {}).values():
                for im in out.get("images", []):
                    q = "filename=%s&subfolder=%s&type=%s" % (im["filename"], im.get("subfolder", ""), im.get("type", "output"))
                    return urllib.request.urlopen(LOCAL + "/view?" + q).read()
            return None
        time.sleep(1.5)
    raise TimeoutError(pid)


def make_mask(size, box, shape):
    W, H = size
    px = (int(W*box[0]), int(H*box[1]), int(W*box[2]), int(H*box[3]))
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    (d.ellipse if shape == "ellipse" else d.rectangle)(px, fill=255)
    return m, px


try:
    urllib.request.urlopen(LOCAL + "/system_stats", timeout=5)
except Exception:
    sys.exit("ComfyUI not reachable at %s -- start it first." % LOCAL)

total = 0
for s in spec["segments"]:
    for blk in s.get("animate", []):
        base_path = os.path.join(ASSETS, s["image"])
        base = Image.open(base_path).convert("RGB")
        mask, _ = make_mask(base.size, blk["mask"], blk.get("shape", "ellipse"))
        mask_path = os.path.join(ANIM, "_mask_%d_%s.png" % (s["id"], blk["element"]))
        mask.save(mask_path)
        src_name = upload(base_path)
        mask_name = upload(mask_path)
        # soft alpha from the mask for seamless compositing
        alpha = mask.filter(ImageFilter.GaussianBlur(FEATHER))
        n = int(blk.get("variants", 1))
        for k in range(n):
            png = inpaint(src_name, mask_name, blk["prompt"],
                          seed=100 + s["id"] * 10 + k, denoise=float(blk.get("denoise", 0.85)))
            var = Image.open(__import__("io").BytesIO(png)).convert("RGB").resize(base.size)
            region = var.convert("RGBA"); region.putalpha(alpha)     # keep only masked area
            stem = os.path.splitext(s["image"])[0]
            outp = os.path.join(ANIM, "%s__%s_%d.png" % (stem, blk["element"], k))
            region.save(outp)
            total += 1
            print("  S%-2d %-8s v%d -> anim/%s" % (s["id"], blk["element"], k, os.path.basename(outp)))

print("\nDONE %d overlay(s) -> %s" % (total, ANIM))
