"""LangChain @tool wrappers — domain-specific tools for the Deep Agent.

Note: filesystem (ls, read_file, write_file, edit_file, glob, grep), planning (write_todos),
and subagent delegation (task) are all provided natively by deepagents — do not duplicate them.
"""
import logging

from langchain.tools import tool

from src import config

logger = logging.getLogger(__name__)


@tool
def web_search_tool(query: str) -> str:
    """Search the web for real-time information. Use for current events, facts, or any topic needing up-to-date data."""
    from src.tools.web_search import web_search

    logger.debug(f'Executing web search "${query}"')
    results = web_search(query=query, max_results=config.WEB_SEARCH_MAX_RESULTS)
    if not results:
        return "No results found."
    return "\n\n".join(f"[{r['title']}]({r['url']})\n{r['content']}" for r in results)


@tool
def execute_python_tool(code: str) -> str:
    """Execute Python code and return stdout/stderr output. Use for calculations, data processing, or scripting tasks."""
    from src.tools.code_executor import execute_python

    logger.debug(f'executing pyhton code: ${code}')
    return execute_python(code)


@tool
def execute_shell_tool(command: str) -> str:
    """Run a bash shell command and return its output. Use for system tasks or CLI tools."""
    from src.tools.code_executor import execute_shell

    logger.debug(f'executing shell tool: ${command}')
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

    logger.debug(f'Sending email to ${to}, with subject "${subject}"')
    success = send_email(to=to, subject=subject, body=body)
    return f"Email sent to {to}." if success else "Failed to send email."


ALL_TOOLS = [
    web_search_tool,
    execute_python_tool,
    execute_shell_tool,
    send_email_tool,
]
