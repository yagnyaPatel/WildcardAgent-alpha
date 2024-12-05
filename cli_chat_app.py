import asyncio
import websockets
import json
import uuid
import webbrowser
import ssl
import certifi
import os
from typing import Optional
from enum import Enum
import dotenv

DEBUG = False
dotenv.load_dotenv()

class MessageType(Enum):
    AI = "ai"
    CHAT = "chat"
    TOOL = "tool"
    HUMAN = "human"

class ChatClient:
    def __init__(self):
        self.server_url = os.getenv("SERVER_URL", "").replace("https:", "wss:")
        self.ws_url = f"{self.server_url}/ws/"
        self.thread_id = str(uuid.uuid4())
        self._is_waiting = False
        self.in_oauth_flow = False  # Flag to track OAuth flow state
        self.loading_symbols = ["⌛", "⏳", "⌛", "⏳"]  # Loading hourglass symbols
        self.loading_index = 0

    @property
    def is_waiting(self) -> bool:
        return self._is_waiting

    @is_waiting.setter
    def is_waiting(self, value: bool):
        self._is_waiting = value

    def clear_line(self):
        print("\r" + " " * 60 + "\r", end="", flush=True)

    async def handle_event(self, websocket, message: str):
        try:
            data = json.loads(message)
            event = data.get("event")
            event_data = data.get("data", {})

            if event == "start_oauth_flow":
                self.in_oauth_flow = True  # Entering OAuth flow
                authorization_url = event_data.get("authorization_url")
                if authorization_url:
                    print("\n\n🔐 [OAuth Required]\n")
                    print(f"Please authorize by visiting: {authorization_url}\n")
                    webbrowser.open(authorization_url)
                    # During OAuth flow, set is_waiting to True to prevent prompts
                    self.is_waiting = True

            elif event == "end_oauth_flow":
                self.in_oauth_flow = False  # Exiting OAuth flow
                print("\n🎉 [Authentication Successful] Resuming chat...\n")
                resume_data = event_data.get("data", {})
                await websocket.send(json.dumps({
                    "event": "resume_execution",
                    "data": resume_data
                }))
                # After sending resume_execution, set is_waiting to True to wait for server response
                self.is_waiting = True

            elif event == "error":
                error_msg = event_data.get("error", "Unknown error.")
                print(f"\n❌ Error: {error_msg}\n")
                # On error, reset is_waiting to allow user to input again
                self.is_waiting = False

            else:
                messages = data.get("messages", [])
                ai_messages = [
                    msg for msg in messages 
                    if msg.get("type") == MessageType.AI.value
                ]
                for msg in ai_messages:
                    content = msg.get("content", "").strip()
                    tool_calls = msg.get("additional_kwargs", {}).get("tool_calls", [])
                    
                    if tool_calls:
                        for call in tool_calls:
                            function = call.get("function", {})
                            name = function.get("name")
                            args = function.get("arguments", "{}")
                            try:
                                formatted_args = json.dumps(json.loads(args), indent=2)
                                if DEBUG == True:
                                    print(f"\n\n🔧 Assistant is executing: {name}")
                                    print(f"   with arguments:\n{formatted_args}\n")
                            except json.JSONDecodeError:
                                if DEBUG == True:
                                    print(f"\n\n🔧 Assistant is executing: {name}\n")
                    
                    if content:
                        print(f"\n\n🤖 Assistant: {content}\n")
                # After processing AI messages, reset is_waiting
                self.is_waiting = False

        except json.JSONDecodeError:
            print("\n❌ Error: Received invalid JSON data.\n")
            self.is_waiting = False

    async def send_message(self, websocket, message: str):
        self.is_waiting = True
        payload = {"message": message}
        await websocket.send(json.dumps(payload))

    async def listen_messages(self, websocket):
        try:
            async for message in websocket:
                await self.handle_event(websocket, message)
        except asyncio.CancelledError:
            pass  # Handle task cancellation gracefully

    async def display_loading(self):
        self.clear_line()
        symbol = self.loading_symbols[self.loading_index % len(self.loading_symbols)]
        print(f"\r{symbol} Waiting for assistant's response...", end="", flush=True)
        self.loading_index += 1
        await asyncio.sleep(0.5)  # Adjusted sleep for smoother animation

    async def run(self):
        print(f"\n\n🚀 Starting chat session with thread_id: {self.thread_id}\n")
        uri = f"{self.ws_url}{self.thread_id}"

        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            async with websockets.connect(uri=uri, ssl=ssl_context) as websocket:
                print("✨ Connected! You can start typing your messages. To exit, type 'exit'.\n")
                listen_task = asyncio.create_task(self.listen_messages(websocket))

                while True:
                    if not self.is_waiting and not self.in_oauth_flow:
                        self.clear_line()
                        user_input = await asyncio.get_event_loop().run_in_executor(
                            None, input, "👤 You: "
                        )
                        
                        if user_input.strip().lower() == 'exit':
                            print("\n👋 Exiting chat... Bye!\n")
                            listen_task.cancel()
                            await websocket.close()
                            break
                        
                        if not user_input.strip():
                            print("\nPlease enter a message.\n")
                            continue
                        
                        await self.send_message(websocket, user_input)
                    else:
                        await self.display_loading()

        except Exception as e:
            print(f"\n❌ Failed to connect to WebSocket: {e}\n")

def main():
    client = ChatClient()
    asyncio.run(client.run())

if __name__ == "__main__":
    main()