from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


class PythonQualityContractTest(unittest.TestCase):
    def test_pyright_uses_global_strict_type_checking(self) -> None:
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        pyright = pyproject["tool"]["pyright"]

        self.assertEqual(pyright["typeCheckingMode"], "strict")
        self.assertNotIn("strict", pyright)


class ArchitectureDocumentationContractTest(unittest.TestCase):
    def test_proposal_treats_document_artifacts_as_current_agent_outputs(self) -> None:
        proposal = Path("docs/PROPOSAL.md").read_text(encoding="utf-8")

        self.assertIn("document artifact", proposal)
        self.assertIn("document_create", proposal)
        self.assertIn("document_finalize", proposal)
        self.assertNotIn("当前阶段不实现独立的最终文档或报告输出", proposal)


if __name__ == "__main__":
    unittest.main()
