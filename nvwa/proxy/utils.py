import re
import os
import string
from typing import Union

from nvwa.logger import log


def revise_patch(patch: str, project_path: str) -> tuple[str, bool]:
    def resolve_patch_path(file_path: str) -> tuple[str, bool]:
        normalized = os.path.normpath(file_path).lstrip("/\\")
        candidate = os.path.join(project_path, normalized)
        if os.path.exists(candidate):
            return normalized, False

        parts = [part for part in normalized.split(os.sep) if part not in ("", ".")]
        for idx in range(1, len(parts)):
            suffix = os.path.join(*parts[idx:])
            if os.path.exists(os.path.join(project_path, suffix)):
                return suffix, True

        return normalized, False

    def normalize_patch_paths(raw_patch: str) -> tuple[str, bool]:
        fixed = False
        normalized_lines = []

        for line in raw_patch.splitlines():
            if line.startswith("diff --git a/"):
                file_path_a, file_path_b = re.findall(r"diff --git a/(.*) b/(.*)", line)[0]
                fixed_file_path_a, fixed_a = resolve_patch_path(file_path_a)
                fixed_file_path_b, fixed_b = resolve_patch_path(file_path_b)
                fixed_file_path_a = os.path.normpath(fixed_file_path_a)
                fixed_file_path_b = os.path.normpath(fixed_file_path_b)
                fixed = fixed or fixed_a or fixed_b or file_path_a != fixed_file_path_a or file_path_b != fixed_file_path_b
                normalized_lines.append(f"diff --git a/{fixed_file_path_a} b/{fixed_file_path_b}")
            elif line.startswith("--- a/"):
                file_path = re.findall(r"--- a/(.*)", line)[0]
                fixed_file_path, changed = resolve_patch_path(file_path)
                fixed_file_path = os.path.normpath(fixed_file_path)
                fixed = fixed or changed or file_path != fixed_file_path
                normalized_lines.append(f"--- a/{fixed_file_path}")
            elif line.startswith("+++ b/"):
                file_path = re.findall(r"\+\+\+ b/(.*)", line)[0]
                fixed_file_path, changed = resolve_patch_path(file_path)
                fixed_file_path = os.path.normpath(fixed_file_path)
                fixed = fixed or changed or file_path != fixed_file_path
                normalized_lines.append(f"+++ b/{fixed_file_path}")
            else:
                normalized_lines.append(line)

        suffix = "\n" if raw_patch.endswith("\n") else ""
        return "\n".join(normalized_lines) + suffix, fixed

    def revise_hunk(lines: list[str], file_content: list[str]) -> tuple[str, bool]:
        orignal_line_number = sum(1 for line in lines[1:] if not line.startswith("+"))
        patched_line_number = sum(1 for line in lines[1:] if not line.startswith("-"))

        # @@ -3357,10 +3357,16 @@
        # extract the line number and the number of lines
        numbers = re.findall(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@", lines[0])[0]
        if numbers[0] != numbers[2]:
            fixed = True

        hunk = ""
        modified_line_number = None
        corrected_line_number = None

        search_start = max(1, int(numbers[0]) - 5)
        search_end = min(len(file_content) - orignal_line_number + 2, int(numbers[0]) + 6)
        for test_line_no in range(search_start, search_end):
            temp_hunk = ""
            temp_modified_line_number = 0
            line_number = test_line_no

            for line_no in range(1, len(lines)):
                if lines[line_no].startswith("-"):
                    if lines[line_no][1:].strip() != file_content[line_number - 1].strip():
                        temp_modified_line_number += 1
                    temp_hunk += "-" + file_content[line_number - 1]
                    line_number += 1
                elif lines[line_no].startswith("+"):
                    temp_hunk += lines[line_no] + "\n"
                else:
                    if lines[line_no].strip() != file_content[line_number - 1].strip():
                        temp_modified_line_number += 1
                    temp_hunk += " " + file_content[line_number - 1]
                    line_number += 1

            if modified_line_number is None or temp_modified_line_number < modified_line_number:
                modified_line_number = temp_modified_line_number
                corrected_line_number = test_line_no
                hunk = temp_hunk

        if corrected_line_number is None or modified_line_number is None:
            return "\n".join(lines) + "\n", False

        header = f"@@ -{corrected_line_number},{orignal_line_number} +{corrected_line_number},{patched_line_number} @@\n"
        fixed = (
            modified_line_number != 0
            or corrected_line_number != int(numbers[0])
            or orignal_line_number != int(numbers[1])
            or corrected_line_number != int(numbers[2])
            or patched_line_number != int(numbers[3])
        )

        return header + hunk, fixed

    def revise_block(lines: list[str]) -> tuple[list[str], bool]:
        cursor = 0
        fixed_lines = []
        block_fixed = False

        if lines[cursor].startswith("diff --git a/"):
            file_path_a, file_path_b = re.findall(r"diff --git a/(.*) b/(.*)", lines[cursor])[0]
            fixed_file_path_a, fixed_a = resolve_patch_path(file_path_a)
            fixed_file_path_b, fixed_b = resolve_patch_path(file_path_b)
            fixed_file_path_a = os.path.normpath(fixed_file_path_a)
            fixed_file_path_b = os.path.normpath(fixed_file_path_b)
            block_fixed = block_fixed or fixed_a or fixed_b or file_path_a != fixed_file_path_a or file_path_b != fixed_file_path_b
            fixed_lines.append(f"diff --git a/{fixed_file_path_a} b/{fixed_file_path_b}\n")
            cursor += 1

        while cursor < len(lines) and not lines[cursor].startswith("--- a/"):
            fixed_lines.append(lines[cursor] + "\n")
            cursor += 1

        file_path_a = re.findall(r"--- a/(.*)", lines[cursor])[0]
        file_path_b = re.findall(r"\+\+\+ b/(.*)", lines[cursor + 1])[0]
        fixed_file_path_a, fixed_a = resolve_patch_path(file_path_a)
        fixed_file_path_b, fixed_b = resolve_patch_path(file_path_b)
        fixed_file_path_a = os.path.normpath(fixed_file_path_a)
        fixed_file_path_b = os.path.normpath(fixed_file_path_b)
        block_fixed = block_fixed or file_path_a != fixed_file_path_a or file_path_b != fixed_file_path_b or fixed_a or fixed_b

        assert file_path_a == file_path_b and fixed_file_path_a == fixed_file_path_b
        fixed_lines += [
            f"--- a/{fixed_file_path_a}\n",
            f"+++ b/{fixed_file_path_b}\n",
        ]

        with open(os.path.join(project_path, fixed_file_path_a), "r") as f:
            file_content = f.readlines()

        last_line = -1
        for line_no in range(cursor + 2, len(lines)):
            if lines[line_no].startswith("@@"):
                if last_line != -1:
                    hunk_lines, hunk_fixed = revise_hunk(lines[last_line:line_no], file_content)
                    fixed_lines.append(hunk_lines)
                    block_fixed = block_fixed or hunk_fixed
                last_line = line_no
        if last_line != -1:
            hunk_lines, hunk_fixed = revise_hunk(lines[last_line:], file_content)
            fixed_lines.append(hunk_lines)
            block_fixed = block_fixed or hunk_fixed

        return fixed_lines, block_fixed

    normalized_patch, normalized_fixed = normalize_patch_paths(patch)
    try:
        lines = normalized_patch.splitlines()
        fixed_lines = []

        last_line = -1
        fixed = normalized_fixed
        for line_no in range(len(lines)):
            if lines[line_no].startswith("diff --git a/"):
                if last_line != -1:
                    block_lines, block_fixed = revise_block(lines[last_line:line_no])
                    fixed_lines += block_lines
                    fixed = fixed or block_fixed
                last_line = line_no
            elif lines[line_no].startswith("--- a/") and last_line == -1:
                last_line = line_no
        if last_line != -1:
            block_lines, block_fixed = revise_block(lines[last_line:])
            fixed_lines += block_lines
            fixed = fixed or block_fixed

        if len(fixed_lines) == 0:
            return normalized_patch, normalized_fixed
        return "".join(fixed_lines), fixed
    except Exception:
        log.warning("Failed to revise patch")
        return normalized_patch, normalized_fixed


def extract_cpp_function_name(function_name: str) -> Union[str, None]:
    def remove_bracket_pairs(s: str, left: str, right: str) -> str:
        last_parenthesis = s.rfind(right)
        balance = 1
        for i in range(last_parenthesis - 1, -1, -1):
            if s[i] == right:
                balance += 1
            elif s[i] == left:
                balance -= 1
            if balance == 0:
                return s[:i]

        return s

    result = function_name
    if ")" in result:
        result = remove_bracket_pairs(result, "(", ")")
    if ">" in result:
        result = remove_bracket_pairs(result, "<", ">")
    if "::" in result:
        result = result.split("::")[-1]
    if " " in result:
        result = result.split(" ")[-1]

    ident_chars = string.ascii_letters + string.digits + "_~"

    if re.match(r"operator\s*[\(\+\-\*\&\|\^!~<>=]", result):
        return None

    if any(c not in ident_chars for c in result) or len(result) == 0:
        log.warning(f"Failed to extract function name from '{function_name}' (result: '{result})'")

    return result
