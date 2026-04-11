import os
import sys
from typing import Union
from nvwa.logger import log
from nvwa.parser.base import SanitizerReport
from nvwa.parser import parse
from nvwa.parser.sanitizer import Sanitizer

ROOT = os.getenv("SKYSET_ROOT", os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "skyset")))
sys.path.append(ROOT)

import skyset_tools


class PatchTask:
    def __init__(
        self,
        project: str,
        tag: str,
        sanitizer: Sanitizer,
        skip_setup: bool = False,  ## only used for debugging
    ):
        assert tag.count("-") <= 1

        self.project: str = project
        self.tag: str = tag
        self.sanitizer: Sanitizer = sanitizer
        self.patch: Union[None, str] = None
        self.sanitizer_report: Union[None, SanitizerReport] = None
        self.work_dir = ""
        self.language = ""

        if not skip_setup:
            assert self.setup(), f"Failed to setup {self}"
        else:
            self.sanitizer_report: Union[None, SanitizerReport] = parse(self.report, self.sanitizer)
            if self.sanitizer_report is None:
                self.patch = ""
                log.info(f"Do not detect sanitizer report for {self}, skip")

    def __str__(self):
        return f"[{self.project}, {self.tag}]"

    @property
    def commit(self) -> str:
        return self.tag if "-" not in self.tag else self.tag.split("-")[0]

    @property
    def path(self) -> str:
        return os.path.join(ROOT, self.project, self.tag)

    @property
    def immutable_project_path(self) -> str:
        return os.path.join(self.path, "immutable")

    @property
    def report_path(self) -> str:
        return os.path.join(self.path, "report.txt")

    @property
    def build_script_path(self) -> str:
        return os.path.join(ROOT, self.project, "build.sh")

    @property
    def exp_script_path(self) -> str:
        return os.path.join(self.path, "exp.sh")

    @property
    def poc_path(self) -> str:
        return os.path.join(self.path, "@POC@")

    @property
    def report(self) -> str:
        assert os.path.exists(self.report_path)
        with open(self.report_path) as f:
            return f.read()

    @property
    def issue_summary(self) -> str:
        assert self.sanitizer_report is not None
        return self.sanitizer_report.summary

    @property
    def issue_kind(self) -> str:
        return "sanitizer report"

    def build(self, *args, **kwargs) -> tuple[bool, str]:
        log.info(f"Building {self}")
        return skyset_tools.build(self.project, self.tag, self.sanitizer, *args, **kwargs)

    def test(self, *args, **kwargs) -> tuple[bool, str]:
        log.info(f"Testing {self}")
        return skyset_tools.test(self.project, self.tag, self.sanitizer, *args, **kwargs)
    
    def test_functional(self, *args, **kwargs) -> dict:
        log.info(f"Functional Testing {self}")
        return skyset_tools.test_functional(self.project, self.tag, *args, **kwargs)

    def setup(self) -> bool:
        if not os.path.exists(self.path):
            log.error(f"{self} '{self.path}' does not exist")
            return False

        if not os.path.exists(self.build_script_path):
            log.error(f"{self} build script does not exist")
            return False

        if not os.path.exists(self.exp_script_path):
            log.error(f"{self} exp script does not exist")
            return False

        if not os.path.exists(self.poc_path):
            log.error(f"{self} poc does not exist")
            return False

        if not os.path.exists(self.immutable_project_path) or not os.path.exists(self.report_path):
            self.build()
            if not os.path.exists(self.report_path):
                _, report = self.test()
                with open(self.report_path, "w") as f:
                    f.write(report)

        self.sanitizer_report = parse(self.report, self.sanitizer)
        if self.sanitizer_report is None:
            self.patch = ""
            log.info(f"Do not detect sanitizer report for {self}, skip")

        return True

    def validate(self, patch_path: str) -> tuple[bool, str]:
        log.info(f"Validating {self} with {patch_path}")

        ret, report = self.build(patch_path=patch_path)
        if not ret:
            return False, report

        ret, report = self.test(patch=True)
        ## HACK: the return code of test not means if the testing passed
        ## but just indicate if the test have been executed successfully

        if not ret:
            return False, report

        sanitizer_report = parse(report, self.sanitizer)
        if sanitizer_report is None:
            assert len(report) == 0, f"Failed to parse sanitizer report for {report}"
            if self.test_functional(patch_path=patch_path)["result"] != "passed":
                return False, "Functional test failed, please carefully check the patch"

            with open(patch_path) as f:
                log.info(f"Task {self} has been patched")
                self.patch = f.read()
            return True, ""

        return False, sanitizer_report.summary
