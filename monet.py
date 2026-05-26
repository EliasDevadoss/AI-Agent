import inspect
import json
import os
import anthropic

from dotenv import load_dotenv
from pathlib import Path
from typing import Any, Dict, List, Tuple, TypedDict

load_dotenv()

claude_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
ai_model = os.environ["AI_MODEL"]

PROJECT_ROOT = Path(os.environ.get("AGENT_PROJECT_ROOT", Path.cwd())).resolve()
BLOCKED_WRITE_NAMES = {".env", ".gitignore", "uv.lock"}

YOU_COLOR = "\u001b[94m"
ASSISTANT_COLOR = "\u001b[93m"
RESET_COLOR = "\u001b[0m"


class ToolCallResult(TypedDict):
    success: bool
    file_path: str | None
    data: {}
    errors: str | None


def resolve_abs_path(path_str: str) -> Path:
    """
    file.py -> /Users/you/project/file.py
    """
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if path != PROJECT_ROOT and PROJECT_ROOT not in path.parents():
        raise PermissionError(
            f"Attempting to edit outside allowed current directory at: {path}"
        )
    return path


def read_file_tool(filename: str) -> ToolCallResult:
    """
    Gets the full content of a file provided by the user.
    :param filename: The name of the file to read.
    :return: The full content of the file.
    """
    abs_path = resolve_abs_path(filename)
    with open(abs_path, "r") as file:
        content = file.read()
    return ToolCallResult(
        success=True, file_path=str(abs_path), data={"content": content}, errors=None
    )


def list_files_tool(path: str) -> ToolCallResult:
    """
    Lists the files in a directory provided by the user.
    :param path: The path to a directory to list files from.
    :return: A list of files in the directory.
    """
    abs_path = resolve_abs_path(path)
    files = []
    for sub_path in abs_path.iterdir():
        files.append(
            {
                "file_name": sub_path.name,
                "kind": "file" if sub_path.is_file() else "dir",
            }
        )
    return ToolCallResult(
        success=True, file_path=str(abs_path), data={"files": files}, errors=None
    )


def edit_file_tool(path: str, old_str: str, new_str: str) -> ToolCallResult:
    """
    Replaces first occurrence of old_str with new_str in file. If old_str is empty,
    create/overwrite file with new_str.
    :param path: The path to the file to edit.
    :param old_str: The string to replace.
    :param new_str: The string to replace with.
    :return: A dictionary with the path to the file and the action taken.
    """
    abs_path = resolve_abs_path(path)
    path_parts = abs_path.parts()

    if any(part in BLOCKED_WRITE_NAMES for part in path_parts):
        raise PermissionError(f"Not allowed to edit protected file at: {abs_path}")

    if old_str == "":
        abs_path.write_text(new_str)
        return ToolCallResult(
            success=True,
            file_path=str(abs_path),
            data={"action": "New file created"},
            errors=None,
        )

    existing_text = abs_path.read_text()

    if existing_text.find(old_str) == -1:
        return ToolCallResult(
            success=False,
            file_path=str(abs_path),
            data={"action": "None"},
            errors="Error, `old_str` not found",
        )

    updated_text = existing_text.replace(old_str, new_str, 1)
    abs_path.write_text(updated_text)
    return ToolCallResult(
        success=True,
        file_path=str(abs_path),
        data={"action": "File updated"},
        errors=None,
    )


TOOL_LIST = {
    "read_file": read_file_tool,
    "list_files": list_files_tool,
    "edit_file": edit_file_tool,
}

SYSTEM_PROMPT = """
You are a coding assistant geared towards assisting the user in coding tasks. Please read the following instructions on
tools carefully.


You have access to some tools, which are listed here:

{full_tool_list}

To use a tool, your ENTIRE response must be a single line of the format: 'tool: 
TOOL_NAME({{JSON_ARGS}})' and nothing more. 
Use compact single-line JSON with double quotes. After receiving a tool_result(...) 
message, you may continue the task. Do not respond with multiple tool calls before 
receiving a successful response. If no tool call is needed, respond normally.
"""


def get_tool_str(tool_name: str) -> str:
    tool = TOOL_LIST[tool_name]
    return f"""
    Name: {tool_name}
    Description: {tool.__doc__}
    Signature: {inspect.signature(tool)}
    """


def get_full_system_prompt():
    full_tool_list = ""
    for tool_name in TOOL_LIST:
        full_tool_list += "TOOL:" + get_tool_str(tool_name)
        full_tool_list += f"\n{'=' * 15}\n\n"
    return SYSTEM_PROMPT.format(full_tool_list=full_tool_list)


def extract_tool_calls(text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Return list of (tool_name, args) requested in 'tool: name({...})' lines.
    The parser expects single-line, compact JSON in parentheses.
    """
    invocations = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("tool:"):
            continue
        try:
            after = line[len("tool:") :].strip()
            name, rest = after.split("(", 1)
            name = name.strip()
            if not rest.endswith(")"):
                continue
            json_str = rest[:-1].strip()
            args = json.loads(json_str)
            invocations.append((name, args))
        except Exception:
            continue
    return invocations


def execute_tool_call(name: str, args: Dict[str, str]) -> ToolCallResult:
    if name not in TOOL_LIST:
        return ToolCallResult(
            success=False,
            file_path=None,
            data={"args": args},
            errors=f"Tool {name} not in tool list",
        )
    tool = TOOL_LIST[name]

    sig = inspect.signature(tool)

    try:
        sig.bind(**args)
    except TypeError as e:
        return ToolCallResult(
            success=False,
            file_path=None,
            data={"tool": name, "args": args},
            errors=f"Invalid arguments: {e}. Expected signature: {str(sig)}. Got args: {args}",
        )

    return tool(**args)


def execute_llm_call(conversation: List[Dict[str, str]]):
    system_content = ""
    messages = []

    for msg in conversation:
        if msg["role"] == "system":
            system_content = msg["content"]
        else:
            messages.append(msg)

    response = claude_client.messages.create(
        model=ai_model, max_tokens=2000, system=system_content, messages=messages
    )
    return response.content[0].text


def run_coding_agent_loop():
    print(get_full_system_prompt())
    conversation = [{"role": "system", "content": get_full_system_prompt()}]
    while True:
        try:
            user_input = input(f"{YOU_COLOR}You:{RESET_COLOR} ")
        except KeyboardInterrupt, EOFError:
            break
        if user_input == "quit" or user_input == "exit":
            break
        conversation.append({"role": "user", "content": user_input.strip()})
        while True:
            agent_response = execute_llm_call(conversation)
            tool_calls = extract_tool_calls(agent_response)
            if not tool_calls:
                print(f"{ASSISTANT_COLOR}Assistant:{RESET_COLOR} {agent_response}")
                conversation.append({"role": "assistant", "content": agent_response})
                break
            for name, args in tool_calls:
                print(name, args)
                conversation.append(
                    {"role": "assistant", "content": f"tool: {name}({args})"}
                )
                try:
                    resp = execute_tool_call(name, args)
                except (FileNotFoundError, PermissionError, TypeError) as e:
                    resp = ToolCallResult(
                        success=False,
                        file_path=None,
                        data={"tool": name, "args": args},
                        errors=str(e),
                    )
                conversation.append(
                    {
                        "role": "user",
                        "content": f"tool_result({json.dumps(resp, separators=(',', ':'))})",
                    }
                )


if __name__ == "__main__":
    run_coding_agent_loop()
