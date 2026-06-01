"""Router DPO dataset builder tests."""

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DPO_SCRIPTS = REPO_ROOT / "router-eval" / "dpo-router" / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(DPO_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(DPO_SCRIPTS))


def _load_dpo_build():
    path = DPO_SCRIPTS / "build_from_gold.py"
    spec = importlib.util.spec_from_file_location("dpo_build_from_gold", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


dpo = _load_dpo_build()
GOLD_DATA = REPO_ROOT / "router-eval" / "golden-test" / "data"


def test_build_router_completion_rag():
    row = dpo.GoldRow(
        question="What is Taixing Bi's visa status?",
        expected_route="rag_private_kb",
        source_file="t.csv",
    )
    out = dpo.build_router_completion(row)
    assert out["route"] == "rag_private_kb"
    assert "route_detail" not in out
    assert "Taixing Bi" in out["rewritten_question"]


def test_build_dpo_from_gold_csvs():
    prompt = dpo._load_router_system_prompt("router-v2.00")
    train, val, stats = dpo.build_dpo_dataset(
        gold_data_dir=GOLD_DATA,
        result_dir=None,
        system_prompt=prompt,
        include_seed_faq=False,
        include_hack=False,
        fetch_live=False,
        orchestrator_url="",
        router_prompt_version="router-v2.00",
        fetch_timeout_s=1.0,
        val_ratio=0.1,
    )
    assert stats["rows_total"] >= 20
    assert stats["pairs_written"] >= 10
    assert len(train) + len(val) == stats["pairs_written"]
    sample = train[0]
    assert "prompt" in sample and "chosen" in sample and "rejected" in sample
    chosen = json.loads(sample["chosen"])
    rejected = json.loads(sample["rejected"])
    assert chosen["route"] != rejected["route"]
    assert "route_detail" not in chosen
