"""Headless Claude Code runner.

Runs `claude --print` inside a per-job folder using the owner's Max-plan login only.
ANTHROPIC_API_KEY is stripped from the child env so it can never fall back to API billing.
CONFIRM flags against `claude --help` at build time; they change between releases.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

USAGE_LIMIT_RE = re.compile(r"(usage limit|rate limit|limit reached|5-hour|too many requests)", re.I)
WINDOW_SECONDS = 5 * 3600


@dataclass
class BuildResult:
    ok: bool
    output: str
    usage_limited: bool = False
    resume_at: float = 0.0


def default_executor(cmd: list[str], cwd: Path, env: dict, timeout: int):
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


class ClaudeCodeRunner:
    def __init__(self, jobs_dir: Path, executor=default_executor, binary: str = "claude", timeout: int = 3600):
        self.jobs_dir, self.executor, self.binary, self.timeout = Path(jobs_dir), executor, binary, timeout

    def job_dir(self, job_id: int) -> Path:
        d = (self.jobs_dir / f"job_{job_id}").resolve()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def run(self, job_id: int, prompt: str, now: float | None = None) -> BuildResult:
        cwd = self.job_dir(job_id)
        env = {k: v for k, v in os.environ.items()
               if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "DEEPSEEK_API_KEY")}
        cmd = [self.binary, "--print", prompt, "--permission-mode", "acceptEdits"]
        code, out, err = self.executor(cmd, cwd, env, self.timeout)
        now = now if now is not None else time.time()
        if code != 0 and USAGE_LIMIT_RE.search(out + err):
            return BuildResult(False, (out + err)[-500:], True, now + WINDOW_SECONDS)
        return BuildResult(code == 0, (out if code == 0 else out + err)[-4000:])
