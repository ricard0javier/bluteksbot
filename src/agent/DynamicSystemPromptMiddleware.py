import logging
from datetime import UTC, datetime

from langchain.agents.middleware.types import ModelRequest, dynamic_prompt

from src.llms.prompts import ORCHESTRATOR_SYSTEM

logger = logging.getLogger(__name__)


@dynamic_prompt
def dynamic_prompt(request: ModelRequest) -> str:
    return f"""
    {ORCHESTRATOR_SYSTEM}
    
    Today's date and time is {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}. 
    UTC time is {datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")}.
    """
