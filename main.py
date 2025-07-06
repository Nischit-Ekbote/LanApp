import asyncio
import os
import sys
import json
import socket
import struct
from fastapi import FastAPI, WebSocket, UploadFile, File, Form, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import List
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse




try:
    import ssl  # Ensure ssl is available at import time
except ModuleNotFoundError as e:
    print("\n[ERROR] Your Python installation does not support SSL.\n"
          "Please reinstall Python with SSL support (OpenSSL required).\n")
    sys.exit(1)

clients: List[WebSocket] = []
UPLOAD_DIR = "shared_files"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Multicast settings for IGMP
MCAST_GRP = "224.1.1.1"
MCAST_PORT = 5007

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("", MCAST_PORT))
mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
sock.setblocking(False)

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(multicast_listener())
    yield

app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    clients.append(ws)
    try:
        while True:
            msg = await ws.receive_text()

            # Send message over multicast
            send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            send_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack('b', 1))
            send_sock.sendto(msg.encode(), (MCAST_GRP, MCAST_PORT))
    except:
        if ws in clients:
            clients.remove(ws)

@app.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...), sender: str = Form(...)):
    file_location = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_location, "wb") as f:
        content = await file.read()
        f.write(content)

    host_ip = request.client.host
    file_url = f"http://{host_ip}:8000/download/{file.filename}"
    message = json.dumps({
        "type": "file",
        "sender": sender,
        "filename": file.filename,
        "url": file_url
    })

    # Send file message over multicast
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    send_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack('b', 1))
    send_sock.sendto(message.encode(), (MCAST_GRP, MCAST_PORT))

    return {"status": "success", "filename": file.filename, "url": file_url}

@app.get("/files")
async def list_files():
    return os.listdir(UPLOAD_DIR)

@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename=filename)
    return {"error": "File not found"}

@app.get("/")
async def serve_frontend():
    with open("static/index.html", "r") as f:
        html = f.read()
    return HTMLResponse(content=html)


async def multicast_listener():
    loop = asyncio.get_event_loop()
    while True:
        try:
            data, addr = await loop.run_in_executor(None, sock.recvfrom, 1024)
            msg = data.decode()
            for client in clients:
                await client.send_text(msg)
        except:
            pass
        await asyncio.sleep(0.1)
