"""
core/tool_registry.py — Tool registry and schema definitions for AIZEN native tool execution.

Defines supported tools, their parameter schemas, and system prompt generation.
Supported tools:
  - file_read
  - file_write
  - file_search
  - list_files
  - run_command
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]
    aliases: List[str] = field(default_factory=list)


# ------------------------------------------------------------------
# BUILT-IN TOOL DEFINITIONS
# ------------------------------------------------------------------

_BUILTIN_TOOLS: List[Tool] = [
    Tool(
        name="file_read",
        description="Read the text content of a file within the project directory. Supports optional line range slicing.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read (relative to project root or current working directory)."
                },
                "start_line": {
                    "type": "integer",
                    "description": "Optional 1-based start line number to begin reading from."
                },
                "end_line": {
                    "type": "integer",
                    "description": "Optional 1-based end line number (inclusive) to stop reading at."
                }
            },
            "required": ["path"]
        },
        aliases=["read_file", "view_file", "cat"]
    ),
    Tool(
        name="file_write",
        description="Write text content to a file in the project directory. Creates parent directories if needed.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Target file path (relative to project root)."
                },
                "content": {
                    "type": "string",
                    "description": "The exact text content to write to the file."
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Whether to overwrite if file already exists (default: true)."
                }
            },
            "required": ["path", "content"]
        },
        aliases=["write_file", "save_file"]
    ),
    Tool(
        name="file_search",
        description="Search for a text or regex pattern across files in the project directory.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Text substring or regex pattern to search for."
                },
                "path": {
                    "type": "string",
                    "description": "Subdirectory to search in (default: current directory '.')."
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Whether search is case-sensitive (default: false)."
                }
            },
            "required": ["pattern"]
        },
        aliases=["search_files", "grep", "grep_search", "find_in_files"]
    ),
    Tool(
        name="list_files",
        description="List files and directories within a directory in the project.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to list (default: '.')."
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Whether to list subdirectories recursively (default: false)."
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum recursion depth when recursive is true (default: 2)."
                }
            },
            "required": []
        },
        aliases=["list_dir", "ls", "dir"]
    ),
    Tool(
        name="run_command",
        description="Execute a safe shell command on the host system. Subject to safety classification and user confirmation for destructive commands.",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The exact shell command line string to execute."
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for the command (default: '.')."
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds before terminating the process (default: 60)."
                }
            },
            "required": ["command"]
        },
        aliases=["terminal", "bash", "shell", "execute_command", "cmd"]
    ),
]


# ------------------------------------------------------------------
# REGISTRY CLASS
# ------------------------------------------------------------------

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._alias_map: Dict[str, str] = {}
        for t in _BUILTIN_TOOLS:
            self.register(t)

    def register(self, tool: Tool):
        """Register a tool and its aliases."""
        self._tools[tool.name] = tool
        self._alias_map[tool.name.lower()] = tool.name
        for alias in tool.aliases:
            self._alias_map[alias.lower()] = tool.name

    def get_tool(self, name_or_alias: str) -> Optional[Tool]:
        """Retrieve tool by canonical name or alias."""
        if not name_or_alias:
            return None
        cleaned = name_or_alias.strip().lower()
        canonical = self._alias_map.get(cleaned)
        if canonical:
            return self._tools.get(canonical)
        return self._tools.get(name_or_alias)

    def has_tool(self, name_or_alias: str) -> bool:
        """Check if tool exists."""
        return self.get_tool(name_or_alias) is not None

    def list_tools(self) -> List[Tool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def get_schemas(self) -> List[Dict[str, Any]]:
        """Return JSON-compatible schemas of all registered tools."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in self._tools.values()
        ]

    def get_tools_prompt(self) -> str:
        """Generate a prompt instruction detailing available tools and invocation formats."""
        lines = [
            "## Native Tool Capabilities",
            "You have access to native local tools to inspect files, search code, list directories, and execute commands.",
            "Available tools:"
        ]
        for t in self._tools.values():
            req = t.parameters.get("required", [])
            req_str = f" [required: {', '.join(req)}]" if req else ""
            lines.append(f"- **`{t.name}`**: {t.description}{req_str}")

        lines.extend([
            "",
            "### How to call a tool",
            "When you need information or to perform an action, invoke a tool using either of the following formats:",
            "",
            "Format 1 (XML block):",
            "<tool_call>",
            '{"tool": "file_read", "args": {"path": "graphify-out/GRAPH_REPORT.md"}}',
            "</tool_call>",
            "",
            "Format 2 (JSON block):",
            '{"tool": "file_read", "args": {"path": "graphify-out/GRAPH_REPORT.md"}}',
            "",
            "Rules for tool calling:",
            "1. Output ONLY the tool call when you need tool results. Do not wrap in conversational fluff.",
            "2. The tool result will be executed and returned to you automatically.",
            "3. Once you receive the tool result, answer the user in natural language without raw tool markup."
        ])
        return "\n".join(lines)


# Global registry singleton
registry = ToolRegistry()
