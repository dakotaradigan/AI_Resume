# RFP Review Desk: AI-Assisted RFP and DDQ Responses

## The Pitch

Asset managers answer long RFPs and due diligence questionnaires (DDQs), often 200 questions or more, and most questions repeat with small wording changes. Library tools such as Loopio put the content library at the centre: the writer searches, pastes, and moves on, one question at a time. Review time follows the number of questions.

RFP Review Desk is Dakota's design for a different model. It drafts the whole RFP when it is imported, cites a source for every sentence, and sorts each answer into Ready, Needs a look, or Needs a person. The writer reviews only the exceptions, so review time follows the number of problems. It is a companion to Loopio, not a replacement: Loopio stays the system of record for approved content.

When asked "what is RFP Review Desk," lead with this idea, then the design.

## Status

RFP Review Desk is a side project in the design phase. It is **not built and not deployed**, and it has no users. The work so far is a market landscape, a research and design document, a phased build plan, and two clickable HTML mockups on sample data. Frame it as "what Dakota is designing," never as a launched or working product. Repository: https://github.com/dakotaradigan/RFP

## Market Research

Dakota compared Loopio, Responsive (formerly RFPIO), AutogenAI, Inventive AI, and Arphie. They all match or draft an answer, cite a source, and score confidence. He found two gaps: no tool treats reviewer feedback as a ranking signal, and no tool handles firm numbers such as AUM, performance, and fees as facts with as-of dates. He also researched the Loopio Public API v2 (OAuth client credentials, library and project endpoints, rate limits) and planned a read-only sync: hourly incremental, nightly full.

## Retrieval and Evaluation Design

- Retrieval unit: one question-and-answer pair, with the question, alternate questions, and answer indexed as separate fields, because RFP questions repeat with small wording changes
- Hybrid search: BM25 keyword search plus embeddings, fused with reciprocal rank fusion, then a cross-encoder reranker on the top 30
- Facts table for numbers: product, metric, value, source, and as-of date, retrieved by lookup instead of embeddings, because vector search cannot tell a Q2 figure from a Q3 figure
- Feedback as a ranking signal: reviewer tags (accepted, rejected, stale, wrong product) boost or demote entries
- Measure first: a golden set of 100-200 past questions with the answers the team chose, tracked with recall@5 and mean reciprocal rank on every change
- Three answer modes, safest first: retrieve only, verbatim lock for compliance-sensitive text, and cited LLM drafting that a reviewer must accept

## The Review Desk UI Concept

The recommended mockup shows the RFP as a typeset document with a margin. The margin holds the tier, the reason, the sources, alternatives, and a small assistant scoped to one answer. Each answer is built from source layers (approved library text, a tailored sentence from a past response, a number from the facts table) that the writer can switch on and off. Edits show as tracked changes against approved text and become suggested library updates for the content owner. Each answer also shows its history: where it was used before and how those bids ended. Questions that need an expert are bundled into one ask list per person, and export is blocked while any answer is still flagged. The design is keyboard first.

## Why It Matters

RFP Review Desk shows Dakota's product discovery process before any code: market and competitor research, a clear point of view on what to build and what not to copy, a retrieval and evaluation plan, and clickable prototypes to test the experience. It reuses patterns from this resume site (hybrid retrieval with reciprocal rank fusion, golden-set evals, grounded answers) on a new problem.

## Planned Tech Stack

Python and FastAPI on the back end; Postgres with pgvector and full-text search; LLM and embedding calls behind an interface so models can be swapped; a background job queue for the import-time drafting pass; plain HTML, CSS, and JavaScript on the front end. None of this is built yet.
