import asyncio
import websockets
import json
import uuid
import webbrowser
import ssl
import certifi
import os
from typing import Optional

# Generate a unique thread_id
def generate_thread_id():
    return str(uuid.uuid4())

# Configuration
class Settings:
    serverUrl = os.getenv("SERVER_URL").replace("https://", "")
    wsUrl = "wss://" + str.join("/", [serverUrl, "ws"])

settings = Settings()

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
            for msg in messages:
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
    print("[Message Sent Successfully]\n")
    waiting_for_response = True

# Listen to WebSocket Messages
async def listen_messages(websocket):
    async for message in websocket:
        await handle_event(websocket, message)

# Main CLI Loop
async def main():
    thread_id = generate_thread_id()
    print(f"Starting chat session with thread_id: {thread_id}\n")

    uri = f"{settings.wsUrl}{thread_id}"
    try:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        
        async with websockets.connect(uri=uri, ssl=ssl_context) as websocket:
            print("Connected to WebSocket. You can start typing your messages.\n")

            # Start listening to incoming messages
            listen_task = asyncio.create_task(listen_messages(websocket))

            while True:
                if not waiting_for_response:
                    user_input = await asyncio.get_event_loop().run_in_executor(None, input, "You: ")
                    if user_input.strip().lower() == 'exit':
                        print("Exiting chat...")
                        listen_task.cancel()
                        await websocket.close()
                        break
                    elif user_input.strip() == '':
                        continue
                    else:
                        await send_message(websocket, user_input)
                else:
                    # Wait a bit before checking again if we can accept input
                    await asyncio.sleep(0.1)

    except Exception as e:
        print(f"Failed to connect to WebSocket: {e}")

if __name__ == "__main__":
    asyncio.run(main())
