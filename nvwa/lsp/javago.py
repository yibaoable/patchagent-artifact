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

JDTLS_HOME = os.environ.get("JDTLS_HOME", "/opt/jdtls")
LSP_JAVA_HOME = os.environ.get("LSP_JAVA_HOME", "/usr/lib/jvm/jdk-21.0.7+6/bin/java")
JDTLS_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("JDTLS_REQUEST_TIMEOUT_SECONDS", "600"))

class JavaLanguageServer(LanguageServer):
    def __init__(self, task: PatchTask):
        super().__init__(task)
        
        self.jdtls_home = Path(JDTLS_HOME)
        self.request_timeout = JDTLS_REQUEST_TIMEOUT_SECONDS
        self.build_dir = (
            self.task.immutable_project_path
            if os.path.isdir(self.task.immutable_project_path)
            else self.task.work_dir
        )

        self._start()
        print(f"JavaLanguageServer started with PID {self.proc.pid}, workspace={self.build_dir}")

    @classmethod
    def supported_languages(cls) -> list[LanguageType]:
        return [LanguageType.JAVA]

    def _start(self):
        """启动eclipse.jdt.ls服务器"""
        # 检查jdtls安装目录
        if not self.jdtls_home.exists():
            raise FileNotFoundError(f"jdtls目录不存在: {self.jdtls_home}")
        workspace_dir = Path(f"/tmp/jdtls-workspace/{self.task.tag}/.jdtls-workspace")
        
        # 查找launcher JAR
        launcher_jars = list(self.jdtls_home.glob("plugins/org.eclipse.equinox.launcher_*.jar"))
        if not launcher_jars:
            raise FileNotFoundError("未找到equinox launcher JAR")
        launcher_jar = launcher_jars[0]
        
        # 根据操作系统选择配置目录
        if sys.platform.startswith('linux'):
            config_dir = self.jdtls_home / "config_linux"
        elif sys.platform.startswith('darwin'):
            config_dir = self.jdtls_home / "config_mac"
        elif sys.platform.startswith('win32'):
            config_dir = self.jdtls_home / "config_win"
        else:
            raise RuntimeError(f"不支持的操作系统: {sys.platform}")
        
        
        self.proc = subprocess.Popen(
            [LSP_JAVA_HOME] + [
                "-jar",
                str(launcher_jar),
                "-configuration",
                str(config_dir),
                "-data",
                str(workspace_dir)
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=1,
            universal_newlines=True,
        )

        workspace_uri = f"file://{self.build_dir}"
        self.send_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": None,
                    "rootPath": None,
                    "rootUri": workspace_uri,
                    "capabilities": {},
                    "trace": "off",
                    "workspaceFolders": [
                        {
                            "uri": workspace_uri,
                            "name": os.path.basename(self.build_dir) or "workspace",
                        }
                    ],
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
        message_bytes = message_json.encode()
        content_length = len(message_bytes)
        full_message = f"Content-Length: {content_length}\r\n\r\n{message_json}"

        self.proc.stdin.write(full_message)  # type: ignore
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
                        "languageId": "java",
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
                "method": "textDocument/definition",
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

        results = self.read_response(timeout=timeout)

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
                        "languageId": "java",
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

        results = self.read_response(timeout=timeout)
        if results is None or results['contents']['value'] is None:
            return ""

        return results["contents"]["value"]

    def _normalize_symbol(self, name: str) -> str:
        return "".join(ch.lower() for ch in name if ch.isalnum())

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

        results = self.read_response(timeout=timeout)
        log.info(f"Symbol search results for '{symbol_name}': {results}")
        if results is None:
            return []

        query_norm = self._normalize_symbol(symbol_name)
        exact_matches = []
        fuzzy_matches = []
        all_locations = []

        for result in results:
            name = result.get("name", "")
            container = result.get("containerName", "")
            location = result.get("location")
            if location is None:
                continue

            prefix = f"file://{self.build_dir}/"
            path_ = location["uri"]
            if path_.startswith(prefix):
                path_ = path_[len(prefix) :]
            else:
                path_ = path_.replace("file://", "")
                log.warning(f"Trying to locate symbol in {path_}")
            line_ = location["range"]["start"]["line"] + 1
            chr_ = location["range"]["start"]["character"] + 1
            location_str = f"{path_}:{line_}:{chr_}"
            if name:
                location_str = f"{location_str}::{name}"
            all_locations.append(location_str)

            name_norm = self._normalize_symbol(name)
            container_norm = self._normalize_symbol(container)

            if name_norm == query_norm:
                exact_matches.append(location_str)
                continue

            if name_norm.endswith(query_norm) or query_norm in name_norm:
                fuzzy_matches.append(location_str)
                continue

            if query_norm in container_norm:
                fuzzy_matches.append(location_str)

        if exact_matches:
            return exact_matches
        if fuzzy_matches:
            log.info(f"Symbol '{symbol_name}' matched fuzzy candidates: {fuzzy_matches}")
            return fuzzy_matches

        log.warning(f"Symbol {symbol_name} not found, returning all candidates: {all_locations}")
        return all_locations

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

    def read_response(self, timeout: float | None = None):
        output_buffer = ""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    log.warning("Timed out waiting for response from jdtls")
                    return None
                ready, _, _ = select.select([self.proc.stdout], [], [], remaining)  # type: ignore[arg-type]
                if not ready:
                    log.warning("Timed out waiting for response from jdtls")
                    return None

            data = self.proc.stdout.read(1)  # type: ignore
            if not data:
                log.error("No data from jdtls")
                break
            output_buffer += data
            # print(f"Received data: {output_buffer}")  # Debug output

            while True:
                try:
                    response = json.loads(output_buffer)
                    # print(f"Response: {response}")
                    if response.get("method") != None or response.get("id") != 2:
                        output_buffer = ""
                        break
                    else:
                        return response["result"]
                except json.JSONDecodeError as e:
                    try:
                        start = output_buffer.index("{")
                        end = output_buffer.rindex("}") + 1
                        response = json.loads(output_buffer[start:end])
                        if response.get("method") != None or response.get("id") != 2:
                            output_buffer = ""
                            break
                        else:
                            return response["result"]
                    except (ValueError, json.JSONDecodeError):
                        break
