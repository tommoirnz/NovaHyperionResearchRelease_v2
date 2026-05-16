"""
read_log.py — Tool that gives Nova visibility into her own runtime system log.

Lets Nova diagnose her own behaviour: routing decisions, errors, agent calls,
memory operations, council deliberations, and tool execution.
"""

import re
import nova_log_buffer


def read_log(query: str, log_callback=None) -> str:
    """
    Reads Nova's live system log buffer and returns relevant entries.

    Use for: diagnosing errors, checking which agents fired, reviewing
    recent routing decisions, seeing what the council did, spotting
    patterns in system behaviour.

    Args:
        query: What to look for. Examples:
               "last 50 lines"
               "errors"
               "council"
               "planner"
               "geometry"
               "memory"
               "all"
        log_callback: Optional Nova log function.
    Returns:
        Filtered or recent log lines as a formatted string.
    """
    try:
        if log_callback:
            log_callback(f"[READ_LOG] Query: {query}")

        q = query.lower().strip()

        # ── Determine what to return ──────────────────────────────────────────

        # "last N lines" or "recent N"
        count_match = re.search(r'(\d+)\s*lines?|last\s+(\d+)|recent\s+(\d+)', q)
        if count_match:
            n = int(next(g for g in count_match.groups() if g))
            lines = nova_log_buffer.get_recent(n)
            header = f"Last {n} log lines:"

        # "all" — return everything
        elif q in ("all", "everything", "full", "dump"):
            lines = nova_log_buffer.get_all()
            header = f"Full log ({len(lines)} lines):"

        # "errors" or "error"
        elif any(w in q for w in ["error", "errors", "fail", "exception", "crash"]):
            lines = nova_log_buffer.search("error") + nova_log_buffer.search("fail") + \
                    nova_log_buffer.search("exception")
            lines = list(dict.fromkeys(lines))  # deduplicate preserving order
            header = f"Error/failure entries ({len(lines)} found):"

        # Specific section keywords — search for them
        elif any(w in q for w in ["council", "planner", "geometry", "memory",
                                   "router", "tool", "agent", "code", "whisper",
                                   "tts", "react", "internet", "history",
                                   "affect", "ollama", "model"]):
            # Extract the keyword to search
            keywords = ["council", "planner", "geometry", "memory", "router",
                        "tool", "agent", "code", "whisper", "tts", "react",
                        "internet", "history", "affect", "ollama", "model"]
            found_kw = next((kw for kw in keywords if kw in q), None)
            lines = nova_log_buffer.search(found_kw, n=300) if found_kw else \
                    nova_log_buffer.get_recent(50)
            header = f"Log entries matching '{found_kw}' ({len(lines)} found):"

        # Default — last 50 lines
        else:
            lines = nova_log_buffer.get_recent(50)
            header = "Recent log (last 50 lines):"

        if not lines:
            return f"No log entries found for query: '{query}'"

        result = f"{header}\n\n" + "\n".join(lines)

        if log_callback:
            log_callback(f"[READ_LOG] Returning {len(lines)} lines")

        return result

    except Exception as e:
        if log_callback:
            log_callback(f"[READ_LOG] Error: {e}")
        return f"Error reading log: {str(e)}"
