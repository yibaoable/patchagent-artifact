LANGUAGE_PROMPT_EXAMPLES = {
    "c": {
	"viewcode_example": """```c
10| int check(char *string) {
11|     if (string == NULL) {
12|         return 0;
13|     }
14|     return !strcmp(string, \"hello\");
15| }
16|
17| int main(void) {
18|     char *string = NULL;
19|     check(string);
20|     return 0;
21| }
```""",
	"locate_example": "For C, if you want to find where `struct A` or `check` is defined, call `locate` with `symbol` set to `A` or `check`.",
	"patch_example": """```diff
--- a/foo.c
+++ b/foo.c
@@ -10,6 +10,9 @@ int check(char *string) {
+    if (string == NULL) {
+        return 0;
+    }
     return !strcmp(string, \"hello\");
 }
```
""",
	"patch_note": "Use C/C++ source paths such as `.c`, `.cc`, `.cpp`, `.h`, `.hpp` in headers and hunks.",
    },
    "java": {
    "viewcode_example": """```java
10| public class Checker {
11|     public static int check(String string) {
12|         if (string == null) {
13|             return 0;
14|         }
15|         return string.equals("hello") ? 1 : 0;
16|     }
17|
18|     public static void main(String[] args) {
19|         String string = null;
20|         check(string);
21|     }
22| }
```""",
    "locate_example": "For Java, if you want to find where `class Checker` or `check` method is defined, call `locate` with `symbol` set to `Checker` or `check`.",
    "patch_example": """```diff
--- a/Checker.java
+++ b/Checker.java
@@ -10,6 +10,9 @@ public static int check(String string) {
+    if (string == null) {
+        return 0;
+    }
    return string.equals("hello") ? 1 : 0;
}
```""",
    "patch_note": "Use Java source paths such as `.java` in headers and hunks.",
    },
    "python": {
        "viewcode_example": """```python
10| def check(string):
11|     if string is None:
12|         return 0
13|     return 1 if string == "hello" else 0
14|
15|
16| def main():
17|     string = None
18|     check(string)
19|
20| if __name__ == "__main__":
21|     main()
```""",
    "locate_example": "For Python, if you want to find where `check` is defined, call `locate` with `symbol` set to `check`.",
        "patch_example": 
"""```diff
--- a/example.py
+++ b/example.py
@@ -10,6 +10,9 @@ def check(string):
+    if string is None:
+        return 0
    return 1 if string == \"hello\" else 0
}
```""",
        "patch_note": "Use Python source paths such as `.py` in headers and hunks.",
    },
    "go": {
    "viewcode_example": """```go
10| package main
11|
12| func check(string string) int {
13|     if string == "" {
14|         return 0
15|     }
16|     if string == "hello" {
17|         return 1
18|     }
19|     return 0
20| }
21|
22| func main() {
23|     var s string
24|     check(s)
25| }
```""",
    "locate_example": "For Go, if you want to find where `check` is defined, call `locate` with `symbol` set to `check`.",
    "patch_example": """```diff
--- a/main.go
+++ b/main.go
@@ -12,6 +12,9 @@ func check(string string) int {
+    if string == \"\" {
+        return 0
+    }
    if string == \"hello\" {
        return 1
    }
```""",
    "patch_note": "Use Go source paths such as `.go` in headers and hunks.",
    },
    "javascript": {
    "viewcode_example": """```javascript
10| function check(string) {
11|     if (string === null) {
12|         return 0;
13|     }
14|     return string === "hello" ? 1 : 0;
15| }
16|
17| function main() {
18|     let string = null;
19|     check(string);
20| }
21|
22| main();
```""",
    "locate_example": "For JavaScript, if you want to find where `check` is defined, call `locate` with `symbol` set to `check`.",
    "patch_example": """```diff
--- a/example.js
+++ b/example.js
@@ -10,6 +10,9 @@ function check(string) {
+    if (string === null) {
+        return 0;
+    }
    return string === \"hello\" ? 1 : 0;
}
```""",
    "patch_note": "Use JavaScript source paths such as `.js`, `.jsx`, `.mjs` in headers and hunks.",
    },
    "typescript": {
    "viewcode_example": """```typescript
10| function check(string: string | null): number {
11|     if (string === null) {
12|         return 0;
13|     }
14|     return string === "hello" ? 1 : 0;
15| }
16|
17| function main(): void {
18|     let string: string | null = null;
19|     check(string);
20| }
21|
22| main();
```""",
    "locate_example": "For TypeScript, if you want to find where `check` is defined, call `locate` with `symbol` set to `check`.",
    "patch_example": """```diff
--- a/example.ts
+++ b/example.ts
@@ -10,6 +10,9 @@ function check(string: string | null): number {
+    if (string === null) {
+        return 0;
+    }
    return string === \"hello\" ? 1 : 0;
}
```""",
    "patch_note": "Use TypeScript source paths such as `.ts`, `.tsx` in headers and hunks.",
    }
}


def get_monkey_system_prompt(language: str) -> str:
    normalized_language = str(language or "").strip().lower()
    examples = LANGUAGE_PROMPT_EXAMPLES.get(normalized_language, LANGUAGE_PROMPT_EXAMPLES["c"])

    return f"""
Your task is to patch the bug in the program as identified by the provided bug context. Access the buggy codebase and the corresponding bug context. Depending on the dataset, the bug context may be a sanitizer report or a structured vulnerability description with likely vulnerable file locations. Your objective is to analyze and efficiently patch these issues.

Begin by reviewing the bug context to identify specific problems, such as null pointer dereferences, buffer overflows, or use-after-free errors. If the context includes candidate vulnerable file ranges, start there with `viewcode`. Then, delve into the codebase to locate the exact code sections where these issues occur. Understanding the context and functionality of the problematic code is crucial to determine the best fix. Consider whether the issues need simple corrections, like adjusting memory allocations or adding checks, or if they require a more significant overhaul of the logic.

After identifying solutions, modify the code accordingly, ensuring adherence to code language best practices. Test your patches thoroughly to confirm resolution of issues without introducing new ones. Document your changes clearly, explaining the necessity of each modification and how it addresses the specific problems identified by the sanitizer. Your goal is to enhance the codebase's security and stability while minimizing new bug risks.

You have 3 tools available: `viewcode`, `locate` and `validate`.
- `viewcode` allows you to view a code snippet from a file at a specific tag, helping you understand the project's internal logic rather than just using common patterns for bug fixes. You should provide 3 arguments:

1. path: the file path of the file you want to view. The patch is the relative path of the file to the project root directory. For example, if you want to view the file `foo.c` in the project root directory, the file path is `foo.c`. If you want to view the file `foo.c` in the directory `bar`, the file path is `bar/foo.c`.
2. start line: the start line of the code snippet you want to view.
3. end line: the end line of the code snippet you want to view.

The return value of `viewcode` includes line numbers prefixed on each line. Example:
{examples['viewcode_example']}

- `locate` is used to identify symbols. It can accurately pinpoint the location of a symbol, specifying the file and line number where it is defined. {examples['locate_example']}

You should provide 1 argument:

1. symbol: Specify the symbol (e.g., function name, struct name, variable name, etc.) whose location you wish to determine.

Using `locate` in conjunction with `viewcode` can significantly enhance your code navigation efficiency.

- `validate` is used to validate a patch. It replays the Proof of Concept (PoC) and checks if the sanitizer report is resolved. The patch should follow the format generated by the `git diff` command.

Patch format example:
{examples['patch_example']}
Patch format requirements:
1. `--- a/...` is the original file path and `+++ b/...` is the patched file path.
2. Hunk headers like `@@ -old_start,old_count +new_start,new_count @@` must be accurate.
3. Added lines must start with `+`, deleted lines with `-`, unchanged context lines with one leading space.
4. Each hunk should contain at least 3 lines of context before and after the edited region whenever possible.
5. Generate complete and valid patch text only; do not use placeholders like `...`.
"""


MONKEY_USER_PROMPT_TEMPLATE = """
I will send you the bug context for our program. I will give ten dollar tip for your assistance to create a patch for the identified issues. Your assistance is VERY IMPORTANT to the security research and can save thousands of lives. You can access the program's code using the provided tools. Now I want to patch the {project} program, the tag is {tag}, here is the {issue_kind}

{issue}

If the context provides a stack trace, use it to identify a fix point for the bug. If the context instead provides likely vulnerable file ranges, start by inspecting those ranges with `viewcode`. Do not forget the relationship between the failing logic and the function arguments. If you can generate a patch and confirm that it is correct, meaning the patch has no syntax or format errors, can fix the bug, and does not introduce new bugs, please generate the patch diff file. After generating the patch diff file, you MUST use the `validate` tool to validate the patch. Otherwise, you MUST continue to gather information using these tools.
{error_cases}
"""


MONKEY_USER_PROMPT_TEMPLATE_SINGLE_SHOT = """
I will send you the bug context for our program. I will give ten dollar tip for your assistance to create a patch for the identified issues. Your assistance is VERY IMPORTANT to the security research and can save thousands of lives. You can access the program's code using the provided tools. Now I want to patch the {project} program, the tag is {tag}, here is the {issue_kind}

{issue}

If the context provides a stack trace, use it to identify a fix point for the bug. If the context instead provides likely vulnerable file ranges, start by inspecting those ranges with `viewcode`. Do not forget the relationship between the failing logic and the function arguments.

## Single-shot validation mode
You can call `validate` at most once. After that call, the agent run ends immediately. So call `validate` only when you think your patch is good enough. The patch you submit is kept as the final patch even if validation fails. You may call `locate` and `viewcode` multiple times before the final validation.

If you can generate a patch and confirm that it is correct, meaning the patch has no syntax or format errors, can fix the bug, and does not introduce new bugs, please generate the patch diff file and use the `validate` tool exactly once at the end. Otherwise, you MUST continue to gather information using these tools.
{error_cases}
"""
