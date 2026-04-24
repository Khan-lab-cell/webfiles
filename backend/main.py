import json
import uuid
import urllib.request
import urllib.parse
import websocket
import asyncio
import os
import time
import random
import logging
import requests # Added for Supabase uploads
import shutil # Added for file operations
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Form, UploadFile, File, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import Optional, Dict

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- VPS Configuration ---
# VPS 1 is for IMAGES only. VPS 2-10 are for VIDEOS only.
# You can use "127.0.0.1:8188" for localhost or "your-link.ngrok-free.app" for Ngrok.
# IMPORTANT: Do not include http:// or https:// in these URLs.
VPS_POOL = [
    {"url": os.getenv("COMFYUI_URL", "127.0.0.1:8188"), "type": "image"}, # VPS 1 (Image)
    {"url": os.getenv("COMFYUI_URL", "127.0.0.1:8188"), "type": "video"},               # VPS 2 (Video)
    {"url": "vps-3-link.ngrok-free.app", "type": "video"},               # VPS 3 (Video)
    {"url": "vps-4-link.ngrok-free.app", "type": "video"},               # VPS 4 (Video)
    {"url": "vps-5-link.ngrok-free.app", "type": "video"},               # VPS 5 (Video)
    {"url": "vps-6-link.ngrok-free.app", "type": "video"},               # VPS 6 (Video)
    {"url": "vps-7-link.ngrok-free.app", "type": "video"},               # VPS 7 (Video)
    {"url": "vps-8-link.ngrok-free.app", "type": "video"},               # VPS 8 (Video)
    {"url": "vps-9-link.ngrok-free.app", "type": "video"},               # VPS 9 (Video)
    {"url": "vps-10-link.ngrok-free.app", "type": "video"},              # VPS 10 (Video)
]

# Track busy status of each VPS
vps_busy_status = {i: False for i in range(len(VPS_POOL))}

OUTPUT_DIR = "outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Supabase Configuration (Set these on your VPS!)
SUPABASE_URL = "https://uusdmbgxxywvpvwtejlp.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InV1c2RtYmd4eHl3dnB2d3RlamxwIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MjI2MDk1MiwiZXhwIjoyMDg3ODM2OTUyfQ.fzQBtfcVY43r95REM-g50aYePfQExNiQV9OP-LtmUS0" # Use Service Role Key for backend uploads
BUCKET_NAME = "generated-content"

# --- NEW: WebSocket Route for Frontend ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, clientId: Optional[str] = None):
    await websocket.accept()
    logger.info(f"Frontend connected via WebSocket. ClientID: {clientId}")
    try:
        while True:
            # We just keep the connection alive. 
            # You can later use this to send real progress to the frontend!
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info(f"Frontend disconnected. ClientID: {clientId}")

# Job Queue
job_queue = asyncio.Queue()
job_results: Dict[str, dict] = {}

class ComfyUIClient:
    def __init__(self, server_address):
        self.server_address = server_address
        self.client_id = str(uuid.uuid4())

    def queue_prompt(self, prompt):
        p = {"prompt": prompt, "client_id": self.client_id}
        data = json.dumps(p).encode('utf-8')
        protocol = "https" if "ngrok" in self.server_address else "http"
        req = urllib.request.Request(f"{protocol}://{self.server_address}/prompt", data=data)
        return json.loads(urllib.request.urlopen(req).read())

    def upload_image(self, file_path):
        """Uploads an image to ComfyUI server."""
        try:
            # Determine if we should use http or https (Ngrok usually uses https, but ComfyUI API is http)
            # However, Ngrok handles the SSL termination, so we just use http for the local-style call
            # or detect if it's an ngrok link.
            protocol = "https" if "ngrok" in self.server_address else "http"
            
            with open(file_path, "rb") as f:
                files = {"image": f}
                res = requests.post(f"{protocol}://{self.server_address}/upload/image", files=files)
                return res.json()
        except Exception as e:
            logger.error(f"Error uploading image to ComfyUI ({self.server_address}): {e}")
            return None

    def get_image(self, filename, subfolder, folder_type):
        data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        url_values = urllib.parse.urlencode(data)
        protocol = "https" if "ngrok" in self.server_address else "http"
        with urllib.request.urlopen(f"{protocol}://{self.server_address}/view?{url_values}") as response:
            return response.read()

    def get_history(self, prompt_id):
        protocol = "https" if "ngrok" in self.server_address else "http"
        with urllib.request.urlopen(f"{protocol}://{self.server_address}/history/{prompt_id}") as response:
            return json.loads(response.read())

    async def run_workflow(self, workflow, job_id):
        # Use a thread-safe way to run the blocking websocket
        def _run():
            ws = websocket.WebSocket()
            protocol_ws = "wss" if "ngrok" in self.server_address else "ws"
            try:
                ws.connect(f"{protocol_ws}://{self.server_address}/ws?clientId={self.client_id}")
                
                prompt_id = self.queue_prompt(workflow)['prompt_id']
                logger.info(f"Queued prompt ID: {prompt_id} for job {job_id}")
                
                while True:
                    out = ws.recv()
                    if isinstance(out, str):
                        message = json.loads(out)
                        
                        # Update progress
                        if message['type'] == 'progress':
                            data = message['data']
                            if data['prompt_id'] == prompt_id:
                                val = data.get('value', 0)
                                m = data.get('max', 1)
                                if m > 0:
                                    new_progress = int((val / m) * 100)
                                    # Ensure progress doesn't exceed 100 and handle resets gracefully
                                    new_progress = min(100, max(0, new_progress))
                                    
                                    if job_id in job_results:
                                        # Make progress non-decreasing to avoid resets between nodes
                                        current_p = job_results[job_id].get('progress', 0)
                                        if new_progress > current_p:
                                            job_results[job_id]['progress'] = new_progress
                                            logger.info(f"Job {job_id} progress: {new_progress}%")

                        if message['type'] == 'executing':
                            data = message['data']
                            if data['node'] is None and data['prompt_id'] == prompt_id:
                                break
                    else:
                        continue
                
                ws.close()
                return self.get_history(prompt_id)[prompt_id]
            except Exception as e:
                if ws:
                    ws.close()
                raise e

        # Run the blocking websocket logic in a separate thread to avoid blocking the event loop
        history = await asyncio.to_thread(_run)
        
        # Find the output node
        best_node_results = []
        best_node_id = None
        all_collected_results = []
        seen_keys = set()

        # Sort node_ids to have some consistency
        node_ids = sorted(history['outputs'].keys(), key=lambda x: int(x) if x.isdigit() else 999)
        
        logger.info(f"Processing history outputs for job {job_id}. Found nodes: {node_ids}")

        for node_id in node_ids:
            node_output = history['outputs'][node_id]
            node_results = []
            
            # Check for Videos/GIFs (VHS nodes often use 'gifs' or 'videos')
            for key in ['gifs', 'videos']:
                if key in node_output:
                    for item in node_output[key]:
                        filename = item.get('filename', '')
                        if not filename: continue
                        
                        if filename.endswith('.mp4') or item.get('format') == 'mp4':
                            mime = "video/mp4"
                        else:
                            mime = "image/gif"
                        
                        res = (self.get_image(item['filename'], item.get('subfolder', ''), item.get('type', 'output')), mime)
                        node_results.append(res)
                        
                        # Track unique results for the fallback
                        unique_key = f"{item.get('type', 'output')}/{item.get('subfolder', '')}/{filename}"
                        if unique_key not in seen_keys:
                            all_collected_results.append(res)
                            seen_keys.add(unique_key)
            
            # Check for Images
            if 'images' in node_output:
                for item in node_output['images']:
                    filename = item.get('filename', '')
                    if not filename: continue

                    if filename.endswith('.mp4') or item.get('format') == 'mp4':
                        mime = "video/mp4"
                    elif filename.endswith('.gif') or item.get('format') == 'gif':
                        mime = "image/gif"
                    else:
                        mime = "image/png"
                    
                    res = (self.get_image(item['filename'], item.get('subfolder', ''), item.get('type', 'output')), mime)
                    node_results.append(res)
                    
                    # Track unique results for the fallback
                    unique_key = f"{item.get('type', 'output')}/{item.get('subfolder', '')}/{filename}"
                    if unique_key not in seen_keys:
                        all_collected_results.append(res)
                        seen_keys.add(unique_key)
            
            if node_results:
                logger.info(f"Node {node_id} produced {len(node_results)} results")
                # Prioritize the node with the most results (likely the intended batch output)
                # If multiple nodes have the same max length, we take the later one (usually the final output)
                if len(node_results) >= len(best_node_results):
                    best_node_results = node_results
                    best_node_id = node_id
        
        # If we found a node with multiple results, it's likely our batch output
        if len(best_node_results) > 1:
            logger.info(f"Returning best batch output from node {best_node_id} with {len(best_node_results)} items")
            return best_node_results
        
        # If we didn't find a batch, return all unique results collected from all nodes
        if all_collected_results:
            logger.info(f"No batch found, returning all {len(all_collected_results)} unique collected results")
            return all_collected_results
        
        return []

def upload_to_supabase(file_data, filename, mime_type):
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.warning("Supabase credentials not set (SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY). Returning local path.")
        return None

    try:
        # 1. Upload to Supabase Storage
        # Path: bucket/filename
        clean_url = SUPABASE_URL.rstrip('/')
        url = f"{clean_url}/storage/v1/object/{BUCKET_NAME}/{filename}"
        
        logger.info(f"Uploading to Supabase Storage: {url} (Mime: {mime_type})")
        
        headers = {
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": mime_type,
            "x-upsert": "true"
        }
        
        response = requests.post(url, headers=headers, data=file_data)
        
        if response.status_code in [200, 201]:
            # 2. Return the public URL
            public_url = f"{clean_url}/storage/v1/object/public/{BUCKET_NAME}/{filename}"
            logger.info(f"Successfully uploaded to Supabase. Public URL: {public_url}")
            return public_url
        else:
            logger.error(f"Supabase Storage Upload Failed: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error in upload_to_supabase: {str(e)}")
        return None

async def worker():
    logger.info("Worker started")
    while True:
        job_id, job_data = await job_queue.get()
        logger.info(f"Processing job {job_id} for user {job_data['user_id']} (Type: {job_data['type']})")
        
        # --- VPS Selection Logic ---
        selected_vps_index = -1
        
        if job_data['type'] == 'image':
            # VPS 1 is dedicated to images
            selected_vps_index = 0
        else:
            # VPS 2-10 are for videos. Pick the first one that isn't busy.
            # If all are busy, it will wait in the queue loop because we only have one worker.
            # To support true parallel processing, we should start multiple workers.
            for i in range(1, len(VPS_POOL)):
                if not vps_busy_status[i]:
                    selected_vps_index = i
                    break
            
            # Fallback: if all video VPS are busy, just use VPS 2 (index 1) for now
            if selected_vps_index == -1:
                selected_vps_index = 1

        vps_config = VPS_POOL[selected_vps_index]
        vps_busy_status[selected_vps_index] = True
        
        logger.info(f"Routing job {job_id} to VPS {selected_vps_index + 1} ({vps_config['url']})")
        
        comfy_client = ComfyUIClient(vps_config['url'])
        
        if job_id in job_results:
            job_results[job_id].update({"status": "processing", "progress": 0})
        else:
            job_results[job_id] = {"status": "processing", "progress": 0, "user_id": job_data['user_id']}
        
        try:
            # 1. Load Workflow
            workflow_path = f"workflows/{job_data['workflow_file']}"
            if not os.path.exists(workflow_path):
                raise Exception(f"Workflow file {job_data['workflow_file']} not found")
                
            with open(workflow_path, "r") as f:
                workflow = json.load(f)

            # 2. Map Frontend Data to Workflow Nodes
            logger.info(f"Mapping job data to workflow: {job_data}")
            
            user_prompt = job_data.get('prompt', '')
            workflow_file = job_data.get('workflow_file', '')
            
            # --- STRATEGY A: Hardcoded Node Mapping (The "Absolute" Way) ---
            # This is the most reliable way as it uses exact node IDs.
            HARDCODED_MAPS = {
                "img2vid.json": {
                    "positive_nodes": [("267:266", "value"), ("267:240", "text")], # Fill both primitive and encode
                    "negative_nodes": [("267:247", "text")],
                    "image_nodes": [("269", "image")],
                    "seed_nodes": [("267:216", "noise_seed"), ("267:237", "noise_seed"), ("267:274", "sampling_mode.seed")]
                },
                "txt2vid.json": {
                    "positive_nodes": [("267:266", "value"), ("267:240", "text")],
                    "negative_nodes": [("267:247", "text")],
                    "image_nodes": [("269", "image")], # Backup mapping
                    "seed_nodes": [("267:216", "noise_seed"), ("267:237", "noise_seed"), ("267:274", "sampling_mode.seed")]
                },
                "txt2img.json": {
                    "positive_nodes": [("57:27", "text")],
                    "seed_nodes": [("57:3", "seed")]
                },
                "image_gen.json": {
                    "positive_nodes": [("68:6", "text"), ("433:111", "text"), ("435", "value"), ("435", "text")], # Handle both value and text keys
                    "image_nodes": [("46", "image"), ("68:29", "image")],
                    "seed_nodes": [("68:25", "noise_seed")]
                }
            }
            
            applied_via_hardcoded = False
            if workflow_file in HARDCODED_MAPS:
                m = HARDCODED_MAPS[workflow_file]
                # Apply Positive Prompt
                for nid, nkey in m.get("positive_nodes", []):
                    if nid in workflow and "inputs" in workflow[nid]:
                        workflow[nid]["inputs"][nkey] = user_prompt
                        applied_via_hardcoded = True
                        logger.info(f"Hardcoded: Applied prompt to {nid}:{nkey}")
                
                # Apply Negative Prompt (Clear it)
                for nid, nkey in m.get("negative_nodes", []):
                    if nid in workflow and "inputs" in workflow[nid]:
                        workflow[nid]["inputs"][nkey] = ""
                        logger.info(f"Hardcoded: Cleared negative prompt at {nid}:{nkey}")

            # --- STRATEGY B: Placeholder Replacement Strategy (Recursive) ---
            # We recursively search for these specific strings and replace them (REPLACE ALL)
            POSITIVE_PLACEHOLDER = "[POSITIVE_PROMPT]"
            NEGATIVE_PLACEHOLDER = "[NEGATIVE_PROMPT]"
            
            def recursive_replace_all(obj, search, replace):
                count = 0
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(v, (dict, list)):
                            count += recursive_replace_all(v, search, replace)
                        elif isinstance(v, str) and v == search:
                            obj[k] = replace
                            count += 1
                elif isinstance(obj, list):
                    for i, v in enumerate(obj):
                        if isinstance(v, (dict, list)):
                            count += recursive_replace_all(v, search, replace)
                        elif isinstance(v, str) and v == search:
                            obj[i] = replace
                            count += 1
                return count

            replaced_pos = recursive_replace_all(workflow, POSITIVE_PLACEHOLDER, user_prompt)
            replaced_neg = recursive_replace_all(workflow, NEGATIVE_PLACEHOLDER, "")

            if replaced_pos > 0:
                logger.info(f"Placeholder: Replaced {replaced_pos} [POSITIVE_PROMPT] tags.")
            if replaced_neg > 0:
                logger.info(f"Placeholder: Replaced {replaced_neg} [NEGATIVE_PROMPT] tags.")

            # --- STRATEGY C: FALLBACK (Aggressive Search) ---
            # We run this even if Strategy A/B partially worked, to catch secondary prompt nodes.
            if True: # Always run fallback search to be absolutely sure
                logger.info(f"Running aggressive fallback search for {workflow_file}")
                
                # Special brute force for image_gen if we can't find the nodes the user mentioned
                # If there's a hardcoded "snowy mountain" or "sitting on a rock" prompt, we MUST find and replace it
                def brute_force_replace_prompt(obj, target_prompt):
                    c = 0
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if isinstance(v, str):
                                # If the string is long and contains keywords or exactly matches user's problematic prompt
                                if len(v) > 50 and any(kw in v.lower() for kw in ["sitting", "rock", "snowy", "mountain", "freckles", "green eyes"]):
                                    obj[k] = target_prompt
                                    c += 1
                                    logger.info(f"Brute Force: Replaced suspicious prompt string in key {k}")
                            elif isinstance(v, (dict, list)):
                                c += brute_force_replace_prompt(v, target_prompt)
                    elif isinstance(obj, list):
                        for i, v in enumerate(obj):
                            if isinstance(v, str):
                                if len(v) > 50 and any(kw in v.lower() for kw in ["sitting", "rock", "snowy", "mountain", "freckles", "green eyes"]):
                                    obj[i] = target_prompt
                                    c += 1
                                    logger.info(f"Brute Force: Replaced suspicious prompt string in list at index {i}")
                            elif isinstance(v, (dict, list)):
                                c += brute_force_replace_prompt(v, target_prompt)
                    return c

                brute_force_replace_prompt(workflow, user_prompt)

                if workflow_file == 'image_gen.json' or workflow_file == 'txt2img.json':
                    # Aggressive for Flux/SDXL
                    for node_id, node in workflow.items():
                        if "inputs" in node:
                            class_type = str(node.get("class_type", ""))
                            title = str(node.get("_meta", {}).get("title", "") if node.get("_meta") else "").lower()
                            # If it's a prompt node or looks like one
                            if any(kw in class_type.lower() or kw in title for kw in ["prompt", "cliptext", "conditioning", "flux", "textto", "ltx", "instruct"]):
                                for input_key, input_val in node["inputs"].items():
                                    if isinstance(input_val, str) and input_key not in ["vae_name", "model_name", "ckpt_name", "lora_name", "clip_name", "unet_name"]:
                                        if not any(input_val.lower().endswith(ext) for ext in [".safetensors", ".ckpt", ".pt", ".bin", ".png", ".jpg", ".jpeg", ".mp4", ".yaml"]):
                                            node["inputs"][input_key] = user_prompt
                                            logger.info(f"Aggressive Search: Updated node {node_id} input {input_key}")
                else:
                    # Standard fallback mapping
                    for node_id, node in workflow.items():
                        if "inputs" in node:
                            class_type = str(node.get("class_type", ""))
                            title = str(node.get("_meta", {}).get("title", "") if node.get("_meta") else "").lower()
                            is_likely_pos = ("prompt" in title or "positive" in title or "ltxv" in class_type.lower()) and class_type in ["CLIPTextEncode", "PrimitiveString", "PrimitiveStringMultiline", "LTXVConditioning", "TextGenerateLTX2Prompt"]
                            if is_likely_pos:
                                for k in ["text", "value", "prompt", "string"]:
                                    if k in node["inputs"] and isinstance(node["inputs"][k], str):
                                        node["inputs"][k] = user_prompt
                                        logger.info(f"Aggressive Search: Updated node {node_id}")

            # --- ALWAYS ENSURE NEGATIVE PROMPTS ARE CLEARED (Safety) ---
            for node_id, node in workflow.items():
                if "inputs" in node:
                    title = str(node.get("_meta", {}).get("title", "") if node.get("_meta") else "").lower()
                    if "negative" in title:
                        for k in ["text", "value", "prompt", "string"]:
                            if k in node["inputs"] and isinstance(node["inputs"][k], str):
                                if node["inputs"][k] != "": # Only log if actually changing
                                    node["inputs"][k] = ""
                                    logger.info(f"Safety: Cleared negative text in node {node_id}")

            # 2b. Image Mapping
            if job_data.get("input_file"):
                image_applied = False
                upload_res = comfy_client.upload_image(job_data["input_file"])
                if upload_res and "name" in upload_res:
                    comfy_filename = upload_res["name"]
                    
                    # Check Hardcoded Image Mapping
                    if workflow_file in HARDCODED_MAPS:
                        m = HARDCODED_MAPS[workflow_file]
                        for nid, nkey in m.get("image_nodes", []):
                            if nid in workflow and "inputs" in workflow[nid]:
                                workflow[nid]["inputs"][nkey] = comfy_filename
                                image_applied = True
                                logger.info(f"Hardcoded: Applied image to {nid}:{nkey}")
                    
                    # Fallback Image Mapping (Searching for LoadImage nodes)
                    if not image_applied:
                        for node_id, node in workflow.items():
                            if "inputs" in node:
                                class_type = node.get("class_type", "")
                                if class_type in ["LoadImage", "Load Image"]:
                                    if "image" in node["inputs"]:
                                        node["inputs"]["image"] = comfy_filename
                                        image_applied = True
                                        logger.info(f"Fallback: Applied image to node {node_id} ({class_type})")
                        
                        if not image_applied:
                            # Last resort: any node with string "image" input ending in png/jpg
                            for node_id, node in workflow.items():
                                if "inputs" in node and "image" in node["inputs"] and isinstance(node["inputs"]["image"], str):
                                    node["inputs"]["image"] = comfy_filename
                                    image_applied = True
                                    logger.info(f"Deep Fallback: Applied image to node {node_id}")
                else:
                    logger.error("Failed to upload image to ComfyUI")

            # 2c. Seed Mapping
            new_seed = random.randint(0, 10**15)
            seed_applied = False
            
            # Check Hardcoded Seed Mapping
            if workflow_file in HARDCODED_MAPS:
                m = HARDCODED_MAPS[workflow_file]
                for nid, nkey in m.get("seed_nodes", []):
                    if nid in workflow and "inputs" in workflow[nid]:
                        workflow[nid]["inputs"][nkey] = new_seed
                        seed_applied = True
                        logger.info(f"Hardcoded Seed: node {nid} key {nkey} set to {new_seed}")
            
            # Global Seed fallback (Apply to anything that looks like a seed)
            for node_id, node in workflow.items():
                if "inputs" in node:
                    for s_key in ["seed", "noise_seed", "sampling_mode.seed"]:
                        if s_key in node["inputs"] and isinstance(node["inputs"][s_key], (int, float)):
                            node["inputs"][s_key] = new_seed
                            seed_applied = True
            logger.info(f"Applied seed {new_seed} (Applied: {seed_applied})")

            # 2d. Resolution Mapping
            res_map = {
                "480p": (852, 480), # LTX often uses 852x480
                "720p": (1280, 720),
                "1080p": (1920, 1080),
                "512x512": (512, 512)
            }
            w, h = res_map.get(job_data.get('resolution', '1080p'), (852, 480))
            megapixels = (w * h) / 1000000.0
            
            # Apply Aspect Ratio
            if job_data.get('aspect_ratio') == '9:16':
                w, h = h, w
                logger.info(f"Swapping dimensions for 9:16 aspect ratio: {w}x{h}")

            for node_id, node in workflow.items():
                if "inputs" in node:
                    # Standard width/height (only if they are raw numbers, not links)
                    if "width" in node["inputs"] and isinstance(node["inputs"]["width"], (int, float)):
                        node["inputs"]["width"] = w
                    if "height" in node["inputs"] and isinstance(node["inputs"]["height"], (int, float)):
                        node["inputs"]["height"] = h
                    
                    # Megapixels for scaling nodes
                    if "megapixels" in node["inputs"] and isinstance(node["inputs"]["megapixels"], (int, float)):
                        if workflow_file != 'image_gen.json': # Avoid messing with Flux 2 scaling which is sensitive
                            node["inputs"]["megapixels"] = megapixels
                            logger.info(f"Applied megapixels {megapixels} to node {node_id}")
                    
                    # LTX Primitive nodes for Width/Height
                    if node.get("class_type") == "PrimitiveInt":
                        title = str(node.get("_meta", {}).get("title", "") if node.get("_meta") else "")
                        if title == "Width":
                            node["inputs"]["value"] = w
                        elif title == "Height":
                            node["inputs"]["value"] = h

            # 2e. Duration Mapping
            if job_data['type'] == 'video':
                # Assuming 25fps for LTX workflows
                dur_map = {"5s": 125, "10s": 250, "15s": 375, "20s": 500}
                frames = dur_map.get(job_data['duration'], 125)
                for node_id, node in workflow.items():
                    if "inputs" in node:
                        if "batch_size" in node["inputs"] and node.get("class_type") == "EmptyLatentImage":
                            node["inputs"]["batch_size"] = frames
                        if "frame_count" in node["inputs"]:
                            node["inputs"]["frame_count"] = frames
                        
                        # LTX Primitive node for Length
                        if node.get("class_type") == "PrimitiveInt" and node.get("_meta", {}).get("title") == "Length":
                            node["inputs"]["value"] = frames
                            logger.info(f"Applied length {frames} to LTX Primitive node {node_id}")
            else:
                # Image Batch Size (Enforced to 1)
                for node_id, node in workflow.items():
                    if "inputs" in node:
                        class_type = node.get("class_type", "")
                        if "batch_size" in node["inputs"] and class_type in ["EmptyLatentImage", "EmptySD3LatentImage", "EmptyFluxLatentImage", "EmptyFlux2LatentImage"]:
                            node["inputs"]["batch_size"] = 1
                            logger.info(f"Enforced batch_size 1 for node {node_id} ({class_type})")

            # 2f. T2V/I2V Switch (Specific for LTX workflows)
            for node_id, node in workflow.items():
                if node.get("class_type") == "PrimitiveBoolean" and node.get("_meta", {}).get("title") == "Switch to Text to Video?":
                    is_t2v = job_data.get("subType") == "text-to-video"
                    node["inputs"]["value"] = is_t2v
                    logger.info(f"Set T2V switch to {is_t2v} for node {node_id}")

            # 3. Run Workflow
            results = await comfy_client.run_workflow(workflow, job_id)
            
            if results:
                public_urls = []
                for idx, (result_data, mime_type) in enumerate(results):
                    # Determine extension based on mime_type
                    if "video/mp4" in mime_type:
                        ext = "mp4"
                    elif "image/gif" in mime_type:
                        ext = "gif"
                    else:
                        ext = "png"
                    
                    filename = f"{job_id}_{idx}.{ext}"
                    
                    # Try to upload to Supabase first
                    public_url = upload_to_supabase(result_data, filename, mime_type)
                    
                    if not public_url:
                        # Fallback to local file if Supabase fails or credentials missing
                        filepath = os.path.join(OUTPUT_DIR, filename)
                        with open(filepath, "wb") as f:
                            f.write(result_data)
                        
                        # For ngrok/VPS, this would be your public IP or domain
                        domain = os.getenv('DOMAIN', 'mite-next-grouper.ngrok-free.app')
                        public_url = f"https://{domain}/outputs/{filename}"
                    
                    public_urls.append(public_url)
                
                # 4. Save to Supabase Database directly from worker (save all generated results)
                user_id = job_data.get("user_id")
                if user_id and SUPABASE_URL and SUPABASE_KEY:
                    try:
                        db_url = f"{SUPABASE_URL}/rest/v1/projects"
                        db_headers = {
                            "Authorization": f"Bearer {SUPABASE_KEY}",
                            "apikey": SUPABASE_KEY,
                            "Content-Type": "application/json",
                            "Prefer": "return=minimal"
                        }
                        
                        for url in public_urls:
                            project_data = {
                                "user_id": user_id,
                                "type": job_data["type"],
                                "sub_type": job_data.get("subType", ""),
                                "prompt": job_data["prompt"],
                                "url": url,
                                "thumbnail_url": url,
                                "created_at": datetime.now(timezone.utc).isoformat()
                            }
                            # Use timezone-aware UTC datetime for Supabase
                            expires_iso = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                            project_data["expires_at"] = expires_iso
                            
                            logger.info(f"Attempting to save project to DB: {project_data}")
                            
                            db_res = requests.post(db_url, headers=db_headers, json=project_data)
                            if db_res.status_code >= 300:
                                logger.error(f"Failed to save project to DB: {db_res.status_code} - {db_res.text}")
                            else:
                                logger.info(f"Project saved successfully to DB for URL: {url}")
                    except Exception as db_err:
                        logger.error(f"Error saving to DB: {str(db_err)}")

                # 5. Update job status
                job_results[job_id].update({
                    "status": "completed",
                    "url": public_urls[0],
                    "urls": public_urls,
                    "filenames": [f"{job_id}_{idx}.{ext}" for idx, _ in enumerate(results)]
                })
                logger.info(f"Job {job_id} completed successfully with {len(public_urls)} results")
            else:
                job_results[job_id].update({
                    "status": "failed",
                    "error": "No output from ComfyUI"
                })
                logger.error(f"Job {job_id} failed: No output from ComfyUI")

        except Exception as e:
            logger.error(f"Job {job_id} failed: {str(e)}")
            if job_id in job_results:
                job_results[job_id].update({
                    "status": "failed",
                    "error": str(e)
                })
        
        finally:
            vps_busy_status[selected_vps_index] = False
            job_queue.task_done()

# --- Background Task: Cleanup Old Jobs ---
async def cleanup_task():
    """Deletes jobs and files older than 1 hour from Supabase and local storage."""
    while True:
        try:
            logger.info("Running cleanup task...")
            now_ts = time.time()
            one_hour_ago_ts = now_ts - 3600
            now_iso = datetime.utcnow().isoformat()
            
            # 1. Cleanup Supabase Database
            if SUPABASE_URL and SUPABASE_KEY:
                # Delete rows where expires_at < now
                db_url = f"{SUPABASE_URL}/rest/v1/projects?expires_at=lt.{now_iso}"
                db_headers = {
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json"
                }
                try:
                    requests.delete(db_url, headers=db_headers)
                except Exception as e:
                    logger.error(f"Supabase DB cleanup error: {e}")
            
            # 2. Cleanup Local Files (Outputs)
            if os.path.exists(OUTPUT_DIR):
                for f in os.listdir(OUTPUT_DIR):
                    fpath = os.path.join(OUTPUT_DIR, f)
                    if os.path.isfile(fpath) and os.path.getmtime(fpath) < one_hour_ago_ts:
                        os.remove(fpath)
                        logger.info(f"Deleted old local output: {f}")
            
            # 3. Cleanup Inputs
            if os.path.exists("inputs"):
                for f in os.listdir("inputs"):
                    fpath = os.path.join("inputs", f)
                    if os.path.isfile(fpath) and os.path.getmtime(fpath) < one_hour_ago_ts:
                        os.remove(fpath)
                        logger.info(f"Deleted old input file: {f}")
            
            # 4. Cleanup job_results
            jobs_to_delete = []
            for j_id, j_res in list(job_results.items()):
                # Delete jobs older than 2 hours or completed/failed jobs older than 30 mins
                created_at = j_res.get("created_at", 0)
                status = j_res.get("status")
                
                if created_at < (now_ts - 7200): # 2 hours
                    jobs_to_delete.append(j_id)
                elif status in ["completed", "failed"] and created_at < (now_ts - 1800): # 30 mins
                    jobs_to_delete.append(j_id)
            
            for j_id in jobs_to_delete:
                if j_id in job_results:
                    del job_results[j_id]
                    logger.info(f"Cleaned up job_results for job {j_id}")

        except Exception as e:
            logger.error(f"General cleanup error: {e}")
        
        await asyncio.sleep(600) # Run every 10 minutes

# Start multiple workers to handle parallel VPS processing
@app.on_event("startup")
async def startup_event():
    # Start 5 workers to handle multiple VPS requests in parallel
    for _ in range(5):
        asyncio.create_task(worker())
    asyncio.create_task(cleanup_task())

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    """Serves a file with Content-Disposition: attachment to force download."""
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    from fastapi.responses import FileResponse
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type='application/octet-stream',
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.post("/api/generate")
async def generate(
    prompt: str = Form(...),
    duration: Optional[str] = Form(None),
    resolution: Optional[str] = Form(None),
    aspect_ratio: Optional[str] = Form('16:9'),
    type: str = Form(...),
    subType: Optional[str] = Form(None),
    quality: Optional[str] = Form(None),
    count: Optional[int] = Form(1),
    user_id: str = Form(...),
    file: Optional[UploadFile] = File(None)
):
    # Check if user already has an active job
    for j_id, j_res in job_results.items():
        if j_res.get("user_id") == user_id and j_res.get("status") in ["queued", "processing"]:
            raise HTTPException(status_code=400, detail="You already have a generation in progress. Please wait until it's finished.")

    job_id = str(uuid.uuid4())
    
    # Determine which workflow file to use
    workflow_file = "image_gen.json"
    if type == "image":
        workflow_file = "txt2img.json" if subType == "text-to-image" else "image_gen.json"
    elif type == "video":
        workflow_file = "txt2vid.json" if subType == "text-to-video" else "img2vid.json"
    
    job_data = {
        "prompt": prompt,
        "duration": duration,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "quality": quality,
        "count": count,
        "type": type,
        "subType": subType,
        "workflow_file": workflow_file,
        "user_id": user_id # Pass user_id to worker
    }
    
    # If file uploaded, save it for ComfyUI to use
    if file:
        input_path = f"inputs/{job_id}_{file.filename}"
        os.makedirs("inputs", exist_ok=True)
        with open(input_path, "wb") as f:
            f.write(await file.read())
        job_data["input_file"] = input_path

    await job_queue.put((job_id, job_data))
    job_results[job_id] = {
        "status": "queued", 
        "user_id": user_id,
        "created_at": time.time()
    }
    
    # Return immediately with job_id to avoid timeout
    return {"job_id": job_id, "status": "queued"}

@app.get("/api/job_status/{job_id}")
async def get_job_status(job_id: str):
    if job_id not in job_results:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_results[job_id]

# Serve output files
from fastapi.staticfiles import StaticFiles
app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
