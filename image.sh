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

# --- Original z_image_turbo models ---
dltext "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors" "qwen_3_4b.safetensors"

dllora "https://huggingface.co/tarn59/pixel_art_style_lora_z_image_turbo/resolve/main/pixel_art_style_z_image_turbo.safetensors" "pixel_art_style_z_image_turbo.safetensors"

dlcustom "/root/ComfyUI/models/diffusion_models" "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors" "z_image_turbo_bf16.safetensors"

dlvae "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors" "ae.safetensors"

# --- Qwen Image Edit models (from https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit) ---
# Diffusion model
dlcustom "/root/ComfyUI/models/diffusion_models" "https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors" "qwen_image_edit_2509_fp8_e4m3fn.safetensors"

# LoRA
dllora "https://huggingface.co/lightx2v/Qwen-Image-Lightning/resolve/main/Qwen-Image-Edit-2509/Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors" "Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors"

# Text encoder
dltext "https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" "qwen_2.5_vl_7b_fp8_scaled.safetensors"

# VAE
dlvae "https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors" "qwen_image_vae.safetensors"

echo "✅ All done!"