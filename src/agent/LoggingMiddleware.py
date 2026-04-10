import logging
from collections.abc import Callable

from langchain.agents.middleware import (
    AgentMiddleware,
)
from langchain.agents.middleware.types import (
    AIMessage,
    ContextT,
    ExtendedModelResponse,
    ModelRequest,
    ModelResponse,
    ResponseT,
)

logger = logging.getLogger(__name__)


class LoggingMiddleware(AgentMiddleware):
    def __init__(self):
        super().__init__()

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[ResponseT]],
    ) -> ModelResponse[ResponseT] | AIMessage | ExtendedModelResponse[ResponseT]:

        if not logger.isEnabledFor(logging.DEBUG):
            return handler(request)

        num_messages = len(request.messages)
        messages_characters = sum(len(message.content) for message in request.messages)
        system_prompt_characters = len(request.system_prompt) if request.system_prompt else 0
        tool_prompt_characters = (
            sum(len(tool.description) for tool in request.tools) if request.tools else 0
        )
        total_tools = len(request.tools) if request.tools else 0
        total_characters = (
            messages_characters + system_prompt_characters + tool_prompt_characters + total_tools
        )

        logger.debug(
            f"""
        About to call model with {num_messages} messages ({messages_characters} characters), 
        a system prompt of {system_prompt_characters} characters, 
        a tool prompt of {tool_prompt_characters} characters, 
        a total of {total_tools} tools, 
        and a total of {total_characters} characters"""
        )

        response = handler(request)

        model_name = response.result[0].response_metadata["model_name"]
        model_provider = response.result[0].response_metadata["model_provider"]
        prompt_tokens = response.result[0].response_metadata["token_usage"]["prompt_tokens"]
        tokens_per_character = prompt_tokens / total_characters
        completion_tokens = response.result[0].response_metadata["token_usage"]["completion_tokens"]
        total_tokens = response.result[0].response_metadata["token_usage"]["total_tokens"]
        logger.debug(f"Model used: {model_name} ({model_provider})")
        logger.debug(
            f"Prompt tokens: {prompt_tokens}, tokens per character: {tokens_per_character:.4f}"
        )
        logger.debug(f"Completion tokens: {completion_tokens}")
        logger.debug(f"Total tokens: {total_tokens}")

        return response
