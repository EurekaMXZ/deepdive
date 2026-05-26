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

Use this tree as the default target. If the repository lacks a listed area,
create the closest relevant document and explicitly state that the area was not
found in the snapshot. If the repository contains additional material areas,
add focused sibling folders or documents without flattening the required tree.

Each substantive document must:

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

Do not finalize a document that is only a bullet list of paths. Do not add
decorative formulas or diagrams when the topic does not need them.
