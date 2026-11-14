# RFP Application & AI Strategy Work
## Overview & Status
A custom RFP application Dakota built in his AI Strategy role at Parametric Portfolio (Morgan Stanley). It is currently in UAT (user acceptance testing). Instead of one large prompt, it runs a modular drafting workflow: separate steps that coordinate the opportunity context, approved content, reusable skills, quality checks, and SME review. It sits alongside Ben AI, his benchmark assistant that is already deployed in production.

## How the Drafting Workflow Works
The workflow treats an RFP response as a set of coordinated parts rather than a single generation step:
- **Opportunity context**: the details of the specific RFP the response is for
- **Approved content**: answers draw on content the firm has already approved, which matters in a regulated industry
- **Reusable skills**: repeatable drafting skills that SMEs help develop and improve
- **Quality checks**: checks on the drafted responses
- **SME review**: subject-matter experts review the drafts

## Capturing Institutional Knowledge
Dakota developed context-capture and retrieval approaches that keep the knowledge an RFP answer depends on, not just the text of past answers. They preserve:
- Decision rules and the exceptions to them
- Product metadata
- The surrounding source context, so a retrieved passage keeps its meaning

This knowledge comes from SME discussions and historical RFPs.

## Evaluation
Evals are central to how Dakota builds. He refined prompts and workflow behavior using historical examples and held-out RFP cases, measuring:
- Evidence selection: did the workflow pull the right source material?
- Response coverage: did the draft answer everything the question asked?
- Consistency
- Remaining review needs: what still requires an SME

Both the RFP application and Ben AI have extensive eval suites tracking recall, precision, and pass@1. His evals practice draws heavily on Hamel Husain's applied evals approach.

## Working with SMEs & Driving Adoption
Dakota partners with SMEs to co-design workflows and develop reusable skills with them. This helps teams build AI fluency and contribute improvements themselves.

## Discovery & Enterprise Requirements
Dakota leads AI product discovery with business teams, translating operational problems, institutional knowledge, and enterprise constraints into requirements and testable solutions. He also turns workflow designs, prepared knowledge, and evaluation examples into concrete requirements for future enterprise AI solutions.
