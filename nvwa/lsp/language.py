from nvwa.sky.task import PatchTask
from enum import StrEnum


class LanguageType(StrEnum):
    C = "c"
    JAVA = "java"
    GO = "go"
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"


class LanguageServer:
    def __init__(self, task: PatchTask):
        self.task = task

    @property
    def project(self):
        return self.task.project

    @property
    def tag(self):
        return self.task.tag

    @property
    def key(self):
        return f"{self.task.project}-{self.task.tag}"

    def stop(self):
        pass  # Do nothing

    @classmethod
    def supported_languages(cls) -> list[LanguageType]:
        return []
