from typing import Union

from nvwa.sky.task import PatchTask
from nvwa.logger import log

from nvwa.lsp.clangd import ClangdServer
from nvwa.lsp.ctags import CtagsServer
from nvwa.lsp.language import LanguageType, LanguageServer
from nvwa.lsp.javago import JavaLanguageServer
from nvwa.lsp.pyright import PythonLanguageServer
from nvwa.lsp.javascript import JavaScriptLanguageServer
from nvwa.lsp.typescript import TypeScriptLanguageServer
from nvwa.lsp.gopls import GoLanguageServer

SERVER_POOL: list[tuple[type[LanguageServer], dict]] = [
    (ClangdServer, {}),
    (CtagsServer, {}),
    (JavaLanguageServer, {}),
    (PythonLanguageServer, {}),
    (JavaScriptLanguageServer, {}),
    (TypeScriptLanguageServer, {}),
    (GoLanguageServer, {}),
]

def get_language(task: PatchTask) -> str:
    if task.language == "c":
        return LanguageType.C
    elif task.language == "java":
        return LanguageType.JAVA
    elif task.language == "go":
        return LanguageType.GO
    elif task.language == "python":
        return LanguageType.PYTHON
    elif task.language == "javascript":
        return LanguageType.JAVASCRIPT
    elif task.language == "typescript":
        return LanguageType.TYPESCRIPT
    return LanguageType.C

def find_backend(task: PatchTask, interface: str)  -> Union[None, LanguageServer]:
    key = f"{task.project}-{task.tag}"
    language = get_language(task)

    if interface == "locate_symbol":
        for server, pool in SERVER_POOL:
            if server is not CtagsServer:
                continue
            if language not in server.supported_languages() or not hasattr(server, interface):
                continue
            if key not in pool:
                try:
                    pool[key] = server(task)
                except Exception as exc:
                    log.warning(f"Failed to start {server.__name__} for {key}: {exc}")
                    return None
            return pool[key]

        # Keep language-specific locate_symbol implementations for future restore.
        # for server, pool in SERVER_POOL:
        #     if language in server.supported_languages() and hasattr(server, interface):
        #         ...
        return None

    for server, pool in SERVER_POOL:
        if language in server.supported_languages() and hasattr(server, interface):
            if key not in pool:
                try:
                    pool[key] = server(task)
                except Exception as exc:
                    log.warning(f"Failed to start {server.__name__} for {key}: {exc}")
                    continue
            return pool[key]
    return None
