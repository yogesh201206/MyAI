"""
core/project_search.py — Relevance ranking, content retrieval, and context formatting.

Provides:
- find_in_project(): Fast multi-signal search for /find command
- retrieve_project_context(): Automated retrieval and snippet extraction for AI prompt injection
"""

import os
import re
from typing import Dict, List, Optional, Set, Tuple

STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "up", "about", "into", "over",
    "after", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "can", "could", "should",
    "would", "may", "might", "must", "will", "shall", "what", "which",
    "who", "whom", "this", "that", "these", "those", "am", "it", "its",
    "why", "how", "where", "when", "there", "here", "explain", "find",
    "show", "tell", "give", "code", "file", "project", "return", "please",
}


def tokenize_query(query: str) -> List[str]:
    """Extract significant keywords from a user query, preserving camelCase and snake_case tokens."""
    raw_tokens = re.findall(r"[a-zA-Z0-9_\-\.]+", query)
    tokens = []

    for t in raw_tokens:
        clean = t.strip(".-_")
        if not clean:
            continue
        lower = clean.lower()
        if lower in STOP_WORDS and len(clean) < 8:
            continue
        tokens.append(clean)
        # Also split camelCase tokens (e.g. JwtAuthenticationFilter -> Jwt, Authentication, Filter)
        camel_parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+", clean)
        if len(camel_parts) > 1:
            for cp in camel_parts:
                if cp.lower() not in STOP_WORDS and len(cp) > 1:
                    tokens.append(cp)

    # De-duplicate while preserving order
    seen = set()
    result = []
    for t in tokens:
        low = t.lower()
        if low not in seen:
            seen.add(low)
            result.append(t)
    return result


def find_in_project(project_index, query: str, limit: int = 20) -> List[dict]:
    """
    Search indexed project files by filename, path, symbols, and text content.
    Returns ranked matches for the /find command.
    """
    if not project_index or not project_index.indexed_files:
        return []

    q_clean = query.strip()
    if not q_clean:
        return []

    q_lower = q_clean.lower()
    matches = []

    for rel_path, pf in project_index.indexed_files.items():
        base_name = os.path.basename(rel_path).lower()
        name_no_ext, _ = os.path.splitext(base_name)

        # 1. Exact or partial filename match
        if q_lower == base_name or q_lower == name_no_ext:
            matches.append({
                "file": rel_path,
                "line": 1,
                "match_type": "Exact Filename",
                "preview": rel_path,
                "score": 100.0,
            })
        elif q_lower in base_name:
            matches.append({
                "file": rel_path,
                "line": 1,
                "match_type": "Filename",
                "preview": rel_path,
                "score": 70.0,
            })
        elif q_lower in rel_path.lower():
            matches.append({
                "file": rel_path,
                "line": 1,
                "match_type": "Path",
                "preview": rel_path,
                "score": 40.0,
            })

        # 2. Symbol matches
        for sym in pf.symbols:
            sym_name = sym.get("name", "")
            sym_type = sym.get("type", "symbol")
            sym_line = sym.get("line", 1)
            sym_lower = sym_name.lower()

            if q_lower == sym_lower or q_lower == sym_lower.lstrip("@"):
                matches.append({
                    "file": rel_path,
                    "line": sym_line,
                    "match_type": f"Symbol ({sym_type})",
                    "preview": f"{sym_type} {sym_name}",
                    "score": 90.0,
                })
            elif q_lower in sym_lower:
                matches.append({
                    "file": rel_path,
                    "line": sym_line,
                    "match_type": f"Symbol ({sym_type})",
                    "preview": f"{sym_type} {sym_name}",
                    "score": 60.0,
                })

        # 3. Content line matches (up to 3 matches per file to avoid swamping)
        try:
            if os.path.exists(pf.absolute_path):
                content_matches = 0
                with open(pf.absolute_path, "r", encoding="utf-8", errors="ignore") as f:
                    for idx, line in enumerate(f, start=1):
                        if q_lower in line.lower():
                            matches.append({
                                "file": rel_path,
                                "line": idx,
                                "match_type": "Content",
                                "preview": line.strip()[:100],
                                "score": 30.0,
                            })
                            content_matches += 1
                            if content_matches >= 3:
                                break
        except Exception:
            pass

    # Sort descending by score, then line number
    matches.sort(key=lambda m: (-m["score"], m["file"], m["line"]))

    # Deduplicate matches on (file, line)
    seen_locs = set()
    ranked_matches = []
    for m in matches:
        loc = (m["file"], m["line"])
        if loc not in seen_locs:
            seen_locs.add(loc)
            m["rank"] = len(ranked_matches) + 1
            ranked_matches.append(m)
            if len(ranked_matches) >= limit:
                break

    return ranked_matches


def retrieve_project_context(
    project_index,
    query: str,
    max_tokens: int = 2500
) -> Tuple[str, List[dict]]:
    """
    Automatically identify relevant project files, extract code sections,
    and format them for injection into the model context.
    """
    if not project_index or not project_index.indexed_files:
        return "", []

    tokens = tokenize_query(query)
    if not tokens:
        return "", []

    file_scores: Dict[str, float] = {}
    file_hit_lines: Dict[str, Set[int]] = {}
    file_matched_symbols: Dict[str, List[dict]] = {}

    for rel_path, pf in project_index.indexed_files.items():
        base_name = os.path.basename(rel_path).lower()
        name_no_ext, _ = os.path.splitext(base_name)
        score = 0.0
        hit_lines = set()
        matched_symbols = []

        for token in tokens:
            t_low = token.lower()

            # Filename exact match
            if t_low == base_name or t_low == name_no_ext:
                score += 120.0
                hit_lines.add(1)
            elif t_low in base_name:
                score += 50.0
                hit_lines.add(1)
            elif t_low in rel_path.lower():
                score += 25.0

            # Symbol match
            for sym in pf.symbols:
                s_name = sym.get("name", "").lower()
                s_line = sym.get("line", 1)
                if t_low == s_name or t_low == s_name.lstrip("@"):
                    score += 80.0
                    hit_lines.add(s_line)
                    matched_symbols.append(sym)
                elif t_low in s_name:
                    score += 40.0
                    hit_lines.add(s_line)
                    matched_symbols.append(sym)

        # Content keyword scan
        try:
            if os.path.exists(pf.absolute_path):
                matched_tokens = set()
                with open(pf.absolute_path, "r", encoding="utf-8", errors="ignore") as f:
                    for idx, line in enumerate(f, start=1):
                        l_low = line.lower()
                        for token in tokens:
                            t_low = token.lower()
                            if t_low in l_low:
                                matched_tokens.add(t_low)
                                score += 3.0
                                hit_lines.add(idx)
                score += len(matched_tokens) * 15.0
        except Exception:
            pass

        if score >= 10.0:
            file_scores[rel_path] = score
            file_hit_lines[rel_path] = hit_lines
            file_matched_symbols[rel_path] = matched_symbols

    if not file_scores:
        return "", []

    # Sort files by score descending
    sorted_files = sorted(file_scores.keys(), key=lambda k: file_scores[k], reverse=True)

    # Budget context tokens (1 token approx 4 characters)
    max_chars = max_tokens * 4
    instructions_len = 320
    content_budget = max(50, max_chars - instructions_len)
    current_chars = 0
    context_chunks = []
    used_sources = []

    for rel_path in sorted_files[:4]:  # Top 4 files max
        if current_chars >= content_budget:
            break

        pf = project_index.indexed_files[rel_path]
        try:
            with open(pf.absolute_path, "r", encoding="utf-8", errors="ignore") as f:
                all_lines = f.readlines()
        except Exception:
            continue

        total_lines = len(all_lines)
        if total_lines == 0:
            continue

        hits = sorted(list(file_hit_lines.get(rel_path, {1})))
        primary_hit = hits[0] if hits else 1

        if total_lines <= 50 and (current_chars + pf.size_bytes <= content_budget):
            start_line = 1
            end_line = total_lines
        else:
            start_line = max(1, primary_hit - 10)
            end_line = min(total_lines, primary_hit + 15)

        selected_lines = [
            f"{i}: {all_lines[i - 1].rstrip()}"
            for i in range(start_line, end_line + 1)
        ]

        # Truncate lines if necessary to fit in content_budget
        while selected_lines and (current_chars + sum(len(l) + 1 for l in selected_lines) + 80 > content_budget):
            selected_lines.pop()

        if not selected_lines:
            if not context_chunks:
                selected_lines = [f"{start_line}: {all_lines[start_line - 1].rstrip()[:80]}"]
            else:
                break

        code_block = "\n".join(selected_lines)
        actual_end = start_line + len(selected_lines) - 1
        chunk_text = (
            f"File: {rel_path}\n"
            f"Lines: {start_line}-{actual_end}\n"
            f"```\n{code_block}\n```\n"
            f"--- END FILE ---"
        )

        context_chunks.append(chunk_text)
        current_chars += len(chunk_text)
        used_sources.append({
            "file": rel_path,
            "lines": f"{start_line}-{actual_end}",
            "score": round(file_scores[rel_path], 1),
            "language": pf.language,
        })


    if not context_chunks:
        return "", []

    full_context = (
        f"[PROJECT CONTEXT]\n"
        f"Project: {project_index.project_name}\n\n"
        + "\n\n".join(context_chunks)
        + "\n\n[END PROJECT CONTEXT]\n\n"
        "Instructions for Project Context:\n"
        "- Base your answer on the retrieved project files above when relevant.\n"
        "- Reference specific files and line numbers (e.g. `SecurityConfig.java:42` or `SecurityConfig.java`).\n"
        "- Do NOT invent line numbers if not certain.\n"
        "- Do NOT assume missing code exists unless standard for the detected framework."
    )

    return full_context, used_sources
