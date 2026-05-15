import logging
from collections.abc import Callable

from langchain.agents.middleware.types import ModelRequest, ModelResponse, wrap_model_call

from src import config
from src.llms.models import get_chat_model
from src.persistence.preferences_store import get_model

logger = logging.getLogger(__name__)


@wrap_model_call
def dynamic_model(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    thread_model = get_model(request.runtime.execution_info.thread_id)
    if thread_model is not None:
        selected_model = get_chat_model(thread_model)
    else:
        selected_model = get_chat_model(config.WORKER_MODEL)
    return handler(request.override(model=selected_model))
