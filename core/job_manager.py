"""
core/job_manager.py — Background job lifecycle for Phase 10.

Tracks processes launched with /run --background.
Jobs are NOT persisted across AIZEN restarts.

Limits:
    - Only AIZEN-owned PIDs may be killed via /kill.
    - Output is bounded (ring buffer of MAX_OUTPUT_LINES).
    - At AIZEN exit: list running jobs and offer to terminate.
"""

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.command_safety import SafetyResult, sanitize_for_log, parse_command

# ------------------------------------------------------------------
# CONSTANTS
# ------------------------------------------------------------------

MAX_JOB_OUTPUT_LINES = 500    # lines kept per job in memory

JOB_RUNNING  = "RUNNING"
JOB_EXITED   = "EXITED"
JOB_FAILED   = "FAILED"
JOB_STOPPED  = "STOPPED"


# ------------------------------------------------------------------
# JOB RECORD
# ------------------------------------------------------------------

@dataclass
class Job:
    job_id: int
    pid: int
    command: str
    cwd: str
    safety_level: str
    started_at: str
    _proc: subprocess.Popen = field(repr=False, default=None)
    _stdout_buf: List[str] = field(default_factory=list, repr=False)
    _stderr_buf: List[str] = field(default_factory=list, repr=False)
    _lock: threading.Lock  = field(default_factory=threading.Lock, repr=False)
    status: str = JOB_RUNNING
    exit_code: Optional[int] = None

    def is_alive(self) -> bool:
        if self._proc is None:
            return False
        return self._proc.poll() is None

    def poll_status(self) -> str:
        if self._proc is None:
            return self.status
        code = self._proc.poll()
        if code is None:
            self.status = JOB_RUNNING
        elif code == 0:
            self.status = JOB_EXITED
            self.exit_code = code
        else:
            self.status = JOB_FAILED
            self.exit_code = code
        return self.status

    def runtime_seconds(self) -> float:
        try:
            started = time.mktime(time.strptime(self.started_at, "%Y-%m-%dT%H:%M:%S"))
            return time.time() - started
        except Exception:
            return 0.0

    def recent_output(self, n: int = 20) -> str:
        with self._lock:
            lines = self._stdout_buf[-n:] + (
                [f"[stderr] {l}" for l in self._stderr_buf[-5:]] if self._stderr_buf else []
            )
        return "\n".join(lines)

    def _append_stdout(self, line: str):
        with self._lock:
            self._stdout_buf.append(line)
            if len(self._stdout_buf) > MAX_JOB_OUTPUT_LINES:
                self._stdout_buf = self._stdout_buf[-MAX_JOB_OUTPUT_LINES:]

    def _append_stderr(self, line: str):
        with self._lock:
            self._stderr_buf.append(line)
            if len(self._stderr_buf) > MAX_JOB_OUTPUT_LINES:
                self._stderr_buf = self._stderr_buf[-MAX_JOB_OUTPUT_LINES:]


# ------------------------------------------------------------------
# MANAGER
# ------------------------------------------------------------------

class JobManager:
    """Thread-safe registry of AIZEN background jobs."""

    def __init__(self):
        self._jobs: Dict[int, Job] = {}
        self._next_id = 1
        self._lock = threading.Lock()

    def start(
        self,
        command: str,
        cwd: str,
        safety: SafetyResult,
    ) -> tuple[bool, str, Optional[Job]]:
        """
        Launch a background process.

        Returns (success, message, job).
        """
        from core.command_safety import parse_command
        args = parse_command(command)
        if not args:
            return False, "Empty command.", None

        try:
            env = dict(os.environ)
            proc = subprocess.Popen(
                args,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            return False, f"Command not found: {args[0]}", None
        except PermissionError as e:
            return False, f"Permission denied: {e}", None
        except Exception as e:
            return False, f"Failed to start: {e}", None

        with self._lock:
            job_id = self._next_id
            self._next_id += 1
            job = Job(
                job_id=job_id,
                pid=proc.pid,
                command=command,
                cwd=cwd,
                safety_level=safety.level,
                started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                _proc=proc,
            )
            self._jobs[job_id] = job

        # Stream output to in-memory buffer in background threads
        threading.Thread(target=self._read_stream, args=(job, proc.stdout, "stdout"), daemon=True).start()
        threading.Thread(target=self._read_stream, args=(job, proc.stderr, "stderr"), daemon=True).start()

        return True, f"Job {job_id} started (PID {proc.pid}).", job

    def _read_stream(self, job: Job, stream, kind: str):
        try:
            for line in stream:
                line = line.rstrip("\n")
                if kind == "stdout":
                    job._append_stdout(line)
                else:
                    job._append_stderr(line)
        except Exception:
            pass

    def list_jobs(self) -> List[Job]:
        with self._lock:
            for job in self._jobs.values():
                job.poll_status()
            return list(self._jobs.values())

    def get(self, job_id: int) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.poll_status()
            return job

    def kill(self, job_id: int) -> tuple[bool, str]:
        """
        Terminate an AIZEN-owned job.

        Sends SIGTERM first; escalates to SIGKILL if needed.
        """
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return False, f"No job with ID {job_id}."

        if job._proc is None:
            return False, f"Job {job_id} has no process reference."

        if not job.is_alive():
            job.poll_status()
            return False, f"Job {job_id} already {job.status.lower()}."

        try:
            job._proc.terminate()   # SIGTERM
            try:
                job._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                job._proc.kill()    # SIGKILL
                job._proc.wait(timeout=3)
            job.poll_status()
            job.status = JOB_STOPPED
            return True, f"Job {job_id} (PID {job.pid}) stopped."
        except Exception as e:
            return False, f"Kill failed: {e}"

    def running_jobs(self) -> List[Job]:
        with self._lock:
            return [j for j in self._jobs.values() if j.is_alive()]

    def cleanup_on_exit(self) -> int:
        """Terminate all running jobs. Returns count terminated."""
        running = self.running_jobs()
        for job in running:
            try:
                job._proc.terminate()
                try:
                    job._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    job._proc.kill()
                job.status = JOB_STOPPED
            except Exception:
                pass
        return len(running)


# Singleton
_job_manager = JobManager()


def get_job_manager() -> JobManager:
    return _job_manager
