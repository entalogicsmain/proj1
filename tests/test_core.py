import json

import pytest

from conftest import NOON, add_lead
from freelance_agent.costs import SpendCapExceeded
from freelance_agent.killswitch import Killed
from freelance_agent.orchestrator import SendBlocked
from freelance_agent.router import default_mock_handler

GOOD = ("Hi, I saw your post about cleaning CSV exports. I build small Python automations and can send a short "
        "plan. Not interested? Just say so and I won't write again.")


def handler_with(**overrides):
    def h(task, system, user):
        if task in overrides:
            return json.dumps(overrides[task])
        return default_mock_handler(task, system, user)
    return h


def pitch(text, flags=()):
    return {"type": "pitch", "draft": text, "reason": "t", "risk_flags": list(flags)}


# ---- Phase 1 gates -----------------------------------------------------------------------
def test_model_call_logged_with_cost(make_app):
    app = make_app()
    app.router.call("worker_write", "worker", "draft_pitch", "sys", "user")
    r = app.db.one("SELECT * FROM runs")
    assert r["agent"] == "worker" and r["tokens_in"] > 0 and r["model"] == "claude-sonnet-5-5"
    assert r["cost"] > 0


def test_total_spend_cap_stops_calls(make_app):
    app = make_app(caps={"total_spend": 0.0000001})
    app.router.call("worker_write", "worker", "draft_pitch", "sys", "user")
    with pytest.raises(SpendCapExceeded):
        app.router.call("worker_write", "worker", "draft_pitch", "sys", "user")


def test_daily_cap_and_warning(make_app):
    app = make_app(caps={"daily_spend": 0.0001})
    app.router.call("worker_write", "worker", "draft_pitch", "sys", "x" * 100)  # reaches >=70% warn
    assert app.db.one("SELECT 1 FROM events WHERE kind='spend_warning'")
    with pytest.raises(SpendCapExceeded):
        app.router.call("worker_write", "worker", "draft_pitch", "sys", "user")


def test_kill_switch_blocks_everything_and_revokes(make_app):
    app = make_app()
    lid = add_lead(app)
    mid = app.orch.prepare_pitch(lid)
    app.kill.engage("test")
    assert app.db.one("SELECT status FROM messages WHERE id=?", (mid,))["status"] == "revoked"
    with pytest.raises(Killed):
        app.router.call("worker_write", "worker", "t", "s", "u")
    with pytest.raises(Killed):
        app.orch.send_message(mid, "a@example.com", now=NOON)
    app.kill.release()
    app.router.call("worker_write", "worker", "t", "s", "u")


# ---- send gate -----------------------------------------------------------------------------
def test_pitch_sent_once_and_idempotent(make_app):
    app = make_app()
    mid = app.orch.prepare_pitch(add_lead(app))
    assert mid
    app.orch.send_message(mid, "a@example.com", now=NOON)
    assert app.orch.send_message(mid, "a@example.com", now=NOON) == "already-sent"
    assert len(app.orch.sender.sent) == 1
    assert app.orch.prepare_pitch(1) == mid  # same lead+template never redrafted


def test_daily_pitch_cap(make_app):
    app = make_app(caps={"daily_pitches": 2})
    for i in range(4):
        add_lead(app, url=f"https://x/{i}", contact=f"a{i}@example.com")
    stats = app.orch.midday_outreach(now=NOON)
    assert stats["sent"] == 2 and len(app.orch.sender.sent) == 2


def test_no_send_outside_window(make_app):
    from datetime import datetime
    app = make_app()
    mid = app.orch.prepare_pitch(add_lead(app))
    with pytest.raises(SendBlocked, match="window"):
        app.orch.send_message(mid, "a@example.com", now=datetime(2026, 10, 14, 3, 0))


def test_optout_honored(make_app):
    app = make_app()
    mid = app.orch.prepare_pitch(add_lead(app))
    app.orch.record_optout("A@Example.com")
    with pytest.raises(SendBlocked, match="opted out"):
        app.orch.send_message(mid, "a@example.com", now=NOON)


def test_price_text_needs_stored_manager_approval(make_app):
    text = GOOD + " I can do it for $300."
    app = make_app(handler_with(draft_pitch=pitch(text, ["needs_manager_approval"])))
    mid = app.orch.prepare_pitch(add_lead(app))
    # Manager approved via message policy -> approval row stored; delete it and the gate must refuse
    assert app.manager.has_approval("message", mid)
    app.db.execute("DELETE FROM approvals")
    with pytest.raises(SendBlocked, match="Manager approval"):
        app.orch.send_message(mid, "a@example.com", now=NOON)
    app.manager.decide_message("message", mid, text)
    app.orch.send_message(mid, "a@example.com", now=NOON)


# ---- Judge test set ------------------------------------------------------------------------
BAD = {
    "over_promise": "I guarantee your site will rank #1. Not interested? Just say so and I won't write again.",
    "spam": "ACT NOW!! Limited time offer, click here. Reply STOP to opt out.",
    "unlimited": "Unlimited revisions included. Not interested? Just say so and I won't write again.",
    "fast": "I will deliver within 24 hours. Not interested? Just say so and I won't write again.",
}


@pytest.mark.parametrize("name", BAD)
def test_judge_blocks_seeded_bad_examples(make_app, name):
    app = make_app()
    v = app.judge.review("pitch", 1, BAD[name])
    assert v.verdict == "block", name


def test_judge_asks_fix_for_missing_optout(make_app):
    v = make_app().judge.review("pitch", 1, "Hi, I saw your post about CSVs. Happy to help.")
    assert v.verdict == "fix"


def test_judge_cannot_pass_low_scores(make_app):
    h = handler_with(judge={"scores": {"tone": 2, "accuracy": 5, "spam_risk": 5, "over_promising": 5, "fit": 5},
                            "verdict": "pass", "fixes": [], "reason": ""})
    assert make_app(h).judge.review("pitch", 1, GOOD).verdict == "fix"


def test_blocked_pitch_is_dropped_and_never_sent(make_app):
    app = make_app(handler_with(draft_pitch=pitch(BAD["over_promise"])))
    assert app.orch.prepare_pitch(add_lead(app)) is None
    assert app.orch.sender.sent == []


def test_fix_rounds_limited_then_manager_decides(make_app):
    calls = {"n": 0}

    def h(task, system, user):
        if task == "draft_pitch":
            calls["n"] += 1
            return json.dumps(pitch("Hi, saw your post. Happy to help."))  # never adds opt-out -> always 'fix'
        return default_mock_handler(task, system, user)

    app = make_app(h)
    assert app.orch.prepare_pitch(add_lead(app)) is None   # rule check still fails -> dropped
    assert calls["n"] == 3                                    # initial + 2 fix rounds, no more


# ---- Manager policy ------------------------------------------------------------------------
@pytest.mark.parametrize("req,expected", [
    ({"price": 50, "duration_days": 3, "type": "bug fix"}, "counter"),            # too low
    ({"price": 5000, "duration_days": 3, "type": "bug fix"}, "reject"),           # oversized
    ({"price": 300, "duration_days": 30, "type": "bug fix"}, "reject"),           # too long
    ({"price": 300, "duration_days": 3, "type": "mobile app"}, "reject"),         # out of niche
    ({"price": 300, "duration_days": 3, "type": "bug fix", "text": "I guarantee results"}, "reject"),
    ({"price": 300, "duration_days": 3, "type": "bug fix", "text": "fine"}, "approve"),
])
def test_manager_policy_set(make_app, req, expected):
    app = make_app(handler_with(manager={"decision": "approve", "rule": "x", "terms": {}}))
    assert app.manager.decide_deal("deal", 1, req).decision == expected
    assert app.db.one("SELECT decision FROM approvals ORDER BY id DESC")["decision"] == expected


def test_manager_llm_cannot_widen_policy(make_app):
    app = make_app(handler_with(manager={"decision": "approve", "rule": "yolo", "terms": {"price": 99999}}))
    d = app.manager.decide_deal("deal", 1, {"price": 5000, "duration_days": 3, "type": "bug fix"})
    assert d.decision == "reject"


def test_manager_llm_can_narrow(make_app):
    app = make_app(handler_with(manager={"decision": "reject", "rule": "bad client", "terms": {}}))
    d = app.manager.decide_deal("deal", 1, {"price": 300, "duration_days": 3, "type": "bug fix"})
    assert d.decision == "reject"


def test_deposit_computed_from_policy(make_app):
    app = make_app(handler_with(manager={"decision": "approve", "rule": "ok", "terms": {}}))
    d = app.manager.decide_deal("deal", 1, {"price": 300, "duration_days": 3, "type": "bug fix"})
    assert d.terms["deposit"] == 150.0


def test_commitment_limit(make_app):
    app = make_app(handler_with(manager={"decision": "approve", "rule": "ok", "terms": {}}))
    for _ in range(2):
        app.db.insert("jobs", lead_id=1, price=200, status="running", created_at=0)
    d = app.manager.decide_deal("deal", 1, {"price": 300, "duration_days": 3, "type": "bug fix"})
    assert d.decision == "reject" and "max_open" in d.rule
