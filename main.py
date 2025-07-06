import asyncio
import socket
import struct
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

clients = []

MCAST_GRP = "224.1.1.1"
MCAST_PORT = 5007

# Create multicast socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('', MCAST_PORT))
mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
sock.setblocking(False)  # Needed for asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(multicast_listener())
    yield

app = FastAPI(lifespan=lifespan)

# Allow frontend (index.html) to connect
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

            # Send to LAN via multicast
            send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            send_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack('b', 1))
            send_sock.sendto(msg.encode(), (MCAST_GRP, MCAST_PORT))

    except:
        clients.remove(ws)

# Background task: listen for multicast messages and forward to browser clients
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
