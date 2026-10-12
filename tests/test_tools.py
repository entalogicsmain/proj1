import os

from freelance_agent import leads
from freelance_agent.report import weekly_report
from freelance_agent.tools.claude_code import ClaudeCodeRunner
from conftest import add_lead


def test_claude_code_strips_api_key_and_isolates_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    seen = {}

    def ex(cmd, cwd, env, timeout):
        seen.update(cmd=cmd, cwd=cwd, env=env)
        return 0, "built", ""

    r = ClaudeCodeRunner(tmp_path, executor=ex).run(7, "build it")
    assert r.ok and "ANTHROPIC_API_KEY" not in seen["env"]
    assert seen["cwd"] == (tmp_path / "job_7").resolve()


def test_usage_limit_pauses_and_resume_time(tmp_path):
    ex = lambda *a: (1, "", "Claude usage limit reached")
    r = ClaudeCodeRunner(tmp_path, executor=ex).run(1, "x", now=1000.0)
    assert not r.ok and r.usage_limited and r.resume_at == 1000.0 + 5 * 3600


def test_other_failure_not_treated_as_limit(tmp_path):
    r = ClaudeCodeRunner(tmp_path, executor=lambda *a: (2, "", "syntax error")).run(1, "x")
    assert not r.ok and not r.usage_limited


def test_hn_ingest_dedupes_and_scores(make_app):
    app = make_app()
    fake = lambda url: {"hits": [{"objectID": "1", "comment_text": "Looking for a developer for a script"}]}
    got = leads.collect_hn(fake)
    assert leads.ingest(app.db, got) == 1
    assert leads.ingest(app.db, got) == 0
    assert leads.score_pending(app.db, app.worker) == 1
    assert app.db.one("SELECT score FROM leads")["score"] == 8


def test_weekly_report_matches_log(make_app):
    app = make_app()
    from conftest import NOON
    mid = app.orch.prepare_pitch(add_lead(app))
    app.orch.send_message(mid, "a@example.com", now=NOON)
    rep = weekly_report(app.db)
    assert "Pitches sent: 1" in rep and "worker" in rep
