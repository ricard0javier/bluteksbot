"""LangChain @tool wrappers — exposes all bot capabilities as tools for the Deep Agent."""
import logging

from langchain.tools import tool

from src import config

logger = logging.getLogger(__name__)


@tool
def web_search_tool(query: str) -> str:
    """Search the web for real-time information. Use for current events, facts, or any topic needing up-to-date data."""
    from src.tools.web_search import web_search

    results = web_search(query=query, max_results=config.WEB_SEARCH_MAX_RESULTS)
    if not results:
        return "No results found."
    return "\n\n".join(f"[{r['title']}]({r['url']})\n{r['content']}" for r in results)


@tool
def execute_python_tool(code: str) -> str:
    """Execute Python code and return stdout/stderr output. Use for calculations, data processing, or scripting tasks."""
    from src.tools.code_executor import execute_python

    return execute_python(code)


@tool
def execute_shell_tool(command: str) -> str:
    """Run a bash shell command in the workspace and return its output. Use for file operations, system tasks, or CLI tools."""
    from src.tools.code_executor import execute_shell

    return execute_shell(command)


@tool
def send_email_tool(to: str, subject: str, body: str) -> str:
    """Send a plain-text email to the specified recipient.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain-text email body.
    """
    from src.tools.email_sender import send_email

    success = send_email(to=to, subject=subject, body=body)
    return f"Email sent to {to}." if success else "Failed to send email."


@tool
def calendar_tool(task: str) -> str:
    """Create, query, or manage calendar events. Describe the action in natural language.

    Args:
        task: Natural language description of the calendar operation (e.g. 'schedule a meeting tomorrow at 3pm').
    """
    from src.llms import client as llm
    from src.llms.prompts import CALENDAR_AGENT_SYSTEM

    messages = [
        {"role": "system", "content": CALENDAR_AGENT_SYSTEM},
        {"role": "user", "content": task},
    ]
    try:
        return llm.chat(messages, model=config.LITELLM_WORKER_MODEL)
    except Exception:
        logger.error("calendar_tool failed.", exc_info=True)
        return "Calendar operation failed."


@tool
def reminder_tool(task: str) -> str:
    """Set, list, or complete reminders and tasks. Describe the action in natural language.

    Args:
        task: Natural language description of the reminder (e.g. 'remind me to call John at 5pm').
    """
    from src.llms import client as llm
    from src.llms.prompts import REMINDERS_AGENT_SYSTEM

    messages = [
        {"role": "system", "content": REMINDERS_AGENT_SYSTEM},
        {"role": "user", "content": task},
    ]
    try:
        return llm.chat(messages, model=config.LITELLM_WORKER_MODEL)
    except Exception:
        logger.error("reminder_tool failed.", exc_info=True)
        return "Reminder operation failed."


@tool
def process_document_tool(content: str) -> str:
    """Analyse, summarise, or answer questions about a document. Pass the extracted text content.

    Args:
        content: The extracted text content of the document to process.
    """
    from src.llms import client as llm
    from src.llms.prompts import FILES_AGENT_SYSTEM

    messages = [
        {"role": "system", "content": FILES_AGENT_SYSTEM},
        {"role": "user", "content": content},
    ]
    try:
        return llm.chat(messages, model=config.LITELLM_WORKER_MODEL)
    except Exception:
        logger.error("process_document_tool failed.", exc_info=True)
        return "Document processing failed."


ALL_TOOLS = [
    web_search_tool,
    execute_python_tool,
    execute_shell_tool,
    send_email_tool,
    calendar_tool,
    reminder_tool,
    process_document_tool,
]
