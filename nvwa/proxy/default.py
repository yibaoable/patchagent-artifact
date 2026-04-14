from langchain.tools import StructuredTool

from nvwa.context import Context
from nvwa.proxy import internal


def create_viewcode_tool(context: Context, auto_hint: bool = False) -> StructuredTool:
    def viewcode(path: str, start_line: int, end_line: int) -> str:
        """
        Returns the code snippet, the line number is attached to the head of each line.

        :param path: The path of the file.
        :param start_line: The start line of the code snippet.
        :param end_line: The end line of the code snippet.
        """

        args, result = internal.viewcode(context, path, start_line, end_line, auto_hint=auto_hint)
        context.add_tool_call("viewcode", args, result)
        return result

    return StructuredTool.from_function(viewcode)


def create_locate_tool(context: Context, auto_hint: bool = False) -> StructuredTool:
    def locate(symbol: str) -> str:
        """
        Returns the location of the symbol.

        :param symbol: The symbol to be located.
        """

        args, result = internal.locate(context, symbol)
        context.add_tool_call("locate", args, result)
        return result

    return StructuredTool.from_function(locate)


def create_validate_tool(
    context: Context, auto_hint: bool = False, return_direct: bool = False
) -> StructuredTool:
    def validate(patch: str) -> str:
        """
        Returns the validation result of the patch. The patch should be a multi-hunk patch, here is a example:
        ```diff
        --- a/src/OT/Layout/GDEF/GDEF.hh
        +++ b/src/OT/Layout/GDEF/GDEF.hh
        @@ -869,7 +869,7 @@ struct GDEF
                return v;

            v = table->get_glyph_props (glyph);
        -      if (likely (table)) // Don't try setting if we are the null instance!
        +      if (likely (table.get_blob ())) // Don't try setting if we are the null instance!
            glyph_props_cache.set (glyph, v);

            return v;
        ```

        :param patch: The patch to be validated.
        """

        args, result = internal.validate(context, patch, auto_hint=auto_hint)
        context.add_tool_call("validate", args, result)
        return result

    return StructuredTool.from_function(validate, return_direct=return_direct)
