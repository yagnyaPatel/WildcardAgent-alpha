import asyncio
import websockets
import json
import uuid
import webbrowser
import ssl
import certifi
import os
from typing import Optional
import dotenv
import time
import sys
from enum import Enum

dotenv.load_dotenv()

# Generate a unique thread_id
def generate_thread_id():
    return str(uuid.uuid4())

# Configuration
serverUrl = os.getenv("SERVER_URL")
serverUrl = serverUrl.replace("https:", "wss:")
wsUrl = str.join("/", [serverUrl, "ws/"])

# Global flag to track if we're waiting for a response
waiting_for_response = False

# Handle Incoming Events
async def handle_event(websocket, message: str):
    global waiting_for_response
    try:
        data = json.loads(message)
        event = data.get("event")
        event_data = data.get("data", {})

        if event == "start_oauth_flow":
            authorization_url = event_data.get("authorization_url")
            if authorization_url:
                print("\n[OAuth Required]")
                print(f"Please authorize by visiting: {authorization_url}\n")
                webbrowser.open(authorization_url)
        elif event == "end_oauth_flow":
            print("\n[Resuming Execution]")
            resume_data = event_data.get("data", {})
            await websocket.send(json.dumps({
                "event": "resume_execution",
                "data": resume_data
            }))
        elif event == "error":
            error_msg = event_data.get("error", "Unknown error.")
            print(f"\n[Error]: {error_msg}\n")
            waiting_for_response = False
        else:
            # Assuming any other event is a response message
            messages = data.get("messages", [])
            filtered_messages = [msg for msg in messages if msg.get("type") == MessageType.AI.value]
            filtered_messages = [msg for msg in filtered_messages if len(msg.get("tool_calls", [])) == 0]
            for msg in filtered_messages:
                print(f"\n[Agent]: {msg.get('content')}\n")
            waiting_for_response = False
    except json.JSONDecodeError:
        print("\n[Error]: Received invalid JSON data.\n")
        waiting_for_response = False

# Send Message to WebSocket
async def send_message(websocket, message: str):
    global waiting_for_response
    payload = {
        "message": message
    }
    await websocket.send(json.dumps(payload))

    # typing indicator cli animation. clear line after 3 dots and continue on same line
    print("\r", end="", flush=True)
    for _ in range(3):
        print(".", end="", flush=True)
        await asyncio.sleep(0.5)
    print("\r", end="", flush=True)
    waiting_for_response = True

# Listen to WebSocket Messages
async def listen_messages(websocket):
    async for message in websocket:
        await handle_event(websocket, message)

# Main CLI Loop
async def main():
    thread_id = generate_thread_id()
    print(f"Starting chat session with thread_id: {thread_id}\n")

    uri = f"{wsUrl}{thread_id}"
    try:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        async with websockets.connect(uri=uri, ssl=ssl_context) as websocket:
            print("Connected! You can start typing your messages. To exit, type 'exit'.\n")

            # Start listening to incoming messages
            listen_task = asyncio.create_task(listen_messages(websocket))
            symbols = ["|", "/", "-", "\\"]
            i = 0

            while True:
                if not waiting_for_response:
                    user_input = await asyncio.get_event_loop().run_in_executor(None, input, "You: ")
                    if user_input.strip().lower() == 'exit':
                        print("Exiting chat...")
                        listen_task.cancel()
                        await websocket.close()
                        break
                    elif user_input.strip() == '':
                        print("please enter a message")
                        continue
                    else:
                        await send_message(websocket, user_input)
                else:
                    # Wait a bit before checking again if we can accept input
                    sys.stdout.write("\r" + symbols[i % 4] + " Waiting for response...")
                    sys.stdout.flush()
                    time.sleep(0.2)
                    i += 1

    except Exception as e:
        print(f"Failed to connect to WebSocket: {e}")

class MessageType(Enum):
    AI = "ai"
    CHAT = "chat"
    TOOL = "tool" # tool response from the api
    HUMAN = "human"

if __name__ == "__main__":
    asyncio.run(main())