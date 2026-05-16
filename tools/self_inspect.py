import ast
import os
import sys
import re


# Files to always include
CORE_FILES = [
    "nova_assistant_v1.py",
    "nova_ai.py",
    "nova_router.py",
    "nova_manager.py",
    "nova_tts.py",
    "nova_whisper.py",
    "nova_widgets.py",
    "nova_selfimprove_ui.py",
    "agent_executor.py",
    "planner.py",
    "code_execution_loop.py",
    "mistake_memory.py",
    "Internet_Tools.py",
    "latex_window.py",
    "code_window.py",
    "code_display.py",
    "theme_manager.py",
    "self_improver.py",
    "paper_tools_window.py",
    "asr_whisper.py",
    "nova_web.py",
    "nova_memory.py",
    "nova_council.py",
    "nova_affect.py",
    "tools/geometry_tool.py",
    "nova_math_researcher.py",
    "nova_research_hooks.py",
    "personality_routes.py",
    "personality_manager.py",
    "nova_chemistry_researcher.py",
    "document_reader.py",
    "math_speech.py",
    "tools/read_log.py",
    "nova_log_buffer.py",
]

SCAN_DIRS = [
    "tools",
]

SKIP_FILES = {
    "tool_registry.py",
    "__init__.py",
}


def _get_project_root():
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def _read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"# ERROR reading {path}: {e}"


def _collect_sources(root):
    """Collect all relevant source files with labelled headers."""
    sections = []

    found   = [f for f in CORE_FILES if os.path.exists(os.path.join(root, f))]
    missing = [f for f in CORE_FILES if not os.path.exists(os.path.join(root, f))]
    print(f"[SELF_INSPECT] Root: {root}")
    print(f"[SELF_INSPECT] Found: {found}")
    print(f"[SELF_INSPECT] Missing: {missing}")

    for fname in CORE_FILES:
        path = os.path.join(root, fname)
        if os.path.exists(path):
            source = _read_file(path)
            sections.append(f"{'='*60}\nFILE: {fname}\n{'='*60}\n{source}")

    for subdir in SCAN_DIRS:
        dirpath = os.path.join(root, subdir)
        if not os.path.isdir(dirpath):
            continue
        for fname in sorted(os.listdir(dirpath)):
            if not fname.endswith(".py"):
                continue
            if fname in SKIP_FILES or fname.startswith("_"):
                continue
            path = os.path.join(dirpath, fname)
            source = _read_file(path)
            sections.append(f"{'='*60}\nFILE: {subdir}/{fname}\n{'='*60}\n{source}")

    return "\n\n".join(sections)


def _extract_sigs(source: str) -> list:
    """
    Extract def/class/async def lines using AST parsing.
    Immune to docstrings containing 'def' or 'class' keywords.
    Falls back to a multiline-string-aware scanner for unparseable fragments.
    """
    try:
        tree = ast.parse(source)
        definition_linenos = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                definition_linenos.add(node.lineno)
        source_lines = source.splitlines()
        return [source_lines[i - 1] for i in sorted(definition_linenos)]

    except SyntaxError:
        result = []
        in_multiline = False
        delim = None
        for line in source.splitlines():
            stripped = line.strip()
            for d in ('"""', "'''"):
                if stripped.count(d) % 2 == 1:
                    if not in_multiline:
                        in_multiline, delim = True, d
                    elif delim == d:
                        in_multiline, delim = False, None
                    break
            if not in_multiline and stripped.startswith(("def ", "class ", "async def ")):
                result.append(line)
        return result


def _build_method_index(full_source: str) -> dict:
    """
    Parse all file sections and build a name → (body, filename, lineno) index.
    Tracks filename across adjacent header/source sections.
    """
    index = {}
    current_fname = "unknown"

    for section in full_source.split("=" * 60):
        if not section.strip():
            continue

        file_match = re.match(r'\nFILE: (.+?)\n', section)
        if file_match:
            current_fname = file_match.group(1).strip()
            continue  # header-only section, no code to parse

        try:
            tree = ast.parse(section)
            section_lines = section.splitlines()

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    start = node.lineno - 1
                    end   = node.end_lineno
                    body  = "\n".join(section_lines[start:end])
                    name  = node.name

                    if name not in index or len(body) > len(index[name][0]):
                        index[name] = (body, current_fname, node.lineno)

        except SyntaxError:
            pass

    return index


def self_inspect(query=None):
    """
    Read Nova's entire source tree to answer questions about how it works.
    Covers nova_assistant.py, agent_executor.py, planner.py, and all tools/.
    """
    try:
        root = _get_project_root()
        full_source = _collect_sources(root)
        lines = full_source.splitlines()

        method_index = _build_method_index(full_source)

        if not query:
            sigs = _extract_sigs(full_source)
            return "SELF_INSPECT_SIGS:" + "\n".join(s.strip() for s in sigs)

        # ── Scan-all mode ──────────────────────────────────────────────────
        broad_triggers = ["scan all", "diagnose all", "inspect all",
                          "overall", "architecture", "everything",
                          "all files", "whole system", "full picture"]
        if any(t in query.strip().lower() for t in broad_triggers):
            sections = []
            seen_files = {}

            for name, (body, fname, lineno) in method_index.items():
                if fname not in seen_files:
                    seen_files[fname] = []
                sig = body.splitlines()[0] if body else f"def {name}:"
                seen_files[fname].append((sig, lineno))

            for fname, sigs in seen_files.items():
                sigs.sort(key=lambda x: x[1])  # sort by line number

                section = f"### `{fname}`\n```\n"
                section += "\n".join(s[0] for s in sigs)
                section += "\n```"
                sections.append(section)

            combined = "\n\n".join(sections)
            return (
                f"SELF_INSPECT:{query}||SCAN_ALL: {len(method_index)} methods across {len(seen_files)} files\n\n"
                f"{combined}"
            )

        # ── Filename direct-open mode ──────────────────────────────────────
        query_stripped = query.strip().lower()
        matched_file = None

        for fname in CORE_FILES:
            fname_lower = fname.lower()
            fname_stem  = os.path.splitext(fname_lower)[0]
            if fname_lower in query_stripped or fname_stem in query_stripped:
                matched_file = fname
                break

        if matched_file:
            path = os.path.join(root, matched_file)
            if os.path.exists(path):
                source = _read_file(path)
                return (
                    f"SELF_INSPECT:{query}||FILE:{matched_file}\n"
                    f"{source}"
                )
            else:
                return (
                    f"SELF_INSPECT:{query}||FILE_NOT_FOUND: "
                    f"{matched_file} is in manifest but missing on disk."
                )

        # ── Single method lookup ───────────────────────────────────────────
        words = re.findall(r'[\w_]+', query)
        words_sorted = sorted(set(words), key=len, reverse=True)

        for word in words_sorted:
            if len(word) < 2:
                continue
            if word in method_index:
                body, fname, lineno = method_index[word]
                return (
                    f"SELF_INSPECT:{query}||METHOD:{word} (from {fname})\n"
                    f"{body[:8000]}"
                )

        # ── Keyword search ─────────────────────────────────────────────────
        significant_words = [w for w in words_sorted if len(w) > 3]
        if significant_words:
            hits = []
            seen = set()
            for i, line in enumerate(lines):
                if any(w.lower() in line.lower() for w in significant_words):
                    block = range(max(0, i - 2), min(len(lines), i + 6))
                    for j in block:
                        if j not in seen:
                            hits.append(lines[j])
                            seen.add(j)
                    hits.append("---")
                if len(hits) > 300:
                    hits.append("... [truncated]")
                    break
            if hits:
                return f"SELF_INSPECT:{query}||KEYWORD_HITS:\n" + "\n".join(hits)

        # ── Nothing found ──────────────────────────────────────────────────
        sigs = _extract_sigs(full_source)
        sigs_text = "\n".join(sigs)

        return (
            f"SELF_INSPECT:{query}||NOT_FOUND: No method or keyword match found "
            f"for '{query}' in Nova source.\n"
            f"IMPORTANT: The following are ONLY function signatures — you do NOT "
            f"have the method bodies. Do NOT invent or guess what these functions contain.\n"
            f"Available signatures:\n{sigs_text}"
        )

    except Exception as e:
        return f"Could not read source: {e}"