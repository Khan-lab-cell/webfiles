#!/bin/bash

# === Folders ===
COMFY="/root/ComfyUI/models"

# === Download Function ===
_dl() {
  mkdir -p "$1"
  if [ -n "$3" ]; then
    aria2c -x 16 -s 16 -k 1M --max-tries=0 \
      --retry-wait=10 --continue=true \
      --dir="$1" --out="$3" "$2"
  else
    FNAME=$(basename "$2" | cut -d'?' -f1)
    aria2c -x 16 -s 16 -k 1M --max-tries=0 \
      --retry-wait=10 --continue=true \
      --dir="$1" --out="$FNAME" "$2"
  fi
}

dlcheck()   { _dl "$COMFY/checkpoints" "$1" "$2"; }
dllora()    { _dl "$COMFY/loras" "$1" "$2"; }
dlvae()     { _dl "$COMFY/vae" "$1" "$2"; }
dlupscale() { _dl "$COMFY/latent_upscale_models" "$1" "$2"; }
dlclip()    { _dl "$COMFY/clip" "$1" "$2"; }
dlcontrol() { _dl "$COMFY/controlnet" "$1" "$2"; }
dltext()    { _dl "$COMFY/text_encoders" "$1" "$2"; }
dlcustom()  { _dl "$1" "$2" "$3"; }

# === Downloads ===
echo "🚀 Starting all downloads..."
dlcheck "https://huggingface.co/Lightricks/LTX-2.3-fp8/resolve/main/ltx-2.3-22b-dev-fp8.safetensors" "ltx-2.3-22b-dev-fp8.safetensors"

dllora "https://huggingface.co/Lightricks/LTX-2.3/resolve/main/ltx-2.3-22b-distilled-lora-384.safetensors" "ltx-2.3-22b-distilled-lora-384.safetensors"
dllora "https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/loras/gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors" "gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors"

dlupscale "https://huggingface.co/Lightricks/LTX-2.3/resolve/main/ltx-2.3-spatial-upscaler-x2-1.1.safetensors" "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"

dltext "https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors" "gemma_3_12B_it_fp4_mixed.safetensors"

echo "✅ All done!"
