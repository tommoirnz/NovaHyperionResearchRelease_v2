# Nova Assistant — Council of Agents Architecture

*Document version: May 2026*
*Author: Dr Tom Moir, Birkdale, Auckland, New Zealand*

---

## 10. Multi-Agent Council Deliberation System

### Overview

A multi-agent deliberation system — `NovaCouncil` — was added in May 2026. Rather than routing every query through a single LLM call, Nova can convene an internal council of specialised agents, each with a distinct cognitive role, distinct system prompt, and distinct generation temperature. The council's outputs are synthesised into a single coherent response that reflects multiple independent perspectives without exposing the internal scaffolding to the user.

This makes Nova unusual among deployed personal AI systems. Commercial LLMs perform a single forward pass per query. Agent frameworks such as LangGraph and AutoGen support multi-agent deliberation but require significant engineering effort to deploy. Nova embeds the council directly into the assistant's routing pipeline as a selectively-triggered path, activated only when the query genuinely warrants deliberation.

---

### 10.1 Theoretical Basis

The design draws on several established frameworks:

**Minsky's Society of Mind (1986):** Intelligence as the emergent property of many specialised agents interacting. No single agent is intelligent in isolation; the appearance of coherent reasoning arises from the combination. Nova's council is a constrained, practical instantiation of this idea — a small fixed panel of agents rather than a large dynamic society.

**Cognitive diversity research (Hong & Page, 2004):** Groups of cognitively diverse problem-solvers outperform groups of individually skilled solvers on sufficiently complex problems. The key requirement is that agents must approach the problem differently, not merely have different levels of competence. Nova's per-agent temperature differentiation (Section 10.3) implements this — agents are not just differently prompted but genuinely generate differently due to temperature variation.

**Deliberative democracy theory (Habermas, 1984):** The legitimacy and quality of a decision improves when it emerges from structured deliberation among participants with different perspectives, subject to synthesis rather than simple voting. The council's synthesis step — which resolves contradictions by explaining trade-offs rather than suppressing minority views — mirrors this principle.

**Multi-agent systems research (Wooldridge & Jennings, 1995):** Autonomous agents as systems with goals, beliefs, and reasoning capabilities, coordinated through communication protocols. Nova's council is a lightweight implementation — agents share a query and context but reason independently before a coordinator (the synthesiser) integrates their outputs.

---

### 10.2 Agent Roster

The council consists of five specialised agents defined in `nova_council.py`:

| Agent | Role | Priority |
|---|---|---|
| **Analyst** | Factual accuracy, evidence, logical structure | 1 |
| **Creative** | Lateral thinking, novel angles, unexpected connections | 2 |
| **Critic** | Challenging assumptions, identifying weaknesses and risks | 3 |
| **Strategist** | Long-term implications, second-order effects, actionable steps | 4 |
| **Empath** | Human factors, emotional tone, communication style | 5 |

Each agent has a distinct system prompt that defines its cognitive role and output format. The priority field determines which agent's response is used as a fallback if synthesis fails.

The Empath agent deserves particular note. It reads the conversation history injected into context and assesses the user's current emotional and cognitive state before contributing its perspective. This output is informed by what Nova knows about the user from `NovaMemory`'s semantic store — persistent facts such as the user's technical background, current projects, and interaction preferences. This is consistent with affective computing research (Picard, 1997) which argues that emotionally intelligent systems must model the user's state, not merely perform emotion themselves.

---

### 10.3 Per-Agent Temperatures

A key design decision is that agents run at different generation temperatures rather than a uniform value:

```python
temperature_map = {
    "analyst":    0.3,   # Low — precision and accuracy
    "creative":   0.9,   # High — divergent, unexpected
    "critic":     0.4,   # Low-moderate — sceptical but controlled
    "strategist": 0.5,   # Moderate — balanced long-term thinking
    "empath":     0.6    # Moderate — warm but grounded
}
```

The Analyst and Creative agents are not merely differently prompted — they genuinely generate differently because they operate at different points on the randomness-determinism spectrum. A single agent at a compromise temperature would produce mediocre creative output (too constrained) and unreliable analytical output (too random). The temperature split allows each role to operate in its natural register.

This approach is consistent with ensemble methods research from machine learning (Dietterich, 2000), where diversity among ensemble members — not just individual accuracy — is the key driver of ensemble performance. Temperature variation is one mechanism for inducing output diversity without requiring separate model weights.

---

### 10.4 Task-Type Routing

Not all agents are appropriate for all queries. The `TASK_ROUTING` dict maps query categories to the most relevant agent subset:

```python
TASK_ROUTING = {
    "research":  ["analyst", "critic", "strategist"],
    "creative":  ["creative", "empath", "analyst"],
    "math":      ["analyst", "critic"],
    "code":      ["analyst", "critic", "creative"],
    "social":    ["empath", "strategist", "critic"],
    "default":   ["analyst", "empath"]
}
```

The task type is determined in `nova_router.py` by keyword matching on the user input before the council is invoked. If no specific type is matched, the `default` pair fires — a lightweight two-agent call that avoids unnecessary token expenditure.

---

### 10.5 Parallel Execution

In parallel mode (the default), all agents for a given task type are submitted simultaneously to a `ThreadPoolExecutor`:

```python
with ThreadPoolExecutor(max_workers=len(agent_names)) as executor:
    futures = {
        executor.submit(self._call_agent, name, self.AGENTS[name], query): name
        for name in agent_names
    }
    for future in as_completed(futures, timeout=30):
        responses[name] = future.result(timeout=10)
```

A 30-second wall-clock timeout applies to the full parallel batch, with a 10-second timeout per individual result. This prevents any single slow LLM call from blocking the entire pipeline. Total latency for a three-agent parallel council call is approximately equal to the slowest single agent, not the sum of all agents.

Sequential mode is also available, where each agent sees the prior agents' outputs before generating. This is appropriate for iterative refinement tasks — for example, a `poem_to_code` task type (planned) where the Creative agent writes a poem and the Analyst then derives working code from it, informed by the poem's specific imagery.

---

### 10.6 Pre-Deliberation Classifier

A lightweight pre-deliberation classifier was added to prevent the council from firing on queries that do not genuinely warrant multi-perspective analysis:

```python
def _needs_council(self, user_input: str) -> bool:
    verdict = self.ai.generate(
        f"""Does this question genuinely benefit from multiple perspectives,
trade-off analysis, or deliberation? Or is it a simple factual or task question?

Question: {user_input}

Reply with ONE word only: COUNCIL or SIMPLE""",
        use_planning=False
    ).strip().upper()
    return "COUNCIL" in verdict
```

This replaces an earlier keyword-trigger approach (matching phrases such as "what should I do", "pros and cons", "best approach") which was too rigid — it missed genuinely deliberative questions that used different phrasing, and triggered on casual queries that happened to contain trigger words.

The classifier costs one small, fast generation before deciding whether to commit to three or more parallel agent calls. On simple questions it returns `SIMPLE` and falls through to the planner. On advisory, trade-off, or strategic questions it returns `COUNCIL` and the full panel convenes.

This is consistent with meta-reasoning research (Russell & Wefald, 1991), which argues that a rational agent should reason about the expected value of deliberation before deliberating — committing computational resources only when the expected improvement in decision quality justifies the cost.

---

### 10.7 Synthesis

After all agents have responded, a synthesis step integrates their outputs into a single Nova response:

```python
synthesis_prompt = """You are Nova — synthesising a council of specialised agents
into one coherent response.

Instructions:
- Weave the insights together — do not list them separately
- Resolve contradictions by explaining the trade-offs
- Produce a single, unified, high-quality response
- Maintain Nova's voice: direct, witty, precise
- Do not mention the agents by name in the final output"""
```

The synthesiser runs at the default model temperature (0.3) to ensure coherence. Its input is the concatenated outputs of all agents; its output is what the user sees. The agents themselves are never named or exposed in the final response — the council is an internal deliberation mechanism, not a visible feature.

If synthesis fails, the fallback is the highest-priority agent's response (the Analyst, priority 1), ensuring a meaningful response is always returned.

---

### 10.8 Integration with NovaAffect and NovaMemory

The council is integrated with Nova's existing emotional affect and memory systems:

**NovaAffect:** After a successful council synthesis, `affect.update("social")` is called, reflecting the interpersonal and deliberative nature of council exchanges. This nudges empathy and playfulness upward and formality slightly downward — appropriate for the considered, multi-perspective responses the council produces.

**NovaMemory:** Council results are stored via `memory.store_conversation()` and semantic facts are extracted from the synthesis via `_extract_semantic_facts()`. Nova learns from council deliberations in the same way she learns from any other conversation — persistent facts accumulate and are injected into future reasoning via the `KNOWN FACTS ABOUT USER:` block prepended to every planner call.

**Deliberation log:** The council maintains a bounded circular log (`deque(maxlen=50)`) of all deliberations, including the agents used, their individual responses, the synthesis, and a timestamp. This log is available for inspection and forms part of Nova's self-knowledge.

---

### 10.9 Self-Assessment

When asked to evaluate its own council architecture, Nova produced the following assessment via self-inspection and council deliberation (May 2026):

> *"The Council is only better than a single well-prompted call if the synthesiser is genuinely integrating perspectives — not just appending them with headers. The missing piece is a pre-deliberation classifier that decides: does this question actually warrant the full Council, or should it bypass to a single-agent fast path? Without that, you're firing a committee at every question — including the ones that just need a quick answer."*

The pre-deliberation classifier described in Section 10.6 was implemented directly in response to this self-generated diagnosis. This is an instance of Nova's self-improvement capability applied to its own deliberation architecture — Nova identified a weakness in a system component, articulated the fix, and the fix was implemented.

---

### 10.10 Comparison with Existing Frameworks

| System | Multi-agent deliberation | Per-agent temperatures | Pre-deliberation classifier | Integrated with persistent memory | Ready-to-use |
|---|---|---|---|---|---|
| **Nova (NovaCouncil)** | Yes | Yes | Yes | Yes | Yes |
| LangGraph | Yes (framework) | Manual | No | No | No |
| AutoGen | Yes (framework) | Manual | No | No | No |
| CrewAI | Yes (framework) | No | No | No | No |
| ChatGPT / Claude / Gemini | No | N/A | N/A | Limited | Yes |
| OpenAI o1/o3 | Internal CoT only | N/A | N/A | No | Yes |

Nova's council is not the most architecturally flexible implementation — LangGraph offers more freedom for custom topologies. But it is the most integrated: council outputs feed directly into affect state, semantic memory, and conversation history, creating a coherent loop between deliberation and long-term learning.

---

## References (Section 10 additions)

**Multi-agent systems and society of mind:**
- Minsky, M. (1986). *The society of mind*. Simon & Schuster.
- Wooldridge, M., & Jennings, N. R. (1995). Intelligent agents: Theory and practice. *The Knowledge Engineering Review*, 10(2), 115–152.
- Wooldridge, M. (2009). *An introduction to multiagent systems* (2nd ed.). Wiley.

**Cognitive diversity:**
- Hong, L., & Page, S. E. (2004). Groups of diverse problem solvers can outperform groups of high-ability problem solvers. *Proceedings of the National Academy of Sciences*, 101(46), 16385–16389.
- Page, S. E. (2007). *The difference: How the power of diversity creates better groups, firms, schools, and societies*. Princeton University Press.

**Deliberation and synthesis:**
- Habermas, J. (1984). *The theory of communicative action, Vol. 1: Reason and the rationalization of society*. Beacon Press.
- Surowiecki, J. (2004). *The wisdom of crowds*. Doubleday.

**Ensemble methods and output diversity:**
- Dietterich, T. G. (2000). Ensemble methods in machine learning. In *International workshop on multiple classifier systems* (pp. 1–15). Springer.

**Meta-reasoning:**
- Russell, S., & Wefald, E. (1991). *Do the right thing: Studies in limited rationality*. MIT Press.

**Affective computing (cross-reference from Section 2):**
- Picard, R. W. (1997). *Affective computing*. MIT Press.

**LLM agent frameworks (contemporary):**
- Chase, H. (2022). LangChain. GitHub. https://github.com/langchain-ai/langchain
- Wu, Q., Bansal, G., Zhang, J., Wu, Y., Zhang, S., Zhu, E., & Wang, C. (2023). AutoGen: Enabling next-gen LLM applications via multi-agent conversation. *arXiv:2308.08155*.
- Moura, J. (2023). CrewAI: Framework for orchestrating role-playing autonomous AI agents. GitHub. https://github.com/joaomdmoura/crewai