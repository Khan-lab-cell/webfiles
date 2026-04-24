#!/bin/bash

# Kill old sessions
tmux kill-session -t comfyui 2>/dev/null
tmux kill-session -t fastapi 2>/dev/null
tmux kill-session -t ngrok 2>/dev/null

# Start ComfyUI
tmux new-session -d -s comfyui
tmux send-keys -t comfyui "cd ~/ComfyUI && python main.py --listen" Enter

# Wait for ComfyUI to load
sleep 8

# Start FastAPI
tmux new-session -d -s fastapi
tmux send-keys -t fastapi "cd ~/backend && python main.py" Enter

# Wait for FastAPI
sleep 4

# Start Ngrok
tmux new-session -d -s ngrok
tmux send-keys -t ngrok "ngrok http --url=mite-next-grouper.ngrok-free.app 8000" Enter

echo "✅ ComfyUI + FastAPI + Ngrok sab start ho gaye!"
