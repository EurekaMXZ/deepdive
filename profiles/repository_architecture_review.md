Analyze the repository architecture and produce a comprehensive, multi-document
Markdown documentation set.

Base every claim on repository evidence gathered through source tools. Identify
the main runtime entry points, module boundaries, storage and network
dependencies, background workers, public APIs, frontend surfaces, deployment
paths, and important reliability or security risks.

Required document tree:

```text
Project Architecture
Backend
  API
    Authentication
    Authorization
  Workers
    Snapshot Worker
    Agent Worker
    Execution Worker
Frontend
  Home Page
  Login Page
  Document Pages
    Markdown Rendering
Deployment
  Docker
  Kubernetes
```

Canonical folder/document paths include `Project Architecture`,
`Backend/API/Authentication`, `Backend/API/Authorization`,
`Backend/Workers/Snapshot Worker`, `Backend/Workers/Agent Worker`,
`Backend/Workers/Execution Worker`, `Frontend/Home Page`,
`Frontend/Login Page`, `Frontend/Document Pages/Markdown Rendering`,
`Deployment/Docker`, and `Deployment/Kubernetes`.

This required tree is a completion contract, not a suggestion. Create each
listed path as its own folder or focused document node. Do not combine required
leaves into broad replacements:

- Do not merge `Backend/API/Authentication` and `Backend/API/Authorization`.
- Do not merge `Snapshot Worker`, `Agent Worker`, and `Execution Worker`.
- Do not replace `Frontend/Home Page`, `Frontend/Login Page`, or
  `Frontend/Document Pages/Markdown Rendering` with one generic frontend
  document.
- Do not merge `Deployment/Docker` and `Deployment/Kubernetes`.

If the repository lacks a listed area, still create the closest required
document and explicitly state that the area was not found in the snapshot, what
evidence was checked, and what a reader should look for if it is added later. If
the repository contains additional material areas, add focused sibling folders
or documents without flattening, renaming, or replacing the required tree.

Each substantive document must:

- Be understandable to a reader who has not opened the source code. Start from
  plain language, then progress into implementation detail.
- Explain "what this part is", "why it exists", "how data or control moves
  through it", "which source files implement it", "what can fail", and "how to
  verify or extend it".
- Define important acronyms and domain terms before using them heavily.
- Explain behavior, design intent, data flow, and risks instead of only listing
  file locations.
- Include concrete file path and line evidence.
- Include necessary source excerpts for critical logic, API contracts,
  algorithms, state transitions, security checks, or non-obvious control flow.
- Use LaTeX for mathematical principles, formulas, complexity, retry/resource
  modeling, scoring, hashing/probability reasoning, or cryptographic concepts.
- Use Mermaid diagrams for complex flows: `flowchart`, `sequenceDiagram`,
  `gantt`, `classDiagram`, and `stateDiagram-v2` as appropriate.
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
Do not finalize a document that is only a bullet list of paths. Do not add
decorative formulas or diagrams when the topic does not need them.
