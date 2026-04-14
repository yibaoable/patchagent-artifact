import os
import re
import sys
import json
import time
import select
import subprocess
from typing import Union
from pathlib import Path

from nvwa.logger import log
from nvwa.sky.task import PatchTask
from nvwa.lsp.language import LanguageType, LanguageServer

TSSERVER_PATH = os.environ.get("TSSERVER_PATH", "/opt/tools/node/bin/node,/opt/tools/node/bin/typescript-language-server")
tsserver_cmd = TSSERVER_PATH.split(',')
TSSERVER_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("TSSERVER_REQUEST_TIMEOUT_SECONDS", "120"))

class TypeScriptLanguageServer(LanguageServer):
    def __init__(self, task: PatchTask):
        super().__init__(task)
        self.build_dir = self.task.work_dir
        self.request_timeout = TSSERVER_REQUEST_TIMEOUT_SECONDS

        self._start()

    @classmethod
    def supported_languages(cls) -> list[LanguageType]:
        return [LanguageType.TYPESCRIPT]

    def _start(self):
        """启动typescript-language-server服务器"""
        self.proc = subprocess.Popen(
            tsserver_cmd + ["--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=False,
            bufsize=0,
        )

        self.send_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": None,
                    "rootPath": self.build_dir,
                    "rootUri": f"file://{self.build_dir}",
                    "capabilities": {},
                    "initializationOptions":{
                        "typescript": {
                            "preferences": {
                                "includePackageJsonAutoImports": "auto",
                                "importModuleSpecifierPreference": "relative",  # 优先相对路径导入
                                "quoteStyle": "single",  # 单引号偏好
                                "allowTextChangesInNewFiles": True
                            },
                            "tsserver": {
                                "logVerbosity": "verbose",
                                "logDirectory": os.path.expanduser("~/.tsserver-logs")
                            }
                        }
                    },
                    "trace": "off",
                    "workspaceFolders": None,
                },
            }
        )
        self.send_request({"jsonrpc": "2.0", "method": "initialized", "params": {}})

    def stop(self):
        time.sleep(1)
        assert self.proc is not None
        self.send_request({"jsonrpc": "2.0", "method": "shutdown", "params": {}})
        self.send_request({"jsonrpc": "2.0", "method": "exit", "params": {}})
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()

        if hasattr(self.proc.stdin, 'close'):
            self.proc.stdin.close() # type: ignore
        if hasattr(self.proc.stdout, 'close'):
            self.proc.stdout.close() # type: ignore
        if hasattr(self.proc.stderr, 'close'):
            self.proc.stderr.close() # type: ignore

        self.proc = None
    
    def send_request(self, message):
        message_json = json.dumps(message)
        message_bytes = message_json.encode("utf-8")
        header = f"Content-Length: {len(message_bytes)}\r\n\r\n".encode("ascii")
        self.proc.stdin.write(header + message_bytes)  # type: ignore
        self.proc.stdin.flush()  # type: ignore

    def _find_definition(self, path: str, line: int, chr: int, timeout: float | None = None) -> Union[list[str], None]:
        with open(path, "r") as f:
            content = f.read()

        self.send_request(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": f"file://{path}",
                        "languageId": "typescript",
                        "version": 1,
                        "text": content,
                    }
                },
            }
        )
        self.send_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "workspace/executeCommand",
                "params": {
                "command": "_typescript.goToSourceDefinition", 
                    "arguments": [
                        f"file://{path}",
                        {
                            "line": line,
                            "character": chr
                        }
                    ]
                },
            }
        )

        results = self.read_response(expected_id=2, timeout=timeout)

        if results is None:
            return None

        locations = []
        for result in results:
            prefix = f"file://{self.build_dir}/"
            path_ = result["uri"]
            if path_.startswith(prefix):
                path_ = path_[len(prefix) :]
            else:
                path_ = path_.replace("file://", "")
                log.warning(f"Trying to locate symbol in {path_}")
            line_ = result["range"]["start"]["line"] + 1
            chr_ = result["range"]["start"]["character"] + 1
            locations.append(f"{path_}:{line_}:{chr_}")

        return locations

    def _hover(self, path: str, line: int, chr: int, timeout: float | None = None) -> Union[str, None]:
        with open(path, "r") as f:
            content = f.read()

        self.send_request(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": f"file://{path}",
                        "languageId": "typescript",
                        "version": 1,
                        "text": content,
                    }
                },
            }
        )
        self.send_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/hover",
                "params": {
                    "textDocument": {
                        "uri": f"file://{path}",
                    },
                    "position": {
                        "line": line,
                        "character": chr,
                    },
                },
            }
        )

        results = self.read_response(expected_id=2, timeout=timeout)
        if results is None or results['contents']['value'] is None:
            return ""

        return results["contents"]["value"]

    def _locate_symbol(self, symbol_name: str, timeout: float | None = None) -> list[str]:

        self.send_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "workspace/symbol",
                "params": {
                    "query": symbol_name
                }
            }
        )

        results = self.read_response(expected_id=2, timeout=timeout)
        if results is None:
            return []

        locations = []
        for result in results:
            if result["name"] != symbol_name:
                continue
            location = result["location"]
            prefix = f"file://{self.build_dir}/"
            path_ = location["uri"]
            if path_.startswith(prefix):
                path_ = path_[len(prefix) :]
            else:
                path_ = path_.replace("file://", "")
                log.warning(f"Trying to locate symbol in {path_}")
            line_ = location["range"]["start"]["line"] + 1
            chr_ = location["range"]["start"]["character"] + 1
            locations.append(f"{path_}:{line_}:{chr_}")

        return locations

    def _remaining_timeout(self, deadline: float) -> float:
        return max(0.0, deadline - time.monotonic())

    def find_definition(self, path: str, line: int, chr: int) -> list[str]:
        filepath = os.path.join(self.build_dir, path)
        log.info(f"Finding definition for {filepath}:{line}:{chr}")
        line, chr = line - 1, chr - 1
        deadline = time.monotonic() + self.request_timeout

        while True:
            remaining = self._remaining_timeout(deadline)
            if remaining <= 0:
                log.warning(f"Timed out finding definition for {filepath}:{line + 1}:{chr + 1}")
                return []

            locations = self._find_definition(filepath, line, chr, remaining)
            if locations is not None:
                return locations
            if self._remaining_timeout(deadline) <= 0:
                log.warning(f"Timed out finding definition for {filepath}:{line + 1}:{chr + 1}")
                return []
            self.stop()
            self._start()

    def hover(self, path: str, line: int, chr: int) -> str:
        filepath = os.path.join(self.build_dir, path)
        log.info(f"Get hint for {filepath}:{line}:{chr}")  # hover
        line, chr = line - 1, chr - 1
        deadline = time.monotonic() + self.request_timeout

        while True:
            remaining = self._remaining_timeout(deadline)
            if remaining <= 0:
                log.warning(f"Timed out getting hint for {filepath}:{line + 1}:{chr + 1}")
                return ""

            hint = self._hover(filepath, line, chr, remaining)
            if hint is not None:
                return hint
            if self._remaining_timeout(deadline) <= 0:
                log.warning(f"Timed out getting hint for {filepath}:{line + 1}:{chr + 1}")
                return ""
            self.stop()
            self._start()

    def locate_symbol(self, symbol_name: str) -> list[str]:
        log.info(f"Locating symbol {symbol_name}")
        deadline = time.monotonic() + self.request_timeout
        while True:
            remaining = self._remaining_timeout(deadline)
            if remaining <= 0:
                log.warning(f"Timed out locating symbol {symbol_name}")
                return []

            locations = self._locate_symbol(symbol_name, remaining)
            if locations is not None:
                return locations
            if self._remaining_timeout(deadline) <= 0:
                log.warning(f"Timed out locating symbol {symbol_name}")
                return []
            self.stop()
            self._start()

    def read_one_lsp_message(self, timeout: float | None = None):
        assert self.proc is not None
        stream = self.proc.stdout
        assert stream is not None

        deadline = None if timeout is None else time.monotonic() + timeout

        def _wait_ready():
            if deadline is None:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for LSP message")
            ready, _, _ = select.select([stream], [], [], remaining)
            if not ready:
                raise TimeoutError("Timed out waiting for LSP message")

        # 1) 读 header（按 bytes）
        headers = {}
        header_buf = b""
        while True:
            _wait_ready()
            ch = stream.read(1)
            if not ch:
                raise RuntimeError("LSP server closed stdout")

            if isinstance(ch, str):
                ch = ch.encode("utf-8")

            header_buf += ch

            # LSP header 结束标志：\r\n\r\n
            if header_buf.endswith(b"\r\n\r\n"):
                break

        header_text = header_buf.decode("ascii", errors="replace")
        for line in header_text.split("\r\n"):
            if not line.strip():
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        if "content-length" not in headers:
            raise RuntimeError(f"Missing Content-Length header: {header_text!r}")

        content_length = int(headers["content-length"])

        # 2) 精确读 body（按字节数）
        body = b""
        while len(body) < content_length:
            _wait_ready()
            chunk = stream.read(content_length - len(body))
            if not chunk:
                raise RuntimeError("LSP server closed while reading body")
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            body += chunk

        # 3) 解析 JSON
        message = json.loads(body.decode("utf-8"))
        # print(json.dumps(message, indent=2, ensure_ascii=False))
        return message

    def read_response(self, expected_id=None, timeout: float | None = None):
        while True:
            message = self.read_one_lsp_message(timeout=timeout)

            if "id" in message and message["id"] == expected_id:
                return message.get("result")

            # 其他 notification / 非目标 response 直接忽略，继续读