import os
import uuid
import logging
from typing import Dict, Any, List

from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, ToolMessage, BaseMessage

from wildcard_core.tool_registry.tools.rest_api.types import ApiKeyAuthConfig, BearerAuthConfig, AuthType
from wildcard_core.tool_search.utils.api_service import APIService
from wildcard_langgraph import create_tool_selection_agent
from wildcard_core import ToolSearchClient


def get_agent():
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
    
    # Create the ToolSearchClient
    tool_search_client = ToolSearchClient(api_key='alpha-api-access')
    
    # Register necessary API authentications
    tool_search_client.register_api_auth(
        APIService.NEW_YORK_TIMES,
        ApiKeyAuthConfig(type=AuthType.API_KEY, key_value=os.getenv("NYT_API_KEY"))
    )
    tool_search_client.register_api_auth(
        APIService.SLACK, 
        BearerAuthConfig(type=AuthType.BEARER, token=os.getenv("SLACK_API_KEY"))
    )
    
    # Initialize the agent
    openai_api_key = os.getenv("OPENAI_API_KEY")
    model = ChatOpenAI(model="gpt-4o", temperature=0, api_key=openai_api_key)

    # Tweak this prompt to change the behavior of the agent
    task_system_prompt = """You are an autonomous personal assistant.
    """

    agent, initial_state = create_tool_selection_agent(model, tool_search_client, task_system_prompt)
    return agent, initial_state, tool_search_client
