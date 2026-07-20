# Smoke-test the local Z-Image Turbo install against the same prompt used on
# the cloud z_image model, so quality and speed are directly comparable.
import json, time, urllib.request

LOCAL = "http://127.0.0.1:8188"
STYLE = ("Simple flat 2D cartoon illustration, thick black outlines, flat solid color fills, "
         "no gradients, no shading, no depth of field, sharp flat background, simple rounded "
         "character shapes, minimal simple facial features, naive hand-drawn indie animation "
         "style, limited muted color palette")
PROMPT = ("A snowy poor Japanese village street at dusk in winter, simple wooden farmhouses, "
          "bare trees, soft falling snow, one small lantern glowing. " + STYLE)

wf = {
    "1": {"class_type": "UNETLoader", "inputs": {
        "unet_name": "z_image_turbo_bf16.safetensors", "weight_dtype": "default"}},
    "2": {"class_type": "CLIPLoader", "inputs": {
        "clip_name": "qwen_3_4b.safetensors", "type": "lumina2", "device": "default"}},
    "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
    "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"shift": 3, "model": ["1", 0]}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPT, "clip": ["2", 0]}},
    "7": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["6", 0]}},
    "8": {"class_type": "EmptySD3LatentImage", "inputs": {
        "width": 1344, "height": 768, "batch_size": 1}},
    "9": {"class_type": "KSampler", "inputs": {
        "seed": 42, "control_after_generate": "fixed",
        "steps": 8, "cfg": 1, "sampler_name": "res_multistep",
        "scheduler": "simple", "denoise": 1,
        "model": ["4", 0], "positive": ["6", 0],
        "negative": ["7", 0], "latent_image": ["8", 0]}},
    "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
    "11": {"class_type": "SaveImage", "inputs": {
        "filename_prefix": "20260720_geisha-village-local", "images": ["10", 0]}},
}

payload = json.dumps({"prompt": wf}).encode("utf-8")
req = urllib.request.Request(f"{LOCAL}/prompt", data=payload,
                             headers={"Content-Type": "application/json"})
t0 = time.time()
pid = json.loads(urllib.request.urlopen(req).read())["prompt_id"]
print("submitted", pid)

while time.time() - t0 < 600:
    with urllib.request.urlopen(f"{LOCAL}/history/{pid}") as r:
        h = json.loads(r.read())
    if pid in h:
        st = h[pid].get("status", {})
        if st.get("completed") or st.get("status_str") in ("success", "error"):
            print("status:", st.get("status_str"), " elapsed: %.1fs" % (time.time() - t0))
            for nid, out in h[pid].get("outputs", {}).items():
                for im in out.get("images", []):
                    print("  ->", im["filename"])
            break
    time.sleep(2)
else:
    print("TIMEOUT")
