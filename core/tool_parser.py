"""
core/tool_parser.py — Robust parser for model tool calls.

Detects, extracts, and normalizes tool calls from various model output formats:
  - <tool_call>...</tool_call>
  - <invoke>...</invoke>
  - <tool_code>...</tool_code>
  - <invoke><tool_code>...</tool_code></invoke>
  - ```json {"tool": ...} ```
  - Plain JSON {"tool": ...} or {"name": ...}
  - OpenAI-style {"type": "function", "function": ...} or [{"function": ...}]

Normalizes all output into:
  {
      "tool": "file_read",
      "args": { ... }
  }
"""

import json
import re
from typing import Any, Dict, Optional, Tuple

from core.tool_registry import registry

# Non-argument reserved keys in raw dictionaries
_RESERVED_KEYS = {
    "tool", "name", "tool_name", "function", "action",
    "type", "id", "tool_call_id", "thought", "thoughts", "reasoning"
}


def _extract_from_dict(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Helper to extract and normalize a tool call from a parsed dictionary."""
    if not isinstance(obj, dict):
        return None

    # Case 1: OpenAI style {"type": "function", "function": {"name": ..., "arguments": ...}}
    if "function" in obj and isinstance(obj["function"], dict):
        fn = obj["function"]
        tool_name = fn.get("name")
        args_raw = fn.get("arguments", {})
        if isinstance(args_raw, str):
            try:
                args = json.loads(args_raw)
            except Exception:
                args = {"raw_input": args_raw}
        elif isinstance(args_raw, dict):
            args = args_raw
        else:
            args = {}
        tool_obj = registry.get_tool(tool_name)
        canonical_name = tool_obj.name if tool_obj else tool_name
        return {"tool": canonical_name, "args": args}

    # Case 2: Standard {"tool": "...", ...} or {"name": "...", ...}
    tool_name = obj.get("tool") or obj.get("name") or obj.get("tool_name") or obj.get("action")
    if not tool_name or not isinstance(tool_name, str):
        return None

    # Check if tool_name is a known tool or alias in registry
    tool_obj = registry.get_tool(tool_name)
    if not tool_obj:
        # If the dict doesn't have an explicit 'tool' key and name isn't registered, skip
        if "tool" not in obj:
            return None
        canonical_name = tool_name
    else:
        canonical_name = tool_obj.name

    # Extract args
    args_raw = obj.get("args") or obj.get("parameters") or obj.get("arguments")
    if isinstance(args_raw, str):
        try:
            args = json.loads(args_raw)
        except Exception:
            args = {"raw_input": args_raw}
    elif isinstance(args_raw, dict):
        args = dict(args_raw)
    else:
        # Flattened args: all other keys in obj
        args = {k: v for k, v in obj.items() if k not in _RESERVED_KEYS}

    return {"tool": canonical_name, "args": args}


def parse_tool_call(raw: str) -> Optional[Dict[str, Any]]:
    """
    Parse a tool call from a model response string.
    Returns normalized dict {"tool": str, "args": dict} or None.
    """
    if not raw or not isinstance(raw, str):
        return None

    cleaned = raw.strip()

    # ----------------------------------------------------------------
    # 1. XML TAG PARSING
    # ----------------------------------------------------------------

    # <tool_call>...</tool_call>
    m = re.search(r"<tool_call>\s*(.*?)\s*</tool_call>", cleaned, re.DOTALL | re.IGNORECASE)
    if m:
        content = m.group(1).strip()
        parsed = _parse_json_or_fenced(content)
        if parsed:
            result = _extract_from_dict(parsed)
            if result:
                return result

    # <invoke><tool_code>...</tool_code></invoke> or <tool_code>...</tool_code>
    m = re.search(r"<tool_code>\s*(.*?)\s*</tool_code>", cleaned, re.DOTALL | re.IGNORECASE)
    if m:
        content = m.group(1).strip()
        parsed = _parse_json_or_fenced(content)
        if parsed:
            result = _extract_from_dict(parsed)
            if result:
                return result

    # <invoke>...</invoke>
    m = re.search(r"<invoke(?:\s+name=[\"']([^\"']+)[\"'])?>\s*(.*?)\s*</invoke>", cleaned, re.DOTALL | re.IGNORECASE)
    if m:
        name_attr = m.group(1)
        content = m.group(2).strip()
        parsed = _parse_json_or_fenced(content)
        if parsed:
            if name_attr and not parsed.get("tool"):
                parsed["tool"] = name_attr
            result = _extract_from_dict(parsed)
            if result:
                return result
        elif name_attr:
            # Maybe parameters like <parameter name="path">...</parameter>
            params = {}
            for p in re.finditer(r"<parameter\s+name=[\"']([^\"']+)[\"']>\s*(.*?)\s*</parameter>", content, re.DOTALL):
                params[p.group(1)] = p.group(2).strip()
            tool_obj = registry.get_tool(name_attr)
            return {"tool": tool_obj.name if tool_obj else name_attr, "args": params}

    # ----------------------------------------------------------------
    # 2. MARKDOWN FENCED CODE BLOCKS (```json ... ``` or ```xml ... ```)
    # ----------------------------------------------------------------
    for fenced in re.finditer(r"```(?:json|xml)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL):
        try:
            obj = json.loads(fenced.group(1))
            res = _extract_from_dict(obj)
            if res:
                return res
        except Exception:
            pass

    # ----------------------------------------------------------------
    # 3. DIRECT JSON OBJECT OR ARRAY
    # ----------------------------------------------------------------
    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            obj = json.loads(cleaned)
            res = _extract_from_dict(obj)
            if res:
                return res
        except Exception:
            pass

    if cleaned.startswith("[") and cleaned.endswith("]"):
        try:
            arr = json.loads(cleaned)
            if arr and isinstance(arr, list) and isinstance(arr[0], dict):
                res = _extract_from_dict(arr[0])
                if res:
                    return res
        except Exception:
            pass

    # ----------------------------------------------------------------
    # 4. SUBSTRING JSON EXTRACTION
    # ----------------------------------------------------------------
    # Search for {"tool": "..."} pattern anywhere in text
    tool_pat = re.search(r"(\{\s*\"(?:tool|action)\"\s*:\s*\"[^\"]+\".*?\})", cleaned, re.DOTALL)
    if tool_pat:
        try:
            obj = json.loads(tool_pat.group(1))
            res = _extract_from_dict(obj)
            if res:
                return res
        except Exception:
            pass

    # Search for registered tool names in json-like structure
    for tool in registry.list_tools():
        names = [tool.name] + tool.aliases
        for n in names:
            pattern = rf"(\{{\s*\"(?:name|tool)\"\s*:\s*\"{re.escape(n)}\".*?\}})"
            m_t = re.search(pattern, cleaned, re.DOTALL | re.IGNORECASE)
            if m_t:
                try:
                    obj = json.loads(m_t.group(1))
                    res = _extract_from_dict(obj)
                    if res:
                        return res
                except Exception:
                    pass

    return None


def _parse_json_or_fenced(text: str) -> Optional[Dict[str, Any]]:
    """Helper to parse JSON from text that might be surrounded by markdown fences."""
    t = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, re.DOTALL)
    candidate = fenced.group(1) if fenced else t
    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    # Try finding outer braces
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and start < end:
        try:
            data = json.loads(candidate[start:end + 1])
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return None


def has_tool_call(raw: str) -> bool:
    """Check if the text contains an identifiable tool call."""
    return parse_tool_call(raw) is not None


def strip_tool_markup(raw: str) -> str:
    """
    Remove tool markup (<tool_call>, <invoke>, etc.) and return
    any surrounding natural language.
    """
    if not raw:
        return ""
    text = raw
    # Remove XML blocks
    text = re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<invoke>.*?</invoke>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<tool_code>.*?</tool_code>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # If the remaining text is just a raw JSON tool call, strip it
    stripped = text.strip()
    if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("```json") and stripped.endswith("```")):
        parsed = parse_tool_call(stripped)
        if parsed:
            return ""

    return text.strip()
