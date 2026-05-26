Analyze the repository architecture and produce a comprehensive, multi-document
Markdown documentation set.

Base every claim on repository evidence gathered through source tools. Identify
the main runtime entry points, module boundaries, storage and network
dependencies, background workers, public APIs, user-facing surfaces, deployment
paths, and important reliability or security risks.

Document tree requirements:

- Build a multi-level documentation tree from the repository's actual shape.
- Do not force every project into `Backend` and `Frontend` folders. Create those
  folders only when the repository contains material backend or frontend code.
- Do not create `Home Page`, `Login Page`, `Markdown Rendering`,
  `Kubernetes`, or similar product-specific documents unless repository
  evidence shows that area exists or the profile/user explicitly requires it.
- If a project is a CLI, library, bot, worker-only service, smart contract,
  mobile app, infrastructure repo, monorepo, or single-binary application,
  organize documents around its real domains instead of pretending it has
  frontend/backend layers.
- Always create a root architecture document such as `Project Architecture`.
  Under it, create evidence-backed folders for concrete domains such as API,
  CLI, Bot Runtime, Workers, Storage, Database, Cache, Messaging, Auth,
  Configuration, Observability, Deployment, SDK, Packages, or UI only when the
  repository actually contains those domains.
- For areas requested by the profile or user but absent from the repository,
  create a focused "Not Found" or "Absence" document only if that absence is
  important to the configured goal. State exactly what evidence was checked and
  what a future reader should look for if the area is added later.

Example layouts:

```text
Project Architecture
Runtime
  Entry Point
  Configuration
Telegram Bot
  Update Routing
  File Relay Flow
Storage
  PostgreSQL Schema
  Redis Cache
Deployment
  Docker Compose
```

```text
Project Architecture
Library API
  Public Types
  Error Model
Parser
  Grammar
  AST Construction
Testing
  Fixtures
```

Each substantive document must:

- Be understandable to a reader who has not opened the source code. Start from
  plain language, then progress into implementation detail.
- Explain "what this part is", "why it exists", "how data or control moves
  through it", "which source files implement it", "what can fail", and "how to
  verify or extend it".
- Define important acronyms and domain terms before using them heavily.
- Explain behavior, design intent, data flow, and risks instead of only listing
  file locations.
- Include source evidence in a reader-useful form:
  - Do not leave important evidence as only `path:line-line`.
  - When a source reference materially supports a claim, paste the relevant
    code in a fenced code block and introduce it with the file path and line
    range.
  - Keep pasted excerpts bounded to the smallest useful range. Do not paste
    whole files, generated code, dependency bundles, secrets, or unrelated
    boilerplate.
  - File paths and line ranges may still be used as labels before a code block
    or as compact secondary references for minor claims.
- Use Markdown-compliant LaTeX only when mathematical principles, formulas,
  complexity, retry/resource modeling, scoring, hashing/probability reasoning,
  or cryptographic concepts genuinely clarify the evidence:
  - Use block math with `$$` on separate lines.
  - Use inline math only with `$...$`.
  - Do not use non-standard `\(...\)` or `\[...\]` delimiters.
  - Explain each symbol before or immediately after the formula.
- Use valid Mermaid diagrams only when they clarify complex flows:
  - Use fenced blocks exactly as ```mermaid.
  - Quote labels that contain slashes, colons, parentheses, angle brackets,
    pipes, braces, or other punctuation that can break Mermaid parsing.
  - Prefer simple node IDs such as `api`, `worker`, `db`; put display text in
    quoted labels.
  - Avoid raw file paths such as `cmd/app/main.rs` inside unquoted Mermaid
    labels; write `entry["cmd/app/main.rs"]` or use a simpler label.
  - Use `flowchart` for processing pipelines and decisions, `sequenceDiagram`
    for request/response or worker timing, `gantt` for staged schedules,
    `classDiagram` for important classes/modules, and `stateDiagram-v2` for
    lifecycle/status transitions.
- Keep Markdown portable:
  - Use fenced code blocks with language tags when known.
  - Keep heading levels nested correctly.
  - Do not use custom HTML components, MDX-only syntax, admonition blocks, or
    renderer-specific Markdown extensions unless the platform explicitly
    supports them.
  - Do not use malformed tables, unterminated fences, or decorative diagrams.
- Prefer multiple sections such as Overview, Evidence, Flow, Key Source,
  Risks, and Follow-ups when the topic is non-trivial.

For each non-trivial document, prefer this section structure:

1. What This Part Is
2. Why It Exists
3. Mental Model and Key Terms
4. Request, Data, or State Flow
5. Source Walkthrough
6. Important Source Excerpts
7. Risks and Failure Modes
8. How to Verify or Extend
9. Open Questions

Use `document_finalize` for every document that satisfies these requirements.
Do not finalize a document that is only a bullet list of paths, contains broken
Markdown, uses non-standard math delimiters, contains unparseable Mermaid, or
omits necessary code excerpts for its key evidence. Do not add decorative
formulas or diagrams when the topic does not need them.
