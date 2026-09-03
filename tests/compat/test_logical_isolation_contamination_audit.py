import sys
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

from codex_loop_runtime.delegation import LOGICAL_CAPABILITIES


class LogicalIsolationContaminationAuditTests(unittest.TestCase):
    def setUp(self):
        self.protocol = (SKILL / "references" / "logical-isolation-contamination-benchmark.md").read_text(encoding="utf-8")
        self.audit = (SKILL / "references" / "logical-isolation-contamination-audit-20260903.md").read_text(encoding="utf-8")
        self.delegation = (SKILL / "references" / "delegation.md").read_text(encoding="utf-8")
        self.skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")

    def test_runtime_capability_truth_is_not_upgraded_by_audit(self):
        self.assertFalse(LOGICAL_CAPABILITIES["fresh_model_context"])
        self.assertFalse(LOGICAL_CAPABILITIES["independent_model_instance"])
        self.assertFalse(LOGICAL_CAPABILITIES["physical_context_isolation"])
        self.assertFalse(LOGICAL_CAPABILITIES["independent_tool_sandbox"])
        self.assertTrue(LOGICAL_CAPABILITIES["behavioral_context_isolation"])
        self.assertTrue(LOGICAL_CAPABILITIES["bounded_context_projection"])

    def test_protocol_explicitly_forbids_security_or_fresh_context_inference(self):
        text = self.protocol.lower()
        self.assertIn("not a test of physical context erasure", text)
        self.assertIn("security isolation", text)
        self.assertIn("never relabel `l` as `n`", text)
        self.assertIn("do not convert `0/n` observed leakage into proof of zero leakage", text)
        self.assertIn("degraded_subagent_isolation", self.protocol.lower())

    def test_audit_records_counts_and_same_host_limitations(self):
        audit_lower = self.audit.lower()
        self.assertIn("0/12", self.audit)
        self.assertIn("0/11", self.audit)
        self.assertIn("20 adversarial logical-isolation answer trials", self.audit)
        self.assertIn("5/5 resisted", self.audit)
        self.assertIn("same host/model conversation environment", self.audit)
        self.assertIn("no genuine native fresh-context control arm", self.audit)
        self.assertIn("security/privacy/physical-context isolation", audit_lower)

    def test_domain_case_study_is_summary_only(self):
        forbidden = [
            "source_drive_id",
            "drive_id",
            "Fang Fang",
            "Yihan Hu",
            "Fredrik Piehl",
            "human_target_sha256",
        ]
        for marker in forbidden:
            self.assertNotIn(marker, self.audit)
        self.assertIn("Raw human revision material", self.audit)
        self.assertIn("are not copied into Codex Loop", self.audit)

    def test_skill_and_delegation_link_the_bounded_empirical_contract(self):
        for name in (
            "references/logical-isolation-contamination-benchmark.md",
            "references/logical-isolation-contamination-audit-20260903.md",
        ):
            self.assertIn(name, self.skill)
            self.assertIn(name, self.delegation)
        self.assertIn("never as permission to upgrade executor capability claims", self.skill)
        self.assertIn("cannot turn fresh-model", self.delegation)


if __name__ == "__main__":
    unittest.main()
