from utils.ConnectionManager import ConnectionManager
from agent import get_agent

from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin
from pydantic import BaseModel
import json
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.messages import BaseMessage, ChatMessage
from langgraph.graph.graph import CompiledGraph


from wildcard_core import ToolSearchClient
from wildcard_core.auth.oauth_helper import OAuthCredentialsRequiredInfo
from wildcard_core.events.types import WebhookOAuthCompletion, WebhookRequest, WildcardEvent, OAuthCompletionData
from wildcard_core.tool_search.utils.api_service import APIService
from wildcard_langgraph import DynamicToolSelectState

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Thread ID -> (agent, initial_state, tool_search_client)
agentMap: Dict[str, Tuple[CompiledGraph, DynamicToolSelectState, ToolSearchClient]] = {} 

# Initialize ConnectionManager
manager = ConnectionManager()

class RunAgentRequest(BaseModel):
    thread_id: str
    next_messages: List[ChatMessage]
    additional_params: Dict[str, Any] = {}

class RunAgentResponse(BaseModel):
    messages: List[BaseMessage]
    wildcard_event: Optional[Dict[WildcardEvent, Any]]

def register_new_agent(thread_id: str):
    agent, initial_state, tool_search_client = get_agent()
    agentMap[thread_id] = (agent, initial_state, tool_search_client)

def find_agent_info(thread_id: str, allow_register: bool = False):
    agent_info = agentMap.get(thread_id, None)
    if agent_info is None and allow_register:
        register_new_agent(thread_id)
        agent_info = agentMap[thread_id]
    elif agent_info is None:
        raise Exception(f"Agent info not found for thread_id: {thread_id}")
       
    return agent_info

async def process_agent_request(request: RunAgentRequest) -> RunAgentResponse:
    config = {"configurable": {"thread_id": request.thread_id}}
    resuming_interrupt = request.additional_params.get("resuming_interrupt", False)
    state = None
    
    agent, initial_state, tool_search_client = find_agent_info(request.thread_id, allow_register=True)

    print(f"TOOL SEARCH CLIENT:", tool_search_client)

    state_snapshot = await agent.aget_state(config)
    print(f"State snapshot:", state_snapshot)

    if "messages" not in state_snapshot.values:
        print("No messages found in state snapshot. Using initial state.")
        state = initial_state
        print(f"AFTER UPDATING INITIAL STATE:", state)
    elif resuming_interrupt:
        print("Resuming interrupt")
        state_history = agent.aget_state_history(config)
        all_states = [state async for state in state_history]
        
        print(f"All states:", all_states)
        await agent.aupdate_state(config, {"tool_search_client": tool_search_client})
        state = None
        
    else:
        state = {**state_snapshot.values}

    print(f"State BEFORE stream:", state)

    async def run_agent(next_state_payload, _state, _config):
        print("RUN AGENT - CONFIG", _config)

        async def stream_agent_messages(_next_state_payload, _state, _config):
            messages = []
            async for s in agent.astream(_next_state_payload, _config, stream_mode="values"):
                msg = dict(s).get("messages", [])
                if msg:
                    messages.append(msg[-1])
                    msg[-1].pretty_print()

            response_state = await agent.aget_state(_config)
            return messages, response_state

        _new_messages, _response_state = await stream_agent_messages(next_state_payload, _state, _config)

        # Handle interrupts
        for task in _response_state.tasks:
            if not task.interrupts:
                continue
            for interrupt in task.interrupts:
                if isinstance(interrupt.value, OAuthCredentialsRequiredInfo):
                    print("Initiating OAuth flow for", interrupt.value)
                    authorization_url = await tool_search_client.initiate_oauth(
                        flows=interrupt.value.flows,
                        api_service=interrupt.value.api_service,
                        required_scopes=interrupt.value.required_scopes,
                        webhook_url=join_url_parts(
                            settings.serverUrl,
                            app.url_path_for("agent_webhook", thread_id=request.thread_id)
                        )
                    )

                    await manager.send_message(
                        request.thread_id,
                        json.dumps({
                            "event": WildcardEvent.START_OAUTH_FLOW,
                            "data": {
                                "flow_type": "authorizationCode",
                                "authorization_url": authorization_url,
                            }
                        })
                    )

                    return RunAgentResponse(
                        messages=_new_messages,
                        wildcard_event=None
                    )

        return RunAgentResponse(
            messages=_new_messages,
            wildcard_event=None
        )

    # final_state = state if not resuming_interrupt else None
    final_payload = {**state, "messages": request.next_messages} if not resuming_interrupt else None

    return await run_agent(final_payload, state, config)

@app.get("/health")
async def health():
    return JSONResponse({"message": "Agent service is healthy."})

@app.post("/webhook/{thread_id}")
async def agent_webhook(request: WebhookRequest[Any], thread_id: str):
    """
    Handle webhook callbacks from the auth_service.
    """
    _, _, tool_search_client = find_agent_info(thread_id)
    print(f"CALLBACK REQUEST: {request}")
    if request.event == WildcardEvent.END_OAUTH_FLOW:
        oauth_completion = WebhookOAuthCompletion(
            event=request.event,
            data=OAuthCompletionData(**request.data)
        )
        tool_search_client.handle_webhook_callback(oauth_completion.data)

        print("UPDATED CLIENT:", tool_search_client)

        # Notify the client via WebSocket about the resume execution
        if thread_id in manager.active_connections:
            await manager.send_message(thread_id, json.dumps({
                "event": WildcardEvent.END_OAUTH_FLOW,
                "data": {
                    "next_messages": [],
                    "additional_params": {"resuming_interrupt": True}
                }
            }))

        return {"status": "success"}
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported event: {request.event}")

@app.websocket("/ws/{thread_id}")
async def websocket_endpoint(websocket: WebSocket, thread_id: str):
    await manager.connect(thread_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            print(f"Received from {thread_id}: {data}")
            try:
                event = data.get("event", None)
                if event is None:
                    # Assume it's a user message
                    user_message = data.get("message")
                    if not user_message:
                        await manager.send_message(thread_id, json.dumps({"event": "error", "data": {"error": "No message provided."}}))
                        continue

                    # Create RunAgentRequest
                    run_request = RunAgentRequest(
                        thread_id=thread_id,
                        next_messages=[{"role": "user", "content": user_message}],
                        additional_params={}
                    )

                    # Process the agent request and send back the response
                    response = await process_agent_request(run_request)
                    await manager.send_message(thread_id, response.model_dump_json())
                elif event == "resume_execution":
                    run_request = RunAgentRequest(
                        thread_id=thread_id,
                        next_messages= data.get("data", {}).get("next_messages", []),
                        additional_params={"resuming_interrupt": True}
                    )
                    response = await process_agent_request(run_request)
                    await manager.send_message(thread_id, response.model_dump_json())
                
                else:
                    raise HTTPException(status_code=400, detail=f"Unsupported event: {data['event']}")
                    
            except json.JSONDecodeError:
                await manager.send_message(thread_id, json.dumps({"event": "error", "data": {"error": "Invalid JSON format."}}))
            except Exception as e:
                await manager.send_message(thread_id, json.dumps({"event": "error", "data": {"error": str(e)}}))
    except WebSocketDisconnect:
        manager.disconnect(thread_id)

def join_url_parts(base_url: str, *parts: str) -> str:
    """
    Joins a base URL with multiple path parts using urljoin.
    
    Args:
        base_url: The base URL (e.g., "https://api.example.com")
        *parts: Variable number of path parts to join
    
    Returns:
        Complete URL with all parts joined correctly
        
    Example:
        >>> join_url_parts("https://api.example.com", "/api", "/v1/", "/users")
        'https://api.example.com/api/v1/users'
    """
    # Ensure base_url ends with slash for proper urljoin behavior
    url = base_url if base_url.endswith('/') else f"{base_url}/"
    
    # Join all parts, ensuring each part is properly stripped
    for part in parts:
        if part:
            # Remove leading/trailing slashes for consistency
            cleaned_part = part.strip('/')
            if cleaned_part:
                url = urljoin(url, cleaned_part + '/')
    
    return url.rstrip('/')  # Remove trailing slash from final URL

class Settings:
    serverUrl = os.getenv("SERVER_URL")
    wsUrl = join_url_parts(serverUrl, "agent", "ws")

settings = Settings()