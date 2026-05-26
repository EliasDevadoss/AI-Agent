import inspect
import json
import os
import anthropic

from dotenv import load_dotenv
from pathlib import Path
from typing import Any, Dict, List, TypedDict

load_dotenv()

claude_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
ai_model = os.environ["AI_MODEL"]

PROJECT_ROOT = Path(os.environ.get("AGENT_PROJECT_ROOT", Path.cwd())).resolve()
BLOCKED_FILE_NAMES = {".env", ".gitignore", "uv.lock"}

YOU_COLOR = "\u001b[94m"
ASSISTANT_COLOR = "\u001b[93m"
TOOL_COLOR = "\u001b[92m"
RESET_COLOR = "\u001b[0m"


class ToolCallResult(TypedDict):
    success: bool
    file_path: str | None
    data: Dict[str, Any]
    errors: str | None


def resolve_abs_path(path_str: str) -> Path:
    """
    file.py -> /Users/you/project/file.py
    """
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if path != PROJECT_ROOT and PROJECT_ROOT not in path.parents:
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
    path_parts = abs_path.parts

    if any(part in BLOCKED_FILE_NAMES for part in path_parts):
        raise PermissionError(f"Not allowed to read protected file at: {abs_path}")

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
    path_parts = abs_path.parts

    if any(part in BLOCKED_FILE_NAMES for part in path_parts):
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

TOOL_DEFINITIONS = [
    {
        "name": "read_file",
        "description": (
            "Read the full text content of a file inside the allowed project root. "
            "Use this when you need to inspect an existing source file, README, "
            "configuration file, or other text file before answering or editing. "
            "The filename parameter may be a relative path from the current project."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Relative or absolute path to the file to read.",
                }
            },
            "required": ["filename"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_files",
        "description": (
            "List the immediate children of a directory inside the allowed project root. "
            "Use this when you need to discover what files or subdirectories exist before "
            "choosing which file to inspect or edit. The result includes each child name "
            "and whether it is a file or directory, but does not recursively list contents."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative or absolute path to the directory to list.",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Edit a text file inside the allowed project root by replacing the first "
            "occurrence of old_str with new_str. Use this after reading enough context "
            "to make a precise change. If old_str is an empty string, the tool creates "
            "or overwrites the target file with new_str; protected project files cannot "
            "be edited."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative or absolute path to the file to edit.",
                },
                "old_str": {
                    "type": "string",
                    "description": "Exact text to replace, or an empty string to create or overwrite the file.",
                },
                "new_str": {
                    "type": "string",
                    "description": "Replacement text or complete new file content.",
                },
            },
            "required": ["path", "old_str", "new_str"],
            "additionalProperties": False,
        },
    },
]

SYSTEM_PROMPT = """
You are a coding assistant geared towards assisting the user in coding tasks.
Use tools when you need to inspect or change local project files. Explain your
work normally when no tool call is needed.
"""


def execute_tool_call(name: str, args: Dict[str, Any]) -> ToolCallResult:
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


def format_tool_call(name: str, args: Dict[str, Any]) -> str:
    return f"{name}({json.dumps(args, separators=(',', ':'))})"


def format_tool_result(result: ToolCallResult) -> str:
    return json.dumps(result, separators=(",", ":"))


def execute_llm_call(conversation: List[Dict[str, Any]]):
    return claude_client.messages.create(
        model=ai_model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=conversation,
        tools=TOOL_DEFINITIONS,
    )


def run_coding_agent_loop():
    conversation = []
    while True:
        try:
            user_input = input(f"{YOU_COLOR}You:{RESET_COLOR} ")
        except KeyboardInterrupt, EOFError:
            break
        user_input = user_input.strip()
        if not user_input:
            continue
        if user_input == "quit" or user_input == "exit":
            break
        conversation.append({"role": "user", "content": user_input})
        while True:
            response = execute_llm_call(conversation)
            assistant_content = [
                block.model_dump(exclude_none=True) for block in response.content
            ]
            conversation.append({"role": "assistant", "content": assistant_content})

            assistant_text = "\n".join(
                block.text for block in response.content if block.type == "text"
            ).strip()
            if assistant_text:
                print(f"{ASSISTANT_COLOR}Monet:{RESET_COLOR} {assistant_text}")

            tool_use_blocks = [
                block for block in response.content if block.type == "tool_use"
            ]
            if not tool_use_blocks:
                break

            tool_result_blocks = []
            for block in tool_use_blocks:
                tool_use_id = block.id
                name = block.name
                args = block.input
                print(
                    f"{TOOL_COLOR}Tool call:{RESET_COLOR} "
                    f"{format_tool_call(name, args)}"
                )
                try:
                    resp = execute_tool_call(name, args)
                except (OSError, TypeError) as e:
                    resp = ToolCallResult(
                        success=False,
                        file_path=None,
                        data={"tool": name, "args": args},
                        errors=str(e),
                    )
                tool_result = format_tool_result(resp)
                truncated_tool_result = (
                    (tool_result[:1000] + "...")
                    if len(tool_result) > 1000
                    else tool_result
                )
                print(f"{TOOL_COLOR}Tool result:{RESET_COLOR} {truncated_tool_result}")
                tool_result_block = {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": tool_result,
                }
                if not resp["success"]:
                    tool_result_block["is_error"] = True
                tool_result_blocks.append(tool_result_block)

            conversation.append({"role": "user", "content": tool_result_blocks})


if __name__ == "__main__":
    run_coding_agent_loop()
