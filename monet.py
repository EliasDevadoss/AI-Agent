import inspect
import json
import os

from openai import OpenAI

from dotenv import load_dotenv
from pathlib import Path
from typing import Any, Dict, List, Tuple

load_dotenv()

YOU_COLOR = "\u001b[94m"
ASSISTANT_COLOR = "\u001b[93m"
RESET_COLOR = "\u001b[0m"

def resolve_abs_path(path_str: str) -> Path:
    """
    file.py -> /Users/you/project/file.py
    """
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path

def read_file_tool(filename: str) -> Dict[str, Any]:
    """
    Gets the full content of a file provided by the user.
    :param filename: The name of the file to read.
    :return: The full content of the file.
    """
    abs_path = resolve_abs_path(filename)
    print(abs_path)
    with open(abs_path, 'r') as file:
        content = file.read()
    return {"file_path": str(abs_path), "content": content}

def list_files_tool(path: str) -> Dict[str, Any]:
    """
    Lists the files in a directory provided by the user.
    :param path: The path to a directory to list files from.
    :return: A list of files in the directory.
    """
    abs_path = resolve_abs_path(path)
    files = []
    for sub_path in abs_path.iterdir() if abs_path.is_dir():
        files.append({
            "file_name": sub_path.name,
            "kind": "file" if sub_path.is_file() else "dir"
        })
    return {"path": abs_path, "files": files}

def edit_file_tool(path: str, old_str: str, new_str: str) -> Dict[str, Any]:
    """
    Replaces first occurrence of old_str with new_str in file. If old_str is empty,
    create/overwrite file with new_str.
    :param path: The path to the file to edit.
    :param old_str: The string to replace.
    :param new_str: The string to replace with.
    :return: A dictionary with the path to the file and the action taken.
    """
    abs_path = resolve_abs_path(path)