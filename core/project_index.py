"""
core/project_index.py — Project structure scanner, indexer, and symbol extractor.

Scans a project directory, applies ignore rules (.gitignore and built-in rules),
extracts symbols (Java, Python, JS/TS), detects languages and frameworks,
and provides compact tree generation.
"""

import fnmatch
import os
import re
import time
from typing import Dict, List, Optional, Set, Tuple


SUPPORTED_EXTENSIONS = {
    ".java", ".py", ".js", ".jsx", ".ts", ".tsx",
    ".html", ".css", ".json", ".xml", ".yml", ".yaml",
    ".sql", ".md", ".txt", ".properties", ".gradle",
    ".kts", ".sh", ".env.example",
}

IGNORED_DIR_NAMES = {
    ".git", "node_modules", "target", "build", "dist",
    "coverage", "__pycache__", ".venv", "venv", ".idea",
    ".vscode", ".next", "out", "tmp", "logs", ".cache",
    ".gradle", ".pytest_cache", ".mypy_cache",
}

IGNORED_EXTENSIONS = {
    ".class", ".pyc", ".pyo", ".exe", ".dll", ".so",
    ".dylib", ".bin", ".zip", ".tar", ".gz", ".7z",
    ".rar", ".png", ".jpg", ".jpeg", ".gif", ".ico",
    ".svg", ".mp4", ".mp3", ".wav", ".pdf", ".db",
    ".sqlite", ".sqlite3", ".jar", ".war", ".ear",
    ".o", ".obj", ".wasm",
}

SENSITIVE_FILENAMES = {
    ".env", ".env.local", ".env.production", ".env.development",
    ".env.test", ".env.staging", "id_rsa", "id_ed25519",
    "id_dsa", "id_ecdsa", "credentials.json", "auth.json",
    "token.json", "jwt.key", "private.pem", "server.key",
}

SENSITIVE_PATTERNS = [
    r".*\.pem$", r".*\.key$", r".*\.keystore$", r".*\.p12$",
    r".*\.pfx$", r".*\.crt$", r".*\.der$",
]

EXTENSION_LANGUAGE_MAP = {
    ".java": "Java",
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript (React)",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".html": "HTML",
    ".css": "CSS",
    ".json": "JSON",
    ".xml": "XML",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".sql": "SQL",
    ".md": "Markdown",
    ".txt": "Plain Text",
    ".properties": "Properties",
    ".gradle": "Gradle",
    ".kts": "Kotlin Script",
    ".sh": "Shell",
    ".env.example": "Config Example",
}

MAX_FILE_SIZE_BYTES = 1024 * 1024  # 1 MB max for indexed files


class ProjectFile:
    """Represents an indexed project file and its extracted metadata."""

    def __init__(
        self,
        relative_path: str,
        absolute_path: str,
        extension: str,
        size_bytes: int,
        modified_time: float,
        language: str,
        line_count: int = 0,
        symbols: Optional[List[dict]] = None,
    ):
        self.relative_path = relative_path
        self.absolute_path = absolute_path
        self.extension = extension
        self.size_bytes = size_bytes
        self.modified_time = modified_time
        self.language = language
        self.line_count = line_count
        self.symbols = symbols or []

    def to_dict(self) -> dict:
        return {
            "relative_path": self.relative_path,
            "absolute_path": self.absolute_path,
            "extension": self.extension,
            "size_bytes": self.size_bytes,
            "modified_time": self.modified_time,
            "language": self.language,
            "line_count": self.line_count,
            "symbols": self.symbols,
        }


def is_safe_boundary(base_dir: str, target_path: str) -> bool:
    """Verify that target_path resolves strictly inside base_dir (no escaping symlinks)."""
    try:
        base_real = os.path.realpath(base_dir)
        target_real = os.path.realpath(target_path)
        return (
            target_real == base_real
            or target_real.startswith(base_real + os.sep)
        )
    except Exception:
        return False


def is_sensitive_file(filename: str) -> bool:
    """Check if a file should never be automatically read or indexed into prompts."""
    base_name = os.path.basename(filename)
    if base_name in SENSITIVE_FILENAMES:
        return True
    for pat in SENSITIVE_PATTERNS:
        if re.match(pat, base_name, re.IGNORECASE):
            return True
    return False


def is_binary_file(file_path: str) -> bool:
    """Check if file appears to contain binary data."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(1024)
            if b"\x00" in chunk:
                return True
        return False
    except Exception:
        return True


def parse_gitignore(project_root: str) -> List[str]:
    """Parse .gitignore rules if present in the project root."""
    gitignore_path = os.path.join(project_root, ".gitignore")
    patterns = []
    if not os.path.isfile(gitignore_path):
        return patterns

    try:
        with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
    except Exception:
        pass
    return patterns


def matches_gitignore(rel_path: str, patterns: List[str], is_dir: bool = False) -> bool:
    """Check if a relative path matches any parsed gitignore pattern."""
    norm_path = rel_path.replace("\\", "/")
    basename = os.path.basename(norm_path)

    for pat in patterns:
        pat = pat.replace("\\", "/")
        dir_only = pat.endswith("/")
        clean_pat = pat.rstrip("/")

        if dir_only and not is_dir:
            continue

        if "/" not in clean_pat:
            if fnmatch.fnmatch(basename, clean_pat):
                return True
        else:
            clean_pat = clean_pat.lstrip("/")
            if fnmatch.fnmatch(norm_path, clean_pat) or fnmatch.fnmatch(norm_path, f"*/{clean_pat}"):
                return True
            if is_dir and fnmatch.fnmatch(f"{norm_path}/", f"{clean_pat}/"):
                return True
    return False


def extract_symbols(lines: List[str], extension: str) -> List[dict]:
    """Extract simple symbols (classes, functions, methods, annotations) via regex."""
    symbols = []
    ext = extension.lower()

    if ext == ".py":
        re_func = re.compile(r"^(?:async\s+)?def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(")
        re_class = re.compile(r"^class\s+([a-zA-Z_][a-zA-Z0-9_]*)\b")

        for idx, line in enumerate(lines, start=1):
            sline = line.strip()
            m_fn = re_func.match(sline)
            if m_fn:
                symbols.append({"name": m_fn.group(1), "type": "function", "line": idx})
                continue
            m_cl = re_class.match(sline)
            if m_cl:
                symbols.append({"name": m_cl.group(1), "type": "class", "line": idx})

    elif ext == ".java":
        re_class = re.compile(
            r"^\s*(?:public|protected|private)?\s*(?:static\s+)?(?:final\s+)?(?:abstract\s+)?class\s+([a-zA-Z_][a-zA-Z0-9_]*)\b"
        )
        re_interface = re.compile(
            r"^\s*(?:public|protected|private)?\s*interface\s+([a-zA-Z_][a-zA-Z0-9_]*)\b"
        )
        re_record = re.compile(
            r"^\s*(?:public|protected|private)?\s*record\s+([a-zA-Z_][a-zA-Z0-9_]*)\b"
        )
        re_enum = re.compile(
            r"^\s*(?:public|protected|private)?\s*enum\s+([a-zA-Z_][a-zA-Z0-9_]*)\b"
        )
        re_annot = re.compile(r"^\s*@([a-zA-Z_][a-zA-Z0-9_]*)\b")
        re_method = re.compile(
            r"^\s*(?:public|protected|private)\s+(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?(?:[\w\<\>\[\],\s\?]+)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^\)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{?"
        )

        for idx, line in enumerate(lines, start=1):
            sline = line.strip()
            if not sline or sline.startswith("//") or sline.startswith("/*") or sline.startswith("*"):
                continue

            m_cl = re_class.match(line)
            if m_cl:
                symbols.append({"name": m_cl.group(1), "type": "class", "line": idx})
                continue

            m_if = re_interface.match(line)
            if m_if:
                symbols.append({"name": m_if.group(1), "type": "interface", "line": idx})
                continue

            m_rc = re_record.match(line)
            if m_rc:
                symbols.append({"name": m_rc.group(1), "type": "record", "line": idx})
                continue

            m_en = re_enum.match(line)
            if m_en:
                symbols.append({"name": m_en.group(1), "type": "enum", "line": idx})
                continue

            m_an = re_annot.match(line)
            if m_an:
                symbols.append({"name": f"@{m_an.group(1)}", "type": "annotation", "line": idx})
                continue

            m_me = re_method.match(line)
            if m_me:
                name = m_me.group(1)
                if name not in ("if", "for", "while", "switch", "catch"):
                    symbols.append({"name": name, "type": "method", "line": idx})

    elif ext in (".js", ".jsx", ".ts", ".tsx"):
        re_func = re.compile(
            r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\("
        )
        re_class = re.compile(
            r"^(?:export\s+)?(?:default\s+)?class\s+([a-zA-Z_][a-zA-Z0-9_]*)\b"
        )
        re_arrow = re.compile(
            r"^(?:export\s+)?(?:const|let|var)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z_][a-zA-Z0-9_]*)\s*=>"
        )
        re_comp = re.compile(
            r"^(?:export\s+)?(?:const|let|var)\s+([A-Z][a-zA-Z0-9_]*)\s*=\s*(?:React\.)?(?:memo|forwardRef)\("
        )

        for idx, line in enumerate(lines, start=1):
            sline = line.strip()
            if not sline or sline.startswith("//") or sline.startswith("/*") or sline.startswith("*"):
                continue

            m_cl = re_class.match(sline)
            if m_cl:
                symbols.append({"name": m_cl.group(1), "type": "class", "line": idx})
                continue

            m_fn = re_func.match(sline)
            if m_fn:
                name = m_fn.group(1)
                stype = "react_component" if (name[0].isupper() and ext in (".jsx", ".tsx", ".js", ".ts")) else "function"
                symbols.append({"name": name, "type": stype, "line": idx})
                continue

            m_comp = re_comp.match(sline)
            if m_comp:
                symbols.append({"name": m_comp.group(1), "type": "react_component", "line": idx})
                continue

            m_ar = re_arrow.match(sline)
            if m_ar:
                name = m_ar.group(1)
                stype = "react_component" if (name[0].isupper() and ext in (".jsx", ".tsx")) else "function"
                symbols.append({"name": name, "type": stype, "line": idx})

    return symbols


class ProjectIndex:
    """Manages the full in-memory index of project files, symbols, and frameworks."""

    def __init__(self, project_root: str):
        self.project_root = os.path.realpath(os.path.abspath(project_root))
        self.project_name = os.path.basename(self.project_root) or "project"
        self.indexed_files: Dict[str, ProjectFile] = {}
        self.total_supported_files = 0
        self.total_ignored_files = 0
        self.last_updated = 0.0
        self.detected_languages: Set[str] = set()
        self.detected_frameworks: Set[str] = set()
        self.status = "INITIALIZING"

    def scan(self) -> dict:
        """Perform a full scan of the project directory."""
        if not os.path.isdir(self.project_root):
            self.status = "ERROR"
            return {"error": f"Project root does not exist: {self.project_root}"}

        self.status = "INDEXING"
        self.indexed_files.clear()
        self.detected_languages.clear()
        self.detected_frameworks.clear()
        self.total_supported_files = 0
        self.total_ignored_files = 0

        gitignore_patterns = parse_gitignore(self.project_root)

        for root, dirs, files in os.walk(self.project_root, followlinks=False):
            safe_dirs = []
            for d in dirs:
                dir_path = os.path.join(root, d)
                if not is_safe_boundary(self.project_root, dir_path):
                    self.total_ignored_files += 1
                    continue
                if d in IGNORED_DIR_NAMES:
                    self.total_ignored_files += 1
                    continue
                rel_dir = os.path.relpath(dir_path, self.project_root)
                if matches_gitignore(rel_dir, gitignore_patterns, is_dir=True):
                    self.total_ignored_files += 1
                    continue
                safe_dirs.append(d)
            dirs[:] = safe_dirs

            for f in files:
                file_path = os.path.join(root, f)
                rel_path = os.path.relpath(file_path, self.project_root).replace("\\", "/")

                if not is_safe_boundary(self.project_root, file_path):
                    self.total_ignored_files += 1
                    continue

                if matches_gitignore(rel_path, gitignore_patterns, is_dir=False):
                    self.total_ignored_files += 1
                    continue

                _, ext = os.path.splitext(f)
                ext = ext.lower()

                if ext in IGNORED_EXTENSIONS or is_sensitive_file(f):
                    self.total_ignored_files += 1
                    continue

                if ext not in SUPPORTED_EXTENSIONS:
                    self.total_ignored_files += 1
                    continue

                self.total_supported_files += 1

                try:
                    stat = os.stat(file_path)
                    size = stat.st_size
                    mtime = stat.st_mtime

                    if size > MAX_FILE_SIZE_BYTES or is_binary_file(file_path):
                        self.total_ignored_files += 1
                        continue

                    lines = []
                    try:
                        with open(file_path, "r", encoding="utf-8") as fp:
                            lines = fp.readlines()
                    except UnicodeDecodeError:
                        with open(file_path, "r", encoding="latin-1") as fp:
                            lines = fp.readlines()

                    language = EXTENSION_LANGUAGE_MAP.get(ext, "Code")
                    self.detected_languages.add(language)

                    symbols = extract_symbols(lines, ext)

                    pf = ProjectFile(
                        relative_path=rel_path,
                        absolute_path=file_path,
                        extension=ext,
                        size_bytes=size,
                        modified_time=mtime,
                        language=language,
                        line_count=len(lines),
                        symbols=symbols,
                    )
                    self.indexed_files[rel_path] = pf

                except Exception:
                    self.total_ignored_files += 1

        self._detect_frameworks()
        self.last_updated = time.time()
        self.status = "READY"

        return {
            "project_name": self.project_name,
            "root_path": self.project_root,
            "indexed_files": len(self.indexed_files),
            "supported_files": self.total_supported_files,
            "ignored_files": self.total_ignored_files,
            "languages": sorted(list(self.detected_languages)),
            "frameworks": sorted(list(self.detected_frameworks)),
            "status": self.status,
        }

    def _detect_frameworks(self):
        """Detect project frameworks based on manifest files and code signatures."""
        root_files = set(os.listdir(self.project_root)) if os.path.isdir(self.project_root) else set()

        has_pom = "pom.xml" in root_files
        has_gradle = "build.gradle" in root_files or "build.gradle.kts" in root_files
        if has_pom:
            self.detected_frameworks.add("Maven")
        if has_gradle:
            self.detected_frameworks.add("Gradle")

        is_spring = False
        if has_pom:
            pom_path = os.path.join(self.project_root, "pom.xml")
            try:
                with open(pom_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    if "spring-boot" in content or "org.springframework.boot" in content:
                        is_spring = True
            except Exception:
                pass
        if has_gradle and not is_spring:
            gradle_path = os.path.join(self.project_root, "build.gradle" if "build.gradle" in root_files else "build.gradle.kts")
            try:
                with open(gradle_path, "r", encoding="utf-8", errors="ignore") as f:
                    if "spring-boot" in f.read():
                        is_spring = True
            except Exception:
                pass

        if not is_spring:
            for pf in self.indexed_files.values():
                if pf.extension == ".java":
                    for sym in pf.symbols:
                        if sym.get("type") == "annotation" and sym.get("name") == "@SpringBootApplication":
                            is_spring = True
                            break
                if is_spring:
                    break

        if is_spring:
            self.detected_frameworks.add("Spring Boot")

        # Check package.json in root or indexed files
        pkg_paths = []
        if "package.json" in root_files:
            pkg_paths.append(os.path.join(self.project_root, "package.json"))
        for rel_p, pf in self.indexed_files.items():
            if rel_p.endswith("package.json") and pf.absolute_path not in pkg_paths:
                pkg_paths.append(pf.absolute_path)

        for pkg_path in pkg_paths:
            self.detected_frameworks.add("Node.js")
            try:
                with open(pkg_path, "r", encoding="utf-8", errors="ignore") as f:
                    pkg_text = f.read()
                    if '"react"' in pkg_text:
                        self.detected_frameworks.add("React")
                    if '"next"' in pkg_text:
                        self.detected_frameworks.add("Next.js")
                    if '"express"' in pkg_text:
                        self.detected_frameworks.add("Express")
            except Exception:
                pass

        vite_files = [f for f in root_files if f.startswith("vite.config.")]
        if vite_files:
            self.detected_frameworks.add("Vite")

        py_manifests = {"requirements.txt", "pyproject.toml", "setup.py", "Pipfile"}
        if py_manifests.intersection(root_files) or "Python" in self.detected_languages:
            self.detected_frameworks.add("Python")
            for m in ("requirements.txt", "pyproject.toml"):
                if m in root_files:
                    try:
                        with open(os.path.join(self.project_root, m), "r", encoding="utf-8", errors="ignore") as f:
                            text = f.read().lower()
                            if "fastapi" in text:
                                self.detected_frameworks.add("FastAPI")
                            if "flask" in text:
                                self.detected_frameworks.add("Flask")
                            if "django" in text:
                                self.detected_frameworks.add("Django")
                    except Exception:
                        pass


    def check_and_update_stale(self) -> int:
        """
        Check for modified or deleted files lazily.
        Returns the number of files refreshed.
        """
        refreshed = 0
        deleted_keys = []

        for rel_path, pf in list(self.indexed_files.items()):
            if not os.path.exists(pf.absolute_path):
                deleted_keys.append(rel_path)
                refreshed += 1
                continue

            try:
                mtime = os.path.getmtime(pf.absolute_path)
                if mtime > pf.modified_time:
                    lines = []
                    try:
                        with open(pf.absolute_path, "r", encoding="utf-8") as fp:
                            lines = fp.readlines()
                    except UnicodeDecodeError:
                        with open(pf.absolute_path, "r", encoding="latin-1") as fp:
                            lines = fp.readlines()

                    pf.size_bytes = os.path.getsize(pf.absolute_path)
                    pf.modified_time = mtime
                    pf.line_count = len(lines)
                    pf.symbols = extract_symbols(lines, pf.extension)
                    refreshed += 1
            except Exception:
                deleted_keys.append(rel_path)
                refreshed += 1

        for k in deleted_keys:
            if k in self.indexed_files:
                del self.indexed_files[k]

        if refreshed > 0:
            self.last_updated = time.time()

        return refreshed

    def generate_tree(self, max_depth: int = 3, max_entries: int = 80) -> str:
        """Generate a compact ASCII tree of the project structure."""
        if not os.path.isdir(self.project_root):
            return f"[Error] Directory not found: {self.project_root}"

        tree_lines = [f"{self.project_name}/"]
        entry_count = [0]
        truncated = [False]

        gitignore_patterns = parse_gitignore(self.project_root)

        def _walk(current_dir: str, prefix: str, depth: int):
            if depth > max_depth or truncated[0]:
                return

            try:
                entries = sorted(os.listdir(current_dir))
            except Exception:
                return

            dirs_list = []
            files_list = []

            for entry in entries:
                if entry in IGNORED_DIR_NAMES or is_sensitive_file(entry):
                    continue
                path = os.path.join(current_dir, entry)
                rel_path = os.path.relpath(path, self.project_root).replace("\\", "/")
                is_dir = os.path.isdir(path)

                if matches_gitignore(rel_path, gitignore_patterns, is_dir=is_dir):
                    continue

                if is_dir:
                    dirs_list.append(entry)
                else:
                    _, ext = os.path.splitext(entry)
                    if ext.lower() in SUPPORTED_EXTENSIONS or entry in ("pom.xml", "package.json", "Dockerfile"):
                        files_list.append(entry)

            combined = [(d, True) for d in dirs_list] + [(f, False) for f in files_list]
            total = len(combined)

            for i, (name, is_dir) in enumerate(combined):
                if entry_count[0] >= max_entries:
                    truncated[0] = True
                    return

                entry_count[0] += 1
                is_last = (i == total - 1)
                connector = "└── " if is_last else "├── "
                sub_prefix = "    " if is_last else "│   "

                if is_dir:
                    tree_lines.append(f"{prefix}{connector}{name}/")
                    _walk(os.path.join(current_dir, name), prefix + sub_prefix, depth + 1)
                else:
                    tree_lines.append(f"{prefix}{connector}{name}")

        _walk(self.project_root, "", 1)

        if truncated[0]:
            tree_lines.append(f"... (output truncated at {max_entries} entries, use /tree <depth> to adjust)")

        return "\n".join(tree_lines)
