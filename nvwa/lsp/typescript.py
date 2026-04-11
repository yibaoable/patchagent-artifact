import os
import re
import sys
import json
import time
import subprocess
from typing import Union
from pathlib import Path

from nvwa.logger import log
from nvwa.sky.task import PatchTask
from nvwa.lsp.language import LanguageType, LanguageServer

TSSERVER_PATH = os.environ.get("TSSERVER_PATH", "/opt/tools/node/bin/node,/opt/tools/node/bin/typescript-language-serverr")

class TypeScriptLanguageServer(LanguageServer):
    def __init__(self, task: PatchTask):
        super().__init__(task)
        self.build_dir = self.task.work_dir

        self._start()

    @classmethod
    def supported_languages(cls) -> list[LanguageType]:
        return [LanguageType.TYPESCRIPT]

    def _start(self):
        """启动typescript-language-server服务器"""
        self.proc = subprocess.Popen(
            [TSSERVER_PATH] + ["--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=1,
            universal_newlines=True,
        )

        self.send_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": None,
                    "rootPath": None,
                    "rootUri": f"file://{self.build_dir}",
                    "capabilities": {},
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
        message_bytes = message_json.encode()
        content_length = len(message_bytes)
        full_message = f"Content-Length: {content_length}\r\n\r\n{message_json}"

        self.proc.stdin.write(full_message)  # type: ignore
        self.proc.stdin.flush()  # type: ignore

    def _find_definition(self, path: str, line: int, chr: int) -> Union[list[str], None]:
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

        results = self.read_response()

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

    def _hover(self, path: str, line: int, chr: int) -> Union[str, None]:
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

        results = self.read_response()
        if results is None or results['contents']['value'] is None:
            return ""

        return results["contents"]["value"]

    def _locate_symbol(self, symbol_name: str) -> list[str]:

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

        results = self.read_response()
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

    def find_definition(self, path: str, line: int, chr: int) -> list[str]:
        filepath = os.path.join(self.build_dir, path)
        log.info(f"Finding definition for {filepath}:{line}:{chr}")
        line, chr = line - 1, chr - 1

        while True:
            locations = self._find_definition(filepath, line, chr)
            if locations is not None:
                return locations
            self.stop()
            self._start()

    def hover(self, path: str, line: int, chr: int) -> str:
        filepath = os.path.join(self.build_dir, path)
        log.info(f"Get hint for {filepath}:{line}:{chr}")  # hover
        line, chr = line - 1, chr - 1

        while True:
            hint = self._hover(filepath, line, chr)
            if hint is not None:
                return hint
            self.stop()
            self._start()

    def locate_symbol(self, symbol_name: str) -> list[str]:
        log.info(f"Locating symbol {symbol_name}")
        while True:
            locations = self._locate_symbol(symbol_name)
            if locations is not None:
                return locations
            self.stop()
            self._start()

    def read_response(self):
        output_buffer = ""
        while True:
            data = self.proc.stdout.read(1)  # type: ignore
            if not data:
                log.error("No data from typescript-language-server")
                break
            output_buffer += data # type: ignore

            while True:
                try:
                    response = json.loads(output_buffer)
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
