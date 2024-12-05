import os
import uuid
import logging
from typing import Dict, Any, List

from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, ToolMessage, BaseMessage

# [1] Wildcard companion packages are imported here. Since we're using langgraph, we need to import the langgraph package
from wildcard_core.tool_registry.tools.rest_api.types import ApiKeyAuthConfig, BearerAuthConfig, AuthType
from wildcard_core.tool_search.utils.api_service import APIService
from wildcard_langgraph import create_tool_selection_agent
from wildcard_core import ToolSearchClient


def get_agent():
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
    
    # [2] The ToolSearchClient is used to search for tools that the agent can use. Let's create one here.
    tool_search_client = ToolSearchClient(api_key='alpha-api-access')
    
    # [3] Register necessary API authentications if you have them
    # tool_search_client.register_api_auth(
    #     APIService.NEW_YORK_TIMES,
    #     ApiKeyAuthConfig(type=AuthType.API_KEY, key_value=os.getenv("NYT_API_KEY"))
    # )
    
    # [4] Initialize the agent. We're using the ChatOpenAI model here.
    openai_api_key = os.getenv("OPENAI_API_KEY")
    model = ChatOpenAI(model="gpt-4o", temperature=0, api_key=openai_api_key)

    # [5] Here's the fun part. Tweak this prompt to change the behavior of the agent
    task_system_prompt = """You are an autonomous personal assistant.
    """

    # [6] Create the agent enabled with our tool search client.
    agent, initial_state = create_tool_selection_agent(model, tool_search_client, task_system_prompt)
    return agent, initial_state, tool_search_client
