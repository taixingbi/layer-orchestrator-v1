"""ROUTER_MODEL resolution for intent router."""

from app.config import resolve_router_model, settings


def test_resolve_router_model_request_override(monkeypatch):
    monkeypatch.setattr(settings, "router_model", "env-router")
    monkeypatch.setattr(settings, "llm_model", "base-llm")
    assert resolve_router_model("req-adapter") == "req-adapter"


def test_resolve_router_model_env(monkeypatch):
    monkeypatch.setattr(settings, "router_model", "router-qwen2.5-7b-sft-v1.00")
    monkeypatch.setattr(settings, "llm_model", "Qwen/Qwen2.5-7B-Instruct")
    assert resolve_router_model(None) == "router-qwen2.5-7b-sft-v1.00"
    assert resolve_router_model("") == "router-qwen2.5-7b-sft-v1.00"


def test_resolve_router_model_falls_back_to_llm_when_router_equals_llm(monkeypatch):
    monkeypatch.setattr(settings, "llm_model", "Qwen/Qwen2.5-7B-Instruct")
    monkeypatch.setattr(settings, "router_model", "Qwen/Qwen2.5-7B-Instruct")
    assert resolve_router_model(None) == "Qwen/Qwen2.5-7B-Instruct"
