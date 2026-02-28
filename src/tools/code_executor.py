"""Code and shell executor — subprocess with timeout, working in the configured workspace."""
import logging
import subprocess
import sys

from src import config

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 5000
_WORKSPACE = config.CODE_EXECUTOR_WORKSPACE


def execute_python(code: str) -> str:
    """Runs Python code in a subprocess with a hard timeout. Returns stdout/stderr."""
    return _run([sys.executable, "-c", code], timeout=config.CODE_EXECUTOR_TIMEOUT)


def execute_shell(command: str, timeout: int | None = None) -> str:
    """Runs an arbitrary bash command in /workspace. Returns stdout/stderr."""
    effective_timeout = timeout if timeout is not None else config.CODE_EXECUTOR_TIMEOUT
    return _run(command, shell=True, timeout=effective_timeout)


def _run(
    cmd: list[str] | str,
    shell: bool = False,
    timeout: int = config.CODE_EXECUTOR_TIMEOUT,
) -> str:
    try:
        result = subprocess.run(
            cmd,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_WORKSPACE,
        )
        output = result.stdout + result.stderr
        if len(output) > _MAX_OUTPUT_CHARS:
            output = output[:_MAX_OUTPUT_CHARS] + "\n...(truncated)"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        logger.warning("Execution timed out after %ds.", timeout)
        return f"Execution timed out after {timeout}s."
    except Exception:
        logger.error("Executor failed.", exc_info=True)
        return "Execution error."
