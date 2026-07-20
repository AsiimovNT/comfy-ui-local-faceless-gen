# Build an eye-region mask for inpaint-based blink frames, + a preview to verify
# placement before spending a generation. Run with ComfyUI's embedded python (has PIL).
import sys
from PIL import Image, ImageDraw

SRC = r"E:\faceless\comy-ui-local-faceless-gen\assets\s01_geisha_closeup.png"
img = Image.open(SRC).convert("RGB")
W, H = img.size
print("image:", W, H)

# eye band (tuned for the face-filling closeup); ellipse bbox in px
box = (int(W*0.28), int(H*0.47), int(W*0.60), int(H*0.58))

mask = Image.new("L", (W, H), 0)
ImageDraw.Draw(mask).ellipse(box, fill=255)
mask.save(r"E:\faceless\comy-ui-local-faceless-gen\assets\mask_eyes.png")

prev = img.copy()
ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(ov).ellipse(box, fill=(255, 0, 0, 110))
prev = Image.alpha_composite(prev.convert("RGBA"), ov).convert("RGB")
prev.save(r"E:\faceless\comy-ui-local-faceless-gen\assets\_mask_preview.png")
print("mask box:", box)
