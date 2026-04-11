import os
import subprocess

from nvwa.lsp.language import LanguageType, LanguageServer
from nvwa.sky.task import PatchTask
from nvwa.logger import log


class CtagsServer(LanguageServer):
    def __init__(self, task: PatchTask):
        super().__init__(task)
        self.tag_file = self._compile()
        self.symbol_map = {}

        with open(self.tag_file, "rb") as f:
            for line in f.readlines():
                if text := line.decode("utf-8", errors="ignore"):
                    if text.startswith("!_TAG_"):
                        continue
                    symbol, path, line_info = text.split(';"')[0].split("\t")
                    if symbol not in self.symbol_map:
                        self.symbol_map[symbol] = []
                    self.symbol_map[symbol].append(f"{path}:{line_info}")
                else:
                    log.warning(f"Failed to decode line {line}")

    @classmethod
    def supported_languages(cls) -> list[LanguageType]:
        return [
            LanguageType.C,
            LanguageType.JAVA,
            LanguageType.GO,
            LanguageType.PYTHON,
            LanguageType.JAVASCRIPT,
            LanguageType.TYPESCRIPT,
        ]

    def _compile(self):
        ctag_dir = os.path.join(self.task.path, "ctags")
        if not os.path.exists(ctag_dir):
            os.makedirs(ctag_dir)
            with open(os.path.join(ctag_dir, ".gitignore"), "w") as file:
                file.write("*\n")
        tag_file = os.path.join(ctag_dir, "tags")

        if not os.path.exists(tag_file):
            log.info(f"Generating ctags for {self.task.project} {self.task.tag}")
            subprocess.run(
                ["ctags", "--excmd=number", "--exclude=Makefile", "-f", tag_file, "-R"],
                cwd=self.task.immutable_project_path,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        return tag_file

    def locate_symbol(self, symbol: str) -> list:
        return self.symbol_map.get(symbol, [])
