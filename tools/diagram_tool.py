import os
import re
import time
import shutil
from datetime import datetime
from graphviz import Digraph

def _create_graphviz_diagram(text, filename=None):
    os.makedirs("diagrams", exist_ok=True)
    if filename is None:
        filename = f"diagrams/gv_diagram_{int(time.time() * 1000)}"

    # Extract content between ```dot and ``` fences if present
    fence_match = re.search(r'```dot\s*\n(.*?)```', text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    else:
        # Strip any markdown fences generically
        text = re.sub(r'```\w*\n?', '', text).strip()

    # If it looks like full DOT syntax, render it directly
    if 'label=' in text or 'shape=' in text or 'digraph' in text.lower():

        from graphviz import Source
        if not text.strip().lower().startswith('digraph'):
            dot_source = (
                'digraph G {\n'
                '    rankdir=LR;\n'
                '    nodesep=0.8;\n'
                '    ranksep=1.2;\n'
                '    splines=spline;\n'
                '    node [shape=box style="rounded,filled" fillcolor=lightblue fontname="Arial"];\n'
                '    edge [fontname="Arial" fontsize=10];\n'
                f'{text}\n'
                '}'
            )
        else:
            dot_source = text
        src = Source(dot_source, format='png')
        return src.render(filename, cleanup=False)

    # ── Simple edge list parser (fallback) ──
    def safe_id(name):
        return re.sub(r'[^a-zA-Z0-9_]', '_', name).strip('_') or 'node'

    rankdir = "LR"
    same_rank_groups = []
    edges = []
    nodes = {}

    lines = text.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.lower().startswith("rankdir="):
            rankdir = line.split("=", 1)[1].strip().upper()
            continue

        if "rank=same" in line.lower():
            members = re.findall(r';\s*([^;{}]+)', line)
            group = [m.strip() for m in members if m.strip()]
            if group:
                same_rank_groups.append(group)
            continue

        if "->" in line:
            line = line.split("#")[0].strip()
            a, b = [x.strip() for x in line.split("->", 1)]
            a = a.strip('"').strip()
            b = b.strip('"').strip()
            if a and b:
                if a not in nodes:
                    nodes[a] = safe_id(a)
                if b not in nodes:
                    nodes[b] = safe_id(b)
                edges.append((a, b))

    dot = Digraph(format="png")
    dot.attr(rankdir=rankdir, nodesep="0.8", ranksep="1.0", splines="ortho")

    for label, node_id in nodes.items():
        dot.node(node_id, label, shape="box", style="rounded,filled", fillcolor="lightblue")

    for group in same_rank_groups:
        valid = [nodes[m] for m in group if m in nodes]
        if valid:
            dot.body.append('{rank=same; ' + '; '.join(valid) + '}')  # noqa

    for a, b in edges:
        dot.edge(nodes[a], nodes[b])

    return dot.render(filename, cleanup=False)

def diagram(description, ai, output_dir="diagrams"):
    """Generate a graphviz block diagram from a description or edge list."""
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs("web_images", exist_ok=True)

    if "->" in description:
        chain = description
    else:
        # Detect diagram type
        desc_lower = description.lower()
        is_control = any(w in desc_lower for w in [
            "control", "feedback", "pid", "controller", "plant", "summing",
            "closed loop", "open loop", "transfer function", "sensor"
        ])
        is_pipeline = any(w in desc_lower for w in [
            "pipeline", "workflow", "process", "stage", "step", "flow",
            "ingestion", "deployment", "sequence"
        ])

        if is_control:
            layout_rules = """- Start with: rankdir=LR
- Main signal flow goes left to right
- FEEDBACK edges (going backwards) MUST have constraint=false
- Example feedback edge: H -> Sum [label="b" constraint=false]"""
        elif is_pipeline:
            layout_rules = """- Start with: rankdir=TB
- Nodes flow top to bottom in sequence
- No feedback edges needed"""
        else:
            layout_rules = """- Start with: rankdir=LR for horizontal flow, rankdir=TB for vertical
- Use rank=same to align parallel blocks: {rank=same; NodeA; NodeB}"""

        prompt = f"""Convert this concept into a Graphviz DOT edge list with layout hints.

Rules:
- One connection per line, format: A -> B [label="signal name"]
{layout_rules}
- Do NOT declare node shapes or styles — defaults will be applied
- Label all edges with signal names
- Do NOT call any tools or use tool_call syntax
- Return ONLY the directives and edge list, nothing else

Concept: {description}
"""
        chain = ai.generate(prompt, use_planning=False).strip()
        print(f"[DIAGRAM] Edge list generated:\n{chain}")
        if not chain or "->" not in chain:
            return f"Could not generate diagram for: {description}"

    try:
        original_path = _create_graphviz_diagram(chain)
        original_png = original_path + ".png" if not original_path.endswith(".png") else original_path

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', description)[:50]
        web_filename = f"diagram_{safe_name}_{timestamp}.png"
        web_path = os.path.join("web_images", web_filename)

        if os.path.exists(original_png):
            shutil.copy2(original_png, web_path)
            print(f"[DIAGRAM] ✅ Saved to web: {web_filename}")
            return f"[DIAGRAM:{web_filename}]"
        else:
            import glob
            png_files = glob.glob("diagrams/*.png")
            if png_files:
                latest = max(png_files, key=os.path.getctime)
                shutil.copy2(latest, web_path)
                print(f"[DIAGRAM] ✅ Found and copied: {web_filename}")
                return f"[DIAGRAM:{web_filename}]"
            else:
                return f"Diagram error: No PNG file found"

    except Exception as e:
        print(f"[DIAGRAM] ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return f"Diagram error: {e}"