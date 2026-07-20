# -*- coding: utf-8 -*-
"""
Emit a UI-format ComfyUI graph for the Z-Image Turbo pipeline that gen_images.py
uses, so it shows up in the ComfyUI Workflows panel (editable, runnable live).

Writes -> ComfyUI/user/default/workflows/Zimage_Geisha.json
After it lands, press F5 in ComfyUI; it appears in the Workflows sidebar.
"""
import json, os

OUT = (r"E:\ComfyUI\ComfyUI_windows_portable\ComfyUI"
       r"\user\default\workflows\Zimage_Geisha.json")

STYLE = ("Simple flat 2D cartoon illustration, thick black outlines, flat solid color fills, "
         "no gradients, no shading, no depth of field, sharp flat background, simple rounded "
         "character shapes, minimal simple facial features, naive hand-drawn indie animation "
         "style, limited muted color palette")
PROMPT = ("Extreme close up of a young Japanese geisha woman's face, stark white painted makeup, "
          "small red painted lips, black hair in an elaborate bun with a pink flower ornament, "
          "one single tear running down her white painted cheek, dark rainy night background "
          "with a soft glowing paper lantern. " + STYLE)

# node(id, type, pos, size, widgets, inputs[(name,type)], outputs[(name,type)])
def N(i, t, pos, size, widgets, ins, outs):
    return {"id": i, "type": t, "pos": pos, "size": size, "flags": {}, "order": i,
            "mode": 0,
            "inputs":  [{"name": n, "type": ty, "link": None} for n, ty in ins],
            "outputs": [{"name": n, "type": ty, "slot_index": s, "links": []}
                        for s, (n, ty) in enumerate(outs)],
            "properties": {"Node name for S&R": t}, "widgets_values": widgets}

nodes = [
    N(1, "UNETLoader",            [40, 40],  [330, 130],
      ["z_image_turbo_bf16.safetensors", "default"], [], [("MODEL", "MODEL")]),
    N(2, "CLIPLoader",            [40, 220], [330, 130],
      ["qwen_3_4b.safetensors", "lumina2", "default"], [], [("CLIP", "CLIP")]),
    N(3, "VAELoader",             [40, 400], [330, 90],
      ["ae.safetensors"], [], [("VAE", "VAE")]),
    N(4, "ModelSamplingAuraFlow", [420, 40], [300, 80],
      [3], [("model", "MODEL")], [("MODEL", "MODEL")]),
    N(6, "CLIPTextEncode",        [420, 180], [400, 200],
      [PROMPT], [("clip", "CLIP")], [("CONDITIONING", "CONDITIONING")]),
    N(7, "ConditioningZeroOut",   [420, 430], [300, 70],
      [], [("conditioning", "CONDITIONING")], [("CONDITIONING", "CONDITIONING")]),
    N(8, "EmptySD3LatentImage",   [420, 560], [300, 130],
      [1920, 1088, 1], [], [("LATENT", "LATENT")]),
    N(9, "KSampler",              [870, 40], [320, 320],
      [42, "fixed", 8, 1, "res_multistep", "simple", 1],
      [("model", "MODEL"), ("positive", "CONDITIONING"),
       ("negative", "CONDITIONING"), ("latent_image", "LATENT")],
      [("LATENT", "LATENT")]),
    N(10, "VAEDecode",            [1240, 40], [260, 60],
      [], [("samples", "LATENT"), ("vae", "VAE")], [("IMAGE", "IMAGE")]),
    N(11, "SaveImage",            [1240, 160], [420, 450],
      ["geisha"], [("images", "IMAGE")], []),
]
byid = {n["id"]: n for n in nodes}

# links: (from_node, from_slot, to_node, to_slot, type)
raw = [
    (1, 0, 4, 0, "MODEL"),
    (4, 0, 9, 0, "MODEL"),
    (2, 0, 6, 0, "CLIP"),
    (6, 0, 9, 1, "CONDITIONING"),
    (6, 0, 7, 0, "CONDITIONING"),
    (7, 0, 9, 2, "CONDITIONING"),
    (8, 0, 9, 3, "LATENT"),
    (9, 0, 10, 0, "LATENT"),
    (3, 0, 10, 1, "VAE"),
    (10, 0, 11, 0, "IMAGE"),
]
links = []
for lid, (fn, fs, tn, ts, ty) in enumerate(raw, start=1):
    links.append([lid, fn, fs, tn, ts, ty])
    byid[fn]["outputs"][fs]["links"].append(lid)
    byid[tn]["inputs"][ts]["link"] = lid

graph = {"last_node_id": 11, "last_link_id": len(links),
         "nodes": nodes, "links": links, "groups": [],
         "config": {}, "extra": {}, "version": 0.4}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(graph, open(OUT, "w", encoding="utf-8"), indent=1)
print("wrote", OUT)
