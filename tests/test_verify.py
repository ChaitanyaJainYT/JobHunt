"""verify.py tests: HP scenario, aliases, boundaries, no false positives."""
from __future__ import annotations

from src.verify import evidenced, find_unverified_claims

EVIDENCE = "Python developer. Skilled in SQL, AWS, ETL pipelines and Git."
TEX = ("Tools: Python, SQL, Microsoft Power BI, Excel, Power Automate, AWS. "
       "Built dashboards in Power BI enabling stakeholders.")
VOCAB = ["Python", "SQL", "Power BI", "Excel", "Power Automate", "AWS",
         "Microsoft Power BI"]


def test_hp_scenario_flags_false_claims():
    bad = find_unverified_claims(TEX, [EVIDENCE], VOCAB)
    lowered = [b.lower() for b in bad]
    assert "power bi" in lowered
    assert "excel" in lowered
    assert "power automate" in lowered
    assert "python" not in lowered and "sql" not in lowered and "aws" not in lowered
    # related-but-distinct skills are never collapsed (Java vs JavaScript)
    assert find_unverified_claims("knows Java and JavaScript", ["knows Java"],
                                  ["Java", "JavaScript"]) == ["JavaScript"]


def test_aliases_count_as_evidence():
    assert evidenced("Amazon Web Services", "aws certified")
    assert evidenced("Power BI", "powerbi dashboards")
    assert evidenced("Kubernetes", "deploys to k8s daily")
    assert not evidenced("Power BI", EVIDENCE)


def test_word_boundaries_no_false_hits():
    assert not evidenced("AI", "said daily standups")
    assert evidenced("AI", "built AI solutions")
    assert not evidenced("R", "Senior developer role")
    assert not evidenced("C", "Basic computer skills")


def test_case_punct_insensitive():
    assert evidenced("CI/CD", "set up ci cd pipelines")
    assert evidenced("PostgreSQL", "postgres tuning")


def test_clean_resume_passes():
    tex = "Tools: Python, SQL, AWS. Pipelines in Python."
    assert find_unverified_claims(tex, [EVIDENCE], ["Python", "SQL", "AWS"]) == []


def test_empty_inputs_safe():
    assert find_unverified_claims("", [EVIDENCE], VOCAB) == []
    assert find_unverified_claims(TEX, [""], VOCAB) != []
    assert find_unverified_claims(TEX, [EVIDENCE], []) == []
