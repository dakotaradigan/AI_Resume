# Brainstorm: ISD Multi-Agent Pipeline

**Date:** 2026-02-13
**Status:** Brainstorm
**Inspired by:** Hebbia's Iterative Source Decomposition architecture

---

## What We're Building

A 7-agent ISD (Iterative Source Decomposition) pipeline, built as a standalone
Python package using the Claude Agent SDK, that can be imported into the resume
assistant as an optional upgrade to the current single-pass RAG system.

**Dual purpose:**
1. Genuinely improve complex query handling in the resume assistant
2. Serve as a portfolio piece demonstrating multi-agent architecture skills

## Why This Approach

**The problem with standard RAG:** Hebbia's research shows 84% failure rate on
real-world professional queries. Simple top-k retrieval can't handle questions
like "Compare Dakota's ML work with his backend experience" or "What's the most
interesting technical challenge Dakota solved?" These need decomposition,
targeted retrieval, and synthesis — not just similarity search.

**Hebbia's key insight — "Full Attention":** Don't just retrieve snippets.
Figure out what actually needs to be deeply read by the LLM, then apply full
self-attention to those parts. The system identifies the relevant portion of
data needing full attention, not just the most similar portion.

**Why Claude Agent SDK:** Aligns with the project's existing Anthropic stack
(Claude for generation, already using the API). Shows deep ecosystem knowledge.
The SDK provides built-in agent orchestration, tool interfaces, and multi-agent
coordination natively.

## The 7-Agent Architecture (Hebbia Mirror)

```
User Query
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  1. ORCHESTRATOR                                     │
│  Manages the full research process. Delegates to     │
│  specialized agents. Decides when to explore vs.     │
│  exploit. Handles inter-agent communication.         │
└──────────┬──────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────┐
│  2. PLANNER                                          │
│  Decomposes complex query into actionable sub-tasks  │
│  with dependency ordering. Not just splitting the    │
│  question — spawns sub-systems of agents per task.   │
└──────────┬──────────────────────────────────────────┘
           │
           ▼ (parallel sub-tasks)
┌─────────────────────────────────────────────────────┐
│  3. RETRIEVER                                        │
│  Surfaces relevant data from sources. Goes beyond    │
│  similarity search — determines what NEEDS deep      │
│  analysis ("component gathering" not just retrieval). │
│  Runs in parallel across sub-tasks.                  │
└──────────┬──────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────┐
│  4. READER                                           │
│  Dedicated to deep information extraction from       │
│  retrieved components. Applies "full attention" to   │
│  selected chunks. Extracts structured facts, not     │
│  just passages.                                      │
└──────────┬──────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────┐
│  5. DISTILLER                                        │
│  Compresses context to principal components between  │
│  agent stages. Hebbia reports 90%+ context reduction │
│  with lower latency and higher recall. Prevents      │
│  context rot in downstream agents.                   │
└──────────┬──────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────┐
│  6. REASONER                                         │
│  Dynamically assesses and refines the research       │
│  process. Implements explore-exploit: first breadth  │
│  across the research surface, then depth on areas    │
│  of interest as insights emerge. Can loop back to    │
│  Planner/Retriever if gaps detected.                 │
└──────────┬──────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────┐
│  7. OUTPUT                                           │
│  Synthesizes findings into the final cited response. │
│  Reverse-engineers highlight-worthy source text for  │
│  citation transparency. Applies validation heuristics│
│  (token-level log-likelihoods, text-level checks).   │
└─────────────────────────────────────────────────────┘
```

## Key Hebbia Concepts to Implement

### Context Rot Prevention (Hebbia's Multi-Pronged Approach)
1. **Role isolation** — each agent has clearly defined scope, only relevant
   history and information in its context
2. **Selective inter-agent communication** — agents share only what's necessary
   for the next subtask, minimizing unnecessary context sharing
3. **Context Distillation Agent** — reduces context to principal components
   (90%+ reduction in Hebbia's evaluation)
4. **Strongly typed hierarchical contexts** — rigorously defined, separated
   context classes to avoid overloading

### Intelligent Chunking (Beyond Standard RAG)
Current resume chunking is basic (1 chunk per job, 1 per project). ISD chunking
should produce "contextually dense, temporally connected, and modally homogenous
components" — preserving structure, layout, and temporal flow.

### Component Gathering vs. Retrieval
Standard RAG: "find similar text"
ISD: "determine what needs deep analysis in relation to the original query"

### Explore-Exploit Pattern
The multi-agent team approaches research by first exploring breadth (decomposing
into broad subtasks), then exploiting depth (going deep on areas of interest as
new insights emerge from the exploration phase).

## Package Design

### Structure
```
dakota-isd/                     (standalone repo)
├── pyproject.toml              (installable package)
├── README.md                   (portfolio-quality docs)
├── src/
│   └── dakota_isd/
│       ├── __init__.py
│       ├── orchestrator.py     (Agent 1: Orchestrator)
│       ├── planner.py          (Agent 2: Planner)
│       ├── retriever.py        (Agent 3: Retriever)
│       ├── reader.py           (Agent 4: Reader)
│       ├── distiller.py        (Agent 5: Distiller)
│       ├── reasoner.py         (Agent 6: Reasoner)
│       ├── output.py           (Agent 7: Output)
│       ├── pipeline.py         (End-to-end ISD pipeline)
│       └── adapters/
│           └── resume.py       (Resume-specific adapter)
├── tests/
└── examples/
    └── resume_assistant.py     (Integration example)
```

### Integration with Resume Assistant
```python
# In backend/main.py (behind feature flag)
if settings.USE_ISD:
    from dakota_isd import ISDPipeline
    from dakota_isd.adapters.resume import ResumeAdapter

    isd = ISDPipeline(
        adapter=ResumeAdapter(qdrant_client, resume_data),
        model="claude-haiku-4-5-20251001",  # fast/cheap for sub-agents
    )
    context = await isd.process(user_query)
else:
    context = await retrieve_rag_context(user_query)
```

### Model Strategy
- **Orchestrator + Reasoner:** Claude Sonnet (needs judgment)
- **Planner + Output:** Claude Sonnet (needs quality)
- **Retriever + Reader + Distiller:** Claude Haiku (fast, cheap, focused tasks)
- All configurable — the package is model-agnostic per Hebbia's design

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Framework | Claude Agent SDK | Aligns with existing Anthropic stack, portfolio value |
| Architecture | Full 7-agent Hebbia mirror | Maximum portfolio impact, demonstrates understanding |
| Packaging | Standalone repo, pip-installable | Own project + importable into resume assistant |
| Scope | Resume-specific (with adapter pattern) | Ships faster, directly useful, adapter allows future generalization |
| Citations | Nice to have (Phase 2) | Focus on decomposition + multi-agent flow first |
| Agent models | Mixed (Sonnet for judgment, Haiku for speed) | Cost-effective, shows model routing understanding |

## Open Questions

1. **Latency budget:** Current chatbot targets <3s responses. A 7-agent pipeline
   will be slower. What's the acceptable latency for ISD-enhanced responses?
   Could show a "thinking deeply..." indicator.

2. **Cost per query:** 7 agent calls per user query adds up. What's the budget?
   Could the Distiller/Reader agents use Haiku to keep costs down?

3. **When to trigger ISD vs. simple RAG:** Not every query needs 7 agents.
   "What's Dakota's email?" shouldn't go through ISD. Need a classifier or
   complexity threshold to route simple vs. complex queries.

4. **Eval strategy:** How do we measure if ISD actually improves response
   quality? The existing eval framework (groundedness, conciseness judges)
   could be extended with a "decomposition quality" judge.

5. **Demo/visualization:** Should the package include a way to visualize the
   agent pipeline execution? (e.g., trace view showing which agents fired,
   what they produced, how context was distilled) — strong portfolio element.

6. **A2A future:** Package designed for Claude SDK now, but could A2A protocol
   be added later for inter-agent communication? Would show interoperability.

## Next Steps

Run `/workflows:plan` to design the implementation when ready.
