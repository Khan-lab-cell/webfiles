#!/bin/bash

# === Base Folder ===
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

# === Shortcuts ===
dlcheckpoint() { _dl "$COMFY/checkpoints" "$1" "$2"; }
dlclipvision() { _dl "$COMFY/clip_vision" "$1" "$2"; }
dllora()       { _dl "$COMFY/loras" "$1" "$2"; }
dlpatch()      { _dl "$COMFY/model_patches" "$1" "$2"; }

# === Downloads Start ===
echo "🚀 Starting downloads..."

# Checkpoints
dlcheckpoint "https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev-fp8.safetensors" "flux1-dev-fp8.safetensors"

# Clip Vision
dlclipvision "https://huggingface.co/Comfy-Org/sigclip_vision_384/resolve/main/sigclip_vision_patch14_384.safetensors" "sigclip_vision_patch14_384.safetensors"

# Lora
dllora "https://huggingface.co/Comfy-Org/USO_1.0_Repackaged/resolve/main/split_files/loras/uso-flux1-dit-lora-v1.safetensors" "uso-flux1-dit-lora-v1.safetensors"

# Model Patch
dlpatch "https://huggingface.co/Comfy-Org/USO_1.0_Repackaged/resolve/main/split_files/model_patches/uso-flux1-projector-v1.safetensors" "uso-flux1-projector-v1.safetensors"

echo "✅ All downloads completed!"