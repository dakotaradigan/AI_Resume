# Resume Assistant RAG: Technical Learning Handoff

Last verified: 2026-07-19 against `main` and the live production health endpoint.

This is the self-contained handoff for understanding, operating, and safely
changing Resume Assistant's retrieval-augmented generation (RAG) feature. It
describes the implementation that exists today, not the earlier vector-only
prototype or the Phase C proposal.

## Start Here in Cowork

Open this repository in Cowork and give it the following instruction:

> Read `docs/rag-learning-handoff.md` completely, then inspect the referenced
> source files before teaching me. Act as a technical mentor, not an
> implementer. Teach the system in this order: mental model, corpus and
> indexing, Qdrant vectors, BM25, RRF, request flow, failure handling,
> operations, and evals. At the end of each section, ask me one check-for-
> understanding question and wait for my answer. Use examples from this
> repository. Distinguish facts verified in code from suggestions. Do not
> change code, production data, environment variables, or Qdrant unless I
> explicitly ask.

After the walkthrough, ask Cowork to use the exercises in [Learning
path](#learning-path) and the review questions in [Questions worth being able
to answer](#questions-worth-being-able-to-answer).

## Current Snapshot

| Item | Current implementation |
| --- | --- |
| Generator | Anthropic Claude, selected by the app's model router |
| Embeddings | OpenAI `text-embedding-3-small` |
| Vector store | Qdrant, collection `resume` |
| Vector shape | 1,536 dimensions, cosine distance |
| Lexical retrieval | BM25 in the FastAPI process (`k1=1.5`, `b=0.75`) |
| Fusion | Reciprocal Rank Fusion (RRF), `k=60` |
| Retrieval tuning | Up to 4 results; vector threshold `0.30` |
| Corpus | 26 chunks: 14 from `resume.json`, 12 from project Markdown |
| Fallback | Compact static summary derived from `resume.json` |
| Live state verified 2026-07-19 | RAG initialized, Qdrant live, 26 points |

OpenAI and Anthropic have different jobs here. OpenAI converts text into
vectors. Qdrant stores and searches those vectors. Claude receives the
retrieved text and writes the answer. The providers do not need to match; the
contract between retrieval and generation is ordinary text.

## The Mental Model

RAG means **retrieve first, generate second**:

1. Turn source material into searchable chunks.
2. Retrieve the chunks most relevant to a question.
3. Put those chunks into Claude's system context.
4. Ask Claude to answer using that context.

RAG does not train Claude, update model weights, or make Qdrant generate an
answer. It selects evidence for this one request.

There are two different timelines:

```text
INDEXING / DATA REFRESH

resume.json ───────┐
                   ├─> source-aligned chunks ─> OpenAI embeddings ─> Qdrant vectors
projects/*.md ─────┘          │
                              └─> token counts ─> in-process BM25 index


ONE CHAT REQUEST

user question ─> RAG search worker
                    1. OpenAI query embedding
                    2. Qdrant semantic ranking
                    3. BM25 lexical ranking
                    4. RRF ─> top 4 chunks ─> retrieved context ───────────┐
                                                                          │
user question ─> model routing (concurrent with RAG) ─> selected model ───┤
system prompt + conversation history ─────────────────────────────────────┤
                                                                          v
                                                                       Claude
                                                                          │
                                                                          v
                                                                 SSE answer stream
```

The key design choice is **hybrid retrieval**. Vector search is strong at
meaning; BM25 is strong at exact terms. RRF combines their rankings without
pretending their raw scores are directly comparable. They are two conceptual
retrieval lanes, but the current `search` method executes the dense work before
BM25; an embedding or Qdrant exception prevents the lexical step from running.

## Code Map

| File | What to study |
| --- | --- |
| `backend/rag.py` | Chunking, embeddings, Qdrant indexing, BM25, RRF, startup rebuild, drift detection, reindexing |
| `backend/main.py` | RAG initialization, static fallback, async request integration, health and admin endpoints |
| `backend/config.py` | Environment-backed RAG settings |
| `backend/test_rag.py` | Offline retrieval tests and opt-in Qdrant integration test |
| `data/resume.json` | Structured resume source |
| `data/projects/*.md` | Long-form project sources |
| `evals/scripts/run_retrieval_eval.py` | Golden-dataset retrieval evaluation |
| `evals/APP_EVAL_PLAN.md` | Retrieval metrics, baseline, and evaluation decisions |
| `evals/datasets/README.md` | Golden-dataset schema and approval rule |
| `frontend/app.js` | Source-title display; raw retrieval scores are intentionally not shown as confidence |

Read `backend/rag.py` in this order:

1. `DocumentChunk`
2. `chunk_resume_data`, `chunk_project_docs`, and `build_corpus`
3. `embed_text` and `index_chunks`
4. `_build_keyword_index`, `_rebuild_keyword_index_from_qdrant`, and
   `_bm25_rank`
5. `search`
6. `initialize_rag_pipeline` and `reindex`

Then follow the runtime path in `backend/main.py`:

1. `_initialize_rag`
2. `_prepare_generation`
3. `_build_chat_context`
4. `retrieve_rag_context`
5. `/health/rag` and `/admin/rag/reindex`

## Corpus and Chunking

The retriever searches chunks, not whole files. A chunk is represented by
`DocumentChunk` and contains:

- `text`: what retrieval searches and Claude receives;
- `chunk_type`: category such as `experience` or `project_doc`;
- `title`: stable human-readable identity;
- optional `timeframe` and `tags` metadata.

### Structured resume chunks

`chunk_resume_data` currently builds 14 chunks:

| Type | Count | Rule |
| --- | ---: | --- |
| Personal | 1 | Name, title, location, summary, email, and LinkedIn; phone intentionally excluded |
| Experience | 4 | One chunk per role, including achievements and technologies |
| Project | 6 | Project overview plus an architecture chunk when architecture details exist |
| Skills | 1 | All skill categories |
| Education | 1 | All education entries |
| Certifications | 1 | All certification entries |

### Project-document chunks

`chunk_project_docs` reads every `data/projects/*.md` file in sorted order:

1. The H1 becomes the document title.
2. Each H2 begins a semantic section.
3. A section body shorter than 300 characters is merged into the previous
   chunk from the same document when one exists.
4. The stable title format is `Document title — Section heading`.
5. The chunk type is `project_doc`.

The current project files produce 12 chunks, bringing the total corpus to 26.
The title format is load-bearing: the retrieval golden dataset and source UI
refer to exact titles. Renaming headings can therefore be a data-contract
change, not merely a copy edit.

This is deterministic source-boundary chunking, not token-aware or
model-generated semantic chunking. Text before the first H2 is not indexed, a
Markdown file without an H1 is skipped, chunks do not overlap, and there is no
maximum token-size split.

Print the corpus without using OpenAI or Qdrant:

```bash
PYTHONPATH=backend USE_RAG=false python -c "from pathlib import Path; from rag import build_corpus; chunks=build_corpus(Path('data/resume.json'), Path('data/projects')); print(len(chunks)); print(*[f'{c.chunk_type}: {c.title}' for c in chunks], sep='\n')"
```

### What gets stored in Qdrant

Each non-empty chunk becomes one point:

```text
point id: 0, 1, 2, ...
vector:   1,536 floating-point coordinates
payload:
  text
  type
  title
  timeframe
  tags
```

`index_chunks` embeds each chunk and upserts the batch into Qdrant. It also
builds the BM25 index from the same payloads so the two retrieval lanes see the
same documents.

## Qdrant and Vectors

### What an embedding is

An embedding model converts text into a fixed-length list of numbers. In this
system, `text-embedding-3-small` returns 1,536 numbers. You can think of the
list as a location in a high-dimensional meaning space, but the individual
dimensions are not useful labels such as "leadership" or "Python."

Texts used in similar contexts tend to land near one another. That allows a
question such as "What did he build to reduce support work?" to retrieve a
chunk about resolving client inquiries even when the wording is different.

### What Qdrant does

Qdrant stores each vector beside its payload. At query time:

1. The question is embedded with the same OpenAI model.
2. Qdrant compares the question vector with stored vectors using cosine
   similarity.
3. It returns at most 4 points whose vector score meets `0.30`.

Cosine comparison focuses on the angle between vectors rather than their raw
magnitude. The collection is configured for the 1,536-dimensional output of
the current embedding model.

Qdrant is not the knowledge itself and it is not an LLM. The human-readable
knowledge remains in the point payload. Qdrant's job is to efficiently return
nearby points.

### Why vectors are not enough

Semantic similarity can miss or blur precise identifiers:

- `Pinecone` versus `Qdrant`;
- a certification acronym;
- a specific dollar amount;
- a product name or uncommon technology.

Those are exactly the cases where lexical retrieval helps.

## In-Process BM25

BM25 is a ranked keyword-search algorithm. "In-process" means its index lives
in Python memory inside each FastAPI process. It is not another cloud database
and is not persisted separately.

The tokenizer lowercases text and extracts tokens matching:

```text
[a-z0-9+#.]+
```

This preserves useful technical tokens containing `+`, `#`, or `.`, while
other punctuation becomes a boundary. The simple regex also preserves trailing
periods, so `python.` and `python` are different tokens; that is a known
lexical-recall limitation rather than language-aware tokenization.

BM25 rewards three things:

1. **Term overlap:** the query word must occur in the document.
2. **Rarity:** a word appearing in few documents matters more than a word
   appearing everywhere.
3. **Useful frequency without unlimited repetition:** repeated occurrences
   help, but the benefit saturates; document-length normalization keeps long
   chunks from winning just because they contain more words.

The implementation uses the standard shape:

```text
IDF(term) = ln(1 + (N - df + 0.5) / (df + 0.5))

score += IDF × tf × (k1 + 1)
               ─────────────────────────────
               tf + k1 × (1 - b + b × dl/avgdl)

k1 = 1.5
b  = 0.75
```

Where:

- `N` is the number of documents;
- `df` is how many documents contain the term;
- `tf` is the term count in this document;
- `dl` is this document's token length;
- `avgdl` is the corpus's average document length.

The implementation returns only documents with a positive BM25 score. A query
with zero token overlap produces no BM25 candidates; preserving that true zero
is important to the static-fallback decision.

### Cold-start rebuild

The BM25 index disappears whenever the app process restarts. The source of
truth is the configured `DATA_DIR`; Qdrant payloads are a persisted index
snapshot that can restore BM25 without re-embedding every chunk.

When Qdrant already has points, `_rebuild_keyword_index_from_qdrant`:

1. calls Qdrant `scroll` with payloads enabled and vectors disabled;
2. requests up to 100 records per page;
3. follows `next_offset` until Qdrant returns no next page;
4. rebuilds token frequencies and document frequencies in memory.

Pagination is mandatory even though today's corpus fits on one page. It keeps
the behavior correct if the corpus grows.

Each server process has its own BM25 copy. That is appropriate for 26 small
documents, but it would become a scaling consideration with many workers or a
large corpus.

## RRF: Reciprocal Rank Fusion

RRF is a small algorithm that merges ranked lists.

It does **not** average the Qdrant and BM25 scores. Those scores have different
units and distributions. Instead, RRF looks only at rank position:

```text
RRF(document) = sum(1 / (60 + rank_in_each_list))
```

Example:

| Document | Qdrant rank | BM25 rank | RRF contribution | Result |
| --- | ---: | ---: | ---: | --- |
| A | 1 | — | `1/61 = 0.01639` | Strong in vectors only |
| B | 2 | 1 | `1/62 + 1/61 = 0.03252` | Wins because both lanes support it |
| C | — | 2 | `1/62 = 0.01613` | Strong in BM25 only |

The constant 60 dampens small rank differences. Agreement between the lanes
usually matters more than being one place higher in only one lane.

The implementation:

1. gets up to 4 vector candidates above the vector threshold;
2. ranks every positive BM25 candidate;
3. identifies the same document by `(title, type, text)`;
4. adds the reciprocal-rank contributions;
5. sorts the union by fused score and returns the top 4.

### RRF is not confidence

Neither the RRF value nor a Qdrant cosine score is a calibrated probability
that an answer is correct.

The internal result currently exposes:

- `score`: the Qdrant vector score when the document appeared in the vector
  lane, otherwise `0.0`;
- `keyword_rank`: its BM25 position, or `None`;
- the RRF score only as an internal sorting value.

Therefore, a `0.0` result can be a valid BM25-only match. The frontend
intentionally shows source titles without numeric "confidence" labels.
Filtering out zero-vector-score results would break hybrid retrieval.

## How These Techniques Differ

| Technique | Matches on | Strength | Weakness | Used here? |
| --- | --- | --- | --- | --- |
| Exact substring search | Identical character sequence | Simple and predictable | Misses variants and gives weak ranking | No |
| BM25 | Overlapping tokens weighted by rarity and length | Names, acronyms, numbers, technologies | No semantic understanding or synonyms | Yes, in memory |
| Dense vector search | Semantic proximity between embeddings | Paraphrases and concept similarity | Can blur precise identifiers | Yes, Qdrant |
| RRF | Rank positions from multiple lists | Robustly combines unlike retrievers | Does not inspect text or create confidence | Yes |
| Score averaging | Numeric scores from multiple systems | Simple when scores are calibrated alike | Unsafe when score scales differ | No |
| Sparse vectors | Learned or weighted term vectors in a vector DB | Server-side hybrid search at larger scale | More infrastructure than this corpus needs | No |
| Reranker | A separate model scores each query-document pair | Can improve final ordering | Extra latency, cost, and complexity | No |

BM25 and vector retrieval produce candidates. RRF combines candidates. A
reranker, if added one day, would be a later stage after candidate retrieval;
it is not a replacement name for RRF.

## Startup and Drift Detection

`_initialize_rag` in `backend/main.py` requires all of the following:

- `USE_RAG=true`;
- `OPENAI_API_KEY`;
- `QDRANT_URL`;
- a reachable Qdrant service, plus `QDRANT_API_KEY` when the cluster requires
  it.

If any requirement is missing or initialization raises, startup records the
failure and leaves `app.state.rag_pipeline` as `None`. The app continues in
static-fallback mode.

When initialization succeeds, `initialize_rag_pipeline` follows this path:

```text
create collection if absent
        │
        ├─ collection empty ─> build corpus ─> embed and index ─> build BM25
        │
        └─ collection populated
                ├─ scroll all payloads and rebuild BM25 (no embedding calls)
                ├─ build the current local corpus
                ├─ compare stored and current (title, text) pairs
                ├─ same  ─> keep collection; startup is inexpensive
                └─ drift ─> delete/recreate/re-embed the collection
```

The drift check makes deployments self-healing when checked-in source content
changes. It compares title and text, not every payload metadata field. A change
only to tags, timeframe, or type may therefore require a manual reindex. The
set comparison also does not preserve duplicate counts and does not validate
the embedding model, vector dimension, distance setting, or payload schema.

The drift check and destructive reindex share one best-effort exception
boundary. A comparison failure leaves the scrolled Qdrant/BM25 snapshot in
place. A reindex failure after collection deletion is more serious: Qdrant may
be empty while the pipeline object remains initialized and its in-memory BM25
still reflects the old payloads. In that state `/health/rag` can report
`mode="rag"` alongside zero points. Correct the upstream failure, run the admin
reindex again, verify the count plus a non-cached retrieval, and restart every
replica so their BM25 copies agree.

## Deployment Topology

Railway builds the checked-in Dockerfile on Python 3.12 and starts Uvicorn with
one worker by default. Qdrant is an external persistent service, so vectors
survive an application redeploy. BM25 is ephemeral process memory and is
rebuilt for every new app process.

RAG initialization runs synchronously while the FastAPI app is constructed. A
matching warm collection avoids document embeddings, while an empty or drifted
collection can add startup work. Initialization failures fail open to static
mode. A green Railway deployment proves that the app process started; it does
not by itself prove that OpenAI, Qdrant, BM25, or an end-to-end retrieval query
is healthy.

## Request-Time Flow

For a normal chat request:

1. FastAPI validates the request and applies quotas/guardrails.
2. `_prepare_generation` starts retrieval and model routing concurrently.
3. Retrieval runs in a worker thread because the OpenAI and Qdrant clients used
   by `RAGPipeline` are synchronous. This prevents blocking the async event
   loop.
4. `search` embeds the question, asks Qdrant for vector candidates, calculates
   BM25 candidates, and fuses them with RRF.
5. `retrieve_rag_context` formats each result as `[Context N: title]` followed
   by its text.
6. The system prompt, retrieved context, and conversation messages go to the
   routed Claude model.
7. Status events, answer tokens, final source titles, and follow-ups stream to
   the browser over server-sent events (SSE).

The LLM sees retrieved text, not embeddings, BM25 scores, or RRF math.
Retrieval searches only the latest user message; it does not rewrite a vague
follow-up using conversation history. Claude still receives the permitted
conversation history during generation.

Starter-question answers have a separate cache. After the first answer is
cached, later first-turn cache hits skip retrieval and generation and report
`used_rag=false` with no sources. Starter questions are therefore poor probes
of live RAG health.

There are also two different source concepts in the UI:

- SSE source titles report which chunks were supplied as candidate context;
- `buildAnswerCitations` separately infers clickable answer citations using
  source titles and response-text matching rules.

Neither is claim-level entailment. `used_rag=true` means non-empty retrieved
context was injected, not that every answer sentence was proven by it.

The two chat APIs expose sources differently: `/api/chat` returns title
strings, while `/api/chat/stream` sends `{title, score}` objects in status and
completion events. The browser intentionally renders titles without treating
the raw vector score as confidence.

RAG powers normal chat retrieval. JD fit analysis deliberately uses the compact
static resume summary, while MCP, `/api/resume`, `/llms.txt`, and PDF delivery
read resume data through separate paths.

Each embedding request has a 10-second timeout and up to three attempts with
exponential waits, so eventual static fallback after an OpenAI problem may not
be immediate. Chat input defaults to a 2,000-character maximum. Retrieval
limits document count to four, but there is no separate final token budget that
truncates the combined retrieved context.

## Failure and Fallback Behavior

Static fallback is a supported operating mode, not an unhandled error.
`retrieve_rag_context` uses a compact summary derived from `data/resume.json`
when:

- RAG is disabled;
- initialization failed or required configuration is missing;
- vector and BM25 retrieval both return no candidates;
- query embedding, Qdrant search, or other retrieval code raises.

The summary includes personal overview, every role with up to its first three
achievements, every project with up to its first two highlights, all skills and
education, and up to five certifications. It does not include the long-form
`data/projects/*.md` documents, so basic resume questions remain available but
project-detail recall may be lower.

Two consequences are worth understanding:

1. `search` embeds the query before it runs BM25. If the OpenAI embedding call
   fails, the outer fallback handles the request; BM25 does not continue alone.
2. A Qdrant query failure also falls back to the static resume even though the
   in-memory BM25 index exists.

Those are deliberate simplicity/reliability tradeoffs in the current code,
not claims that the lexical lane is independently fault tolerant.

## Operations Runbook

### Environment variables

Never paste values into documentation or commit `.env`.

| Variable | Purpose |
| --- | --- |
| `USE_RAG` | Enables or disables retrieval |
| `OPENAI_API_KEY` | Creates chunk and query embeddings |
| `QDRANT_URL` | Selects the Qdrant cluster endpoint |
| `QDRANT_API_KEY` | Authenticates to Qdrant Cloud when required |
| `DATA_DIR` | Selects the directory containing `resume.json` and `projects/` |
| `ADMIN_TOKEN` | Protects production reindex endpoints |

Changing a Qdrant API key for the same cluster does not change stored vectors.
Rotate safely: create/enable the new credential, update Railway, deploy, verify
`/health/rag` and a non-cached retrieval, and only then revoke the old key. Every
environment currently uses the collection name `resume`, so confirm the
endpoint belongs to the intended environment before deploying credentials. A
brand-new or empty cluster is populated during startup. Run an explicit
reindex if an immediate rebuild is needed.

### Check health

```bash
curl --fail --silent --show-error https://www.dakotaradigan.io/health/rag
```

A fully healthy response has:

```json
{
  "rag_enabled": true,
  "rag_initialized": true,
  "qdrant_configured": true,
  "mode": "rag",
  "collection_exists": true,
  "points_count": 26,
  "vector_db_live": true
}
```

The count can change when the source corpus changes. The invariant is a
non-empty collection whose count matches `build_corpus`, not the number 26
forever.

`/health/rag` live-checks collection existence and point count, but it always
returns an HTTP response even when that check fails. It does not call OpenAI,
run a real hybrid query, prove BM25 is populated, compare the deployed corpus,
or measure retrieval quality. Treat it as infrastructure health rather than an
end-to-end readiness test.

### Reindex after source changes

Startup detects title/text drift after a restart, but the admin endpoint is the
way to refresh the running deployment immediately:

```bash
curl --fail --silent --show-error \
  -X POST \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  https://www.dakotaradigan.io/admin/rag/reindex
```

Check the most recent reindex state:

```bash
curl --fail --silent --show-error \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  https://www.dakotaradigan.io/admin/rag/reindex/status
```

The endpoint:

1. requires the admin token in production;
2. rejects a second simultaneous reindex in the same app process;
3. deletes and recreates the collection;
4. re-embeds every current chunk;
5. rebuilds BM25;
6. clears cached resume-derived content.

Reindexing spends embedding calls and is destructive rather than blue/green.
If it fails after deletion, the app can fall back to static context until a
successful retry. The lock is process-local, so a future multi-replica deploy
would need distributed coordination or an external indexing job. Reindexing
through one replica also rebuilds only that process's BM25 copy; other replicas
could continue using stale lexical state until restarted or explicitly
refreshed. Normal searches do not acquire the reindex lock, so requests during
delete/recreate may temporarily fall back or retrieve from stale in-memory
lexical state.

### Normal data-change checklist

1. Edit `data/resume.json` or `data/projects/*.md`.
2. Print and review the resulting chunk titles.
3. Run offline tests.
4. Deploy through a reviewed PR.
5. Let startup drift detection rebuild, or invoke the protected reindex
   endpoint for an immediate refresh.
6. Confirm `/health/rag` and the point count.
7. Ask a precise project question and verify the returned source title and
   factual answer.
8. Re-run the approved retrieval eval when chunk boundaries, titles, or
   retrieval-relevant content changed.

### Troubleshooting map

| Symptom | First checks | Likely action |
| --- | --- | --- |
| `rag_enabled=false` | `USE_RAG` | Correct the variable and redeploy if RAG should be on |
| `rag_initialized=false` | Startup logs, OpenAI key, Qdrant URL/key | Fix configuration or reachability; static fallback is active meanwhile |
| `collection_exists=false` or zero points | Qdrant endpoint and startup/reindex logs | Populate the new cluster or retry reindex |
| Point count differs from local corpus | `DATA_DIR`, mounted volume, deployed commit, chunk-title printout | Align the production source and reindex |
| Correct source not retrieved | Actual chunk title/text, BM25 tokens, vector threshold, retrieval eval | Diagnose retrieval before changing the prompt |
| Correct source retrieved but answer wrong | Context formatting, system prompt, generator eval | Diagnose generation rather than retrieval |
| A result once displayed `0.00` | Check whether it was BM25-only | Treat it as missing vector score, not zero confidence |
| Works until restart, then exact terms degrade | BM25 scroll rebuild and pagination | Verify `_rebuild_keyword_index_from_qdrant` ran successfully |

## Testing Strategy

### Offline tests

`backend/test_rag.py` constructs pipelines without invoking the real
constructor, mocks embeddings, and mocks Qdrant. The tests cover:

- Markdown section chunking and short-section merging;
- missing project-directory behavior;
- BM25 exact-term ranking;
- deterministic RRF ordering;
- the no-signal result;
- paginated Qdrant scroll on cold start;
- startup skip when the stored corpus matches;
- automatic reindex on title/text drift;
- context success and static fallback.

Run just the RAG tests:

```bash
PYTHONPATH=backend USE_RAG=false ./venv/bin/python -m unittest backend.test_rag -v
```

Run the same offline suite CI uses:

```bash
PYTHONPATH=backend USE_RAG=false ./venv/bin/python -m unittest discover -s backend -p 'test*.py' -v
```

Unit tests that require an OpenAI key or network access are incorrectly scoped.

### Opt-in Qdrant integration test

```bash
USE_RAG=false \
RUN_INTEGRATION=1 \
QDRANT_URL="$QDRANT_URL" \
QDRANT_API_KEY="$QDRANT_API_KEY" \
PYTHONPATH=backend \
./venv/bin/python -m unittest backend.test_rag -v
```

The integration test creates an isolated temporary collection and cleans it up
best-effort. It mocks embeddings with deterministic zero vectors, so it tests
the Qdrant integration rather than OpenAI's semantic quality. Keep
`USE_RAG=false`: importing the application during the test must not initialize
or reindex the normal `resume` collection.

## Retrieval Evaluation

Unit tests prove the algorithms behave as coded. Retrieval evals ask whether
the system returns the right real chunk for realistic questions.

The private, gitignored golden dataset uses this schema:

```json
{"id":"retrieval_001","query":"What vector DB did Ben AI use?","expected_titles":["Ben AI: Intelligent Benchmark Assistant — Key Technical Features"],"category":"project_fact"}
```

The evaluator reports:

- **Hit-rate@4:** fraction of questions with at least one expected title in the
  top 4;
- **Recall@4:** fraction of all expected titles recovered in the top 4;
- **MRR:** average reciprocal position of the first expected title;
- category breakdowns and explicit misses.

> **Operational warning:** this evaluator is not read-only. It initializes the
> configured `resume` collection and startup drift detection can delete,
> recreate, and re-embed that collection. It also spends OpenAI embedding calls
> and writes an ignored result file. Run it only after Dakota approves the
> dataset or revision **and** explicitly approves the intended Qdrant target.
> The script has no collection-name option: never run it with production
> Qdrant credentials. Use an isolated non-production cluster and verify its
> endpoint without printing keys.

After those approvals and checks:

```bash
python evals/scripts/run_retrieval_eval.py --k 4
```

Dataset and result files stay out of Git. Scripts, schemas, methodology, and an
approved summary belong in Git.

The recorded 2026-07-19 baseline used 35 approved cases against a 25-chunk
corpus: hit-rate@4 `0.886`, recall@4 `0.886`, and MRR `0.838`. The corpus later
became 26 chunks. Treat the numbers as a historical baseline until the approved
dataset is rerun against the current corpus; do not present them as calibrated
answer confidence.

The February response/judge evaluation and the July retrieval baseline are
different historical snapshots. The first measures generated responses; the
second measures exact-title retrieval. Neither is a combined end-to-end quality
score.

The Pinecone/Qdrant question is an important regression case: Ben AI used
Pinecone, while this Resume Assistant uses Qdrant. A retriever that blends the
two projects can produce a polished but technically wrong answer.

## Historical Documents

`docs/plans/production-upgrade-handoff.md` and
`docs/plans/chatgpt-work-packet.md` describe the approved implementation plan
and assignment that produced this feature. Their projected chunk counts,
unchecked task boxes, and pre-implementation code descriptions are historical.
Use this handoff and the current source code for present behavior; use the plan
files to understand the original decisions and constraints.

## Important Tradeoffs and Limits

1. **Small-corpus optimization.** In-process BM25 is easy to inspect and cheap
   for 26 chunks. It is not the architecture for millions of documents.
2. **One embedding dependency at query time.** OpenAI failure causes static
   fallback before BM25 can operate independently.
3. **One vector dependency.** Qdrant query failure also causes static fallback.
4. **Hard-coded vector contract.** The collection assumes 1,536 dimensions.
   Changing to an embedding model with a different shape requires collection
   recreation and full reindexing.
5. **Destructive refresh.** Reindex deletes then recreates the collection; it
   is not an atomic alias swap.
6. **Per-process lexical state.** Every worker rebuilds its own BM25 index.
7. **Basic tokenization.** There is no stemming, synonym expansion, fuzzy
   matching, language analysis, or stopword list.
8. **No reranker.** RRF is the final ordering stage. This keeps cost and
   latency low but leaves room for a measured reranking experiment.
9. **Title/text drift only.** Automatic drift detection does not compare all
   metadata fields, duplicate counts, or the embedding/index configuration.
10. **Sources are retrieval provenance.** A displayed title means the chunk
    was supplied to Claude; it is not sentence-level proof that every generated
    statement came from that chunk. The system prompt and conversation history
    are also supplied to the model.
11. **Schema compatibility is assumed.** Startup treats an existing collection
    as usable without validating its vector dimension or distance setting.
12. **External data flow.** OpenAI receives source text during indexing and
    user questions during query embedding; Qdrant stores full chunk payloads.
    The phone field is deliberately excluded, but the system should not be
    described as PII-free.

## Why This Design Fits This Product

- The corpus is tiny and changes infrequently.
- Exact technical terms matter in a portfolio viewed by interviewers.
- Users also ask broad, paraphrased recruiter questions.
- RRF avoids brittle score normalization between lexical and semantic search.
- A local BM25 implementation is easier to explain and operate than adding
  Elasticsearch or Qdrant sparse vectors at this size.
- Static fallback keeps the public site useful during retrieval outages.
- Direct SDK calls keep the critical retrieval behavior visible in one file.

The architecture is deliberately not the most elaborate possible RAG stack.
Its credibility comes from explicit tradeoffs, offline tests, a human-approved
golden set, live health checks, and failure behavior that can be explained.

## Learning Path

Complete these in order. The first five require no production credentials.

### Exercise 1: Inspect the corpus

Run the corpus-print command. Explain why a resume role is one chunk while a
long project document is split by H2. Identify the title that should answer
"What vector DB did Ben AI use?"

### Exercise 2: Trace one Qdrant point

Start with one `DocumentChunk`, then trace how `index_chunks` creates its
embedding, point id, and payload. Explain which fields Qdrant searches and
which fields Claude ultimately reads.

### Exercise 3: Calculate a BM25 intuition

Choose the query `Pinecone benchmark`. Find which chunks contain each token.
Predict why `Pinecone` should receive more weight than a common word such as
`project`, then compare the prediction with `_bm25_rank` in an offline test.

### Exercise 4: Calculate RRF by hand

Use the three-document example in this document. Change document A from vector
rank 1 to rank 3. Confirm why document B still wins through agreement.

### Exercise 5: Follow cold start

Read `test_cold_start_scroll_rebuild_paginates`. Explain why `with_vectors` is
false, why the offset must be carried forward, and why `embed_text` must not be
called.

### Exercise 6: Separate retrieval from generation

For a wrong answer, inspect the returned source titles first:

- wrong source: investigate chunking/retrieval;
- right source but wrong statement: investigate prompt/generation;
- no source and `used_rag=false`: first rule out an intentional starter-cache
  hit, then investigate fallback and health.

### Exercise 7: Read production health

Call `/health/rag` and explain each field. Compare `points_count` with a local
`build_corpus` count. Do not assume a green deployment proves Qdrant is live.

### Exercise 8: Design, do not immediately build, one improvement

Pick one limitation: independent BM25 fallback, blue/green reindexing,
metadata-aware drift, or a reranker. State a measurable hypothesis, the
smallest experiment, added failure modes, latency/cost impact, and the eval
that would justify shipping it.

## Questions Worth Being Able to Answer

1. Why use OpenAI embeddings when Claude writes the answer?
2. What does a 1,536-dimensional vector represent, and what does it not
   represent?
3. What does Qdrant persist that the in-process BM25 index does not?
4. Why does BM25 favor rare terms, and why does it normalize document length?
5. Why is RRF safer here than adding BM25 and cosine scores directly?
6. Why can a returned vector score of `0.0` still represent a useful result?
7. What exactly happens on a warm deployment with an already-populated
   collection?
8. What triggers automatic reindexing, and what metadata-only change can it
   miss?
9. Under which failures does the app use static context?
10. Why does static fallback preserve availability but reduce project-detail
    coverage?
11. How would you prove a bad answer is a retrieval problem rather than a
    generation problem?
12. Which evidence supports the current tuning, and why is the old 25-chunk
    baseline historical after the corpus changed?
13. What breaks if the embedding model's vector dimension changes?
14. Why is process-local reindex locking adequate today but risky with several
    replicas?
15. What measurement would justify adding a reranker or server-side sparse
    retrieval?

If these can be answered from the code rather than memorized from this handoff,
the feature is understood deeply enough to maintain and defend in an interview.
