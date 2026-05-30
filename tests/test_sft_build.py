"""Router SFT dataset builder tests."""

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SFT_SCRIPTS = REPO_ROOT / "aval" / "sft-router" / "scripts"
DPO_SCRIPTS = REPO_ROOT / "aval" / "dpo-router" / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(DPO_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(DPO_SCRIPTS))


def _load_sft_build():
    path = SFT_SCRIPTS / "build_from_gold.py"
    spec = importlib.util.spec_from_file_location("sft_build_from_gold", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _load_router_gold():
    path = DPO_SCRIPTS / "router_gold.py"
    spec = importlib.util.spec_from_file_location("router_gold", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


sft = _load_sft_build()
rg = _load_router_gold()
GOLD_DATA = REPO_ROOT / "aval" / "gold-test" / "data"


def test_build_router_completion_rag_sft():
    row = rg.GoldRow(
        question="What is Taixing Bi's visa status?",
        expected_route="rag_private_kb",
        source_file="t.csv",
    )
    out = rg.build_router_completion(row)
    assert out["route"] == "rag_private_kb"
    assert "route_detail" not in out


def test_sft_record_messages():
    row = rg.GoldRow(
        question="What is Taixing Bi's visa status?",
        expected_route="rag_private_kb",
        source_file="t.csv",
    )
    completion = rg.build_router_completion(row)
    rec = sft._sft_record(
        system_prompt="sys",
        row=row,
        completion=completion,
        meta={"question": row.question, "expected_route": "rag_private_kb"},
    )
    assert len(rec["messages"]) == 3
    assert rec["messages"][0]["role"] == "system"
    assert rec["messages"][1]["role"] == "user"
    assert rec["messages"][2]["role"] == "assistant"
    assistant = json.loads(rec["messages"][2]["content"])
    assert assistant["route"] == "rag_private_kb"
    assert "chosen" not in rec
    assert "rejected" not in rec


def test_build_sft_from_gold_csvs():
    prompt = rg.load_router_system_prompt("router-v2.00")
    train, val, stats = sft.build_sft_dataset(
        gold_data_dir=GOLD_DATA,
        system_prompt=prompt,
        include_seed_faq=False,
        include_hack=False,
        router_prompt_version="router-v2.00",
        val_ratio=0.1,
    )
    assert stats["rows_total"] >= 20
    assert stats["examples_written"] >= 10
    assert len(train) + len(val) == stats["examples_written"]
    sample = train[0]
    assert "messages" in sample and "meta" in sample
    assert len(sample["messages"]) == 3
    json.loads(sample["messages"][2]["content"])
