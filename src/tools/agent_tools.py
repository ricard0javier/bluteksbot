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
    """
    Search the public web and return titled snippets with links.
    Use when the user needs time-sensitive or verifiable facts (news, prices, live status, "what happened", or anything you cannot answer confidently from memory). Do not use for sending email, running code, or shell commands.
    """
    from src.tools.web_search import web_search

    logger.debug(f"Executing web search '{query}'")
    results = web_search(query=query, max_results=config.WEB_SEARCH_MAX_RESULTS)
    if not results:
        return "No results found."
    return "\n\n".join(f"[{r['title']}]({r['url']})\n{r['content']}" for r in results)


@tool
def execute_python_tool(code: str) -> str:
    """
    Execute Python in a constrained environment and return stdout/stderr.
    Use for math, parsing, data transforms, or algorithms expressed as Python. Prefer execute_shell_tool for bash/system CLIs; prefer web_search_tool for external facts.
    """
    from src.tools.code_executor import execute_python

    logger.debug(f"executing pyhton code: '{code}'")
    return execute_python(code)


@tool
def execute_shell_tool(command: str) -> str:
    """
    Run a shell command and return its combined output.
    Use for installed CLI tools, git, file inspection via shell, or OS utilities. Prefer execute_python_tool for logic or computation in Python; do not use for sending email or web search.
    """
    from src.tools.code_executor import execute_shell

    logger.debug(f"executing shell tool: '{command}'")
    return execute_shell(command)


@tool
def send_email_tool(to: str, subject: str, body: str) -> str:
    """
    Send one plain-text email through the app's configured SMTP/mailer.
    Use only when the user wants an email actually delivered (you have or can infer a valid recipient, subject, and body). Do not use for web search or code execution; if the user only wants draft text, respond in chat instead of calling this tool.
    """
    from src.tools.email_sender import send_email

    logger.debug(f"Sending email to {to}, with subject {subject}")
    success = send_email(to=to, subject=subject, body=body)
    return f"Email sent to {to}." if success else "Failed to send email."


AGENT_TOOLS = [
    web_search_tool,
    execute_python_tool,
    execute_shell_tool,
    send_email_tool,
]
