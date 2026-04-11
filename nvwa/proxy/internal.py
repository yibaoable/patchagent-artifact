import os
import math
import re
import tempfile
import clang.cindex
from clang.cindex import Config

for verion in range(16, 10, -1):
    path = f"/usr/lib/llvm-{verion}/lib/libclang.so.1"
    try:
        if os.path.exists(path):
            Config.set_library_file(path)
            break
    except:
        continue

from nvwa import lsp
from nvwa.logger import log
from nvwa.context import Context
from nvwa.proxy.utils import revise_patch, extract_cpp_function_name

MAX_VALIDATION_TRIES = 4
SOURCE_FILE_EXTENSIONS = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx")


def _is_secbench_task(task) -> bool:
    return getattr(task, "dataset", "") == "secbench"


def _locate_source_file(task, symbol: str) -> list[str]:
    if not _is_secbench_task(task):
        return []

    normalized = os.path.normpath(symbol).lstrip("/\\")
    if not normalized.lower().endswith(SOURCE_FILE_EXTENSIONS):
        return []

    project_root = task.immutable_project_path
    direct_path = os.path.join(project_root, normalized)
    if os.path.isfile(direct_path):
        return [f"{normalized.replace(os.sep, '/')}:{1}:{1}"]

    basename = os.path.basename(normalized)
    locations = []
    for root, _, files in os.walk(project_root):
        if basename not in files:
            continue
        realpath = os.path.join(root, basename)
        relative = os.path.relpath(realpath, project_root).replace(os.sep, "/")
        locations.append(f"{relative}:{1}:{1}")

    return sorted(set(locations))


def _iter_symbol_columns(line: str, symbol: str) -> list[int]:
    if not symbol:
        return []

    pattern = re.compile(rf"(?<![A-Za-z0-9_$]){re.escape(symbol)}(?![A-Za-z0-9_$])")
    return [match.start() + 1 for match in pattern.finditer(line)]


def _fallback_locations_from_viewcode(context: Context, path: str, start_line: int, end_line: int, symbol: str) -> list[str]:
    realpath = os.path.join(context.task.immutable_project_path, path)
    if not os.path.isfile(realpath):
        return []

    try:
        with open(realpath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError as exc:
        log.warning(f"Failed to read {realpath} for locate fallback: {exc}")
        return []

    location_set = set()
    last_line = min(end_line, len(lines))
    for line_no in range(max(1, start_line), last_line + 1):
        for column in _iter_symbol_columns(lines[line_no - 1], symbol):
            for loc in lsp.find_definition(context.task, path, line_no, column):
                location_set.add(loc)
    return list(location_set)

def viewcode(context: Context, path: str, start_line: int, end_line: int, auto_hint=False) -> tuple[dict, str]:
    total_lines = end_line - start_line + 1
    adjusted_lines = max(40, total_lines) - total_lines
    start_line = max(1, start_line - math.floor(adjusted_lines / 2))
    end_line = end_line + math.ceil(adjusted_lines / 2)
    path = path.lstrip("/")

    lines = lsp.viewcode(context.task, path, start_line, end_line)

    if lines is None:
        result = f"Sorry, the file {path} does not exist."
    else:
        end_line = min(end_line, start_line + len(lines) - 1)
        desc = f"Here is the code snippet from line {start_line} to line {end_line} in {path}:\n"
        
        # Default implementation:
        code = "".join(f"{start_line + i:{math.floor(math.log10(end_line)) + 1}}| {line}" for i, line in enumerate(lines))
        result = desc + code
        
        # Alternative implementation:
        # linum_len = math.floor(math.log10(end_line)) + 1
        # codelines = [f"{start_line + i:{linum_len}}| {line}" for i, line in enumerate(lines)]
        # stacktrace = context.task.sanitizer_report.stacktrace # type: ignore
        # path, line, column = stacktrace[0][1].split(":")
        # path, line, column = path.lstrip("/"), int(line), int(column)
        # if path == path and start_line <= line <= end_line:
        #     content = ''
        #     for idx, c in enumerate(codelines[line - start_line]):
        #         if idx == column + linum_len + 1:
        #             content += '^ Crash here'
        #         elif c == '\t' or c == '\n':
        #             content += c
        #         else:
        #             content += ' '
        #     codelines.insert(line - start_line, content)
        # result = desc + "".join(codelines)

        if auto_hint:
            for stack in context.task.sanitizer_report.get_all_stacktrace(): # type: ignore
                key_line = []
                for _, source in stack:
                    if source.lstrip("/").startswith(path):
                        line = int(source.split(":")[1])
                        if start_line <= line <= end_line and line not in key_line:
                            key_line.append(line)

                ## TODO:
                ## 1. If there are too many hints, we should sample some of them.
                ## 2. we should filter some intrinsic functions.
                for line in key_line:
                    line_content = lines[line - start_line]
                    hints = []
                    for column in range(len(line_content)):
                        if line_content[column].isalpha(): ## only consider the alphabetic characters    
                            hint = lsp.hover(context.task, path, line, column)
                            if hint is not None and len(hint) > 0 and hint not in hints:
                                hints.append(hint)
                    if len(hints) > 0:
                        result += (
                            "\nWe think the following hints might be helpful:\n"
                            f"The line {line} in {path} which appears in the stack trace is:\n{line_content}\n"
                            "Here are the definitions of the symbols in the line:\n"
                        )
                        for i, hint in enumerate(hints):
                            result += f"{i + 1}. {hint}\n"
                    else:
                        log.error(f"Failed to get hint for {path}:{line}")

    log.info(f"Called viewcode with path={path}, start_line={start_line}, end_line={end_line}")
    return {"path": path, "start_line": start_line, "end_line": end_line}, result


def locate(context: Context, symbol: str, auto_hint=False) -> tuple[dict, str]:
    def helper(context: Context, symbol: str) -> list[str]:
        fast_path_locations = lsp.locate_symbol(context.task, symbol)

        if len(fast_path_locations) != 1:
            for tool_calls in reversed(context.tool_calls):
                if tool_calls["name"] != "viewcode":
                    continue
                path, start_line, end_line = tool_calls["args"]["path"], tool_calls["args"]["start_line"], tool_calls["args"]["end_line"]
                realpath = os.path.join(context.task.immutable_project_path, path)
                if not os.path.isfile(realpath):
                    continue
                # Only use Clang for C/C++ files
                if context.task.language == "c":
                    try:
                        index = clang.cindex.Index.create()
                        tu = index.parse(realpath)

                        location_set = set()
                        for token in tu.get_tokens(extent=tu.cursor.extent):
                            if token.kind.name == "IDENTIFIER" and token.spelling == symbol and start_line <= token.location.line <= end_line:
                                for loc in lsp.find_definition(context.task, tool_calls["args"]["path"], token.location.line, token.location.column):
                                    location_set.add(loc)

                        if len(location_set) > 0:
                            return list(location_set)
                    except Exception as e:
                        log.warning(f"Failed to parse {realpath} with Clang: {e}")

                location_set = _fallback_locations_from_viewcode(context, path, start_line, end_line, symbol)
                if len(location_set) > 0:
                    return location_set

            for stack in context.task.sanitizer_report.get_all_stacktrace(): # type: ignore
                for idx, frame in enumerate(stack):
                    if symbol == extract_cpp_function_name(frame[0]):
                        if idx + 1 < len(stack):
                            path, line, column = stack[idx + 1][1].split(":")
                            path, line, column = path.lstrip("/"), int(line), int(column)
                            location = lsp.find_definition(context.task, path, line, column)
                            if len(location) > 0:
                                return location
                        else:
                            path, line, column = stack[idx][1].split(":")
                            realpath, line, column = os.path.join(context.task.immutable_project_path, path.lstrip("/")), int(line), int(column)
                            if os.path.exists(realpath):
                                with open(realpath) as f:
                                    lines = f.readlines()
                                for i in range(min(line, len(lines)) - 1, -1, -1):
                                    if symbol in lines[i]:
                                        location = lsp.find_definition(context.task, path.lstrip("/"), i + 1, lines[i].index(symbol) + 1)
                                        if len(location) > 0:
                                            return location

        return fast_path_locations

    original_symbol = symbol
    locations = _locate_source_file(context.task, original_symbol)
    if len(locations) == 0:
        symbol = extract_cpp_function_name(symbol) or symbol
        locations = helper(context, symbol)
    else:
        symbol = original_symbol

    if len(locations) > 1:
        if context.task.language == "c":
            log.purple(f"{symbol} has multiple definitions.")
        else:
            log.warning(f"There are multiple locating results for {symbol}: {locations}")
    elif len(locations) == 0:
        log.error(f"Failed to find the definition of {symbol}.")

    def format_location(location: str) -> str:
        if "::" in location:
            path_part, display_name = location.split("::", 1)
            return f"{path_part} ({display_name})"
        return location

    result = f"Here is the location of the symbol {symbol}:\n" + "\n".join(format_location(loc) for loc in locations)
    if len(locations) == 1 and auto_hint:
        path, line = locations[0].split(":")[:2]
        path, start_line, end_line = path.lstrip("/"), int(line), int(line)
        _, code = viewcode(context, path, start_line, end_line)
        result += f"\n\n{code}"

    log.info(f"Called locate with symbol={symbol}")
    return {"symbol": symbol}, result


def validate(context: Context, patch: str, auto_hint=False) -> tuple[dict, str]:
    num_tries = 0
    for tool_call in reversed(context.tool_calls):
        if tool_call["name"] != "validate":
            break
        num_tries += 1
    if num_tries >= MAX_VALIDATION_TRIES:
        log.error(f"The model has tried {num_tries} times continuously to validate the patch without viewing the code.")
        return {"patch": patch}, f"You have tried {num_tries} times to validate the patch continuously without viewing the code. Please check the code and try again."

    patch, _ = revise_patch(patch, context.task.immutable_project_path)

    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write(patch)
    ret, report = context.task.validate(f.name)

    header = "Congratulations! The patch is correct!" if ret else "Sorry, the patch is incorrect."
    patch_desc = f"Here is the patch:\n{patch}"
    report_desc = f"Here is the validation report:\n{report}"
    result = f"{header}\n{patch_desc}\n{report_desc}"

    log.info(f"Called validate with patch={repr(patch)}")
    return {"patch": patch}, result
