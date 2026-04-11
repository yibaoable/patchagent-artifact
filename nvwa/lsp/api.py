import os
import atexit
from typing import Union, List

from nvwa.logger import log
from nvwa.sky.task import PatchTask
from nvwa.lsp.utils import find_backend, SERVER_POOL


def viewcode(task: PatchTask, path: str, start_line: int, end_line: int) -> Union[List[str], None]:
    real_path = os.path.join(task.immutable_project_path, path)

    if os.path.exists(real_path):
        with open(real_path, "r") as f:
            return f.readlines()[start_line - 1 : end_line]

    return None


def find_definition(task: PatchTask, path: str, line: int, column: int) -> List[str]:
    server = find_backend(task, find_definition.__name__)
    if server is None:
        return []
    return server.find_definition(path, line, column)  # type: ignore


def locate_symbol(task: PatchTask, symbol: str) -> List[str]:
    server = find_backend(task, locate_symbol.__name__)
    if server is None:
        return []
    return server.locate_symbol(symbol)  # type: ignore

def hover(task: PatchTask, path: str, line: int, column: int) -> Union[str, None]:
    server = find_backend(task, hover.__name__)
    if server is None:
        return None
    return server.hover(path, line, column)  # type: ignore

@atexit.register
def release(task: Union[PatchTask, None] = None):
    log.info("Releasing all LSP servers")
    for _, pool in SERVER_POOL:
        for key, server in pool.items():
            if task is None or server.task == task:
                server.stop()
