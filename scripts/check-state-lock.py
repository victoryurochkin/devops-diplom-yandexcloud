#!/usr/bin/env python3
"""Verify S3 state exclusion with a real console lock and a competing plan."""
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import subprocess
import time


def main():
    project = Path(__file__).resolve().parent.parent
    os.chdir(project)
    data_dir = Path(os.environ.get("TF_DATA_DIR", ".terraform"))
    if not data_dir.is_absolute():
        data_dir = project / "terraform/infrastructure" / data_dir
    backend = json.loads((data_dir / "terraform.tfstate").read_text())["backend"]
    if backend["type"] != "s3" or backend["config"].get("use_lockfile") is not True:
        raise SystemExit("Expected initialized S3 backend with use_lockfile=true")

    command = ["terraform", "-chdir=terraform/infrastructure"]
    plan = command + ["plan", "-input=false", "-no-color", "-refresh=false",
                      "-detailed-exitcode", "-lock-timeout=3s"]
    master, slave = pty.openpty()
    process = subprocess.Popen(command + ["console", "-no-color"],
                               stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    transcript = b""
    try:
        deadline = time.monotonic() + 60
        while b"> " not in transcript:
            if process.poll() is not None:
                raise RuntimeError("Console exited before its prompt: " + transcript.decode(errors="replace"))
            if time.monotonic() >= deadline:
                raise RuntimeError("Timed out waiting for the console prompt")
            if select.select([master], [], [], 1)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError as error:
                    raise RuntimeError("Console failed: " + transcript.decode(errors="replace")) from error
                if not chunk:
                    raise RuntimeError("Console closed before its prompt")
                transcript += chunk
        print("Terraform console is ready and holds the state lock", flush=True)
        result = subprocess.run(plan, text=True, capture_output=True, timeout=60)
        output = result.stdout + result.stderr
        if (result.returncode != 1 or process.poll() is not None
                or not re.search(r"Error acquiring (?:the )?state lock", output)
                or not re.search(r"412|PreconditionFailed", output)):
            raise RuntimeError("Expected a competing S3 lock rejection:\n" + output)
        print("Competing plan rejected: S3 conditional write failed (412)", flush=True)
    finally:
        if process.poll() is None:
            os.write(master, b"exit\n")
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.send_signal(signal.SIGINT)
                process.wait(timeout=30)
        os.close(master)
    if process.returncode != 0:
        raise SystemExit("Console did not exit cleanly; inspect the state lock before continuing")
    print("Console exited normally; checking that the lock was released", flush=True)
    result = subprocess.run(plan, text=True, capture_output=True, timeout=120)
    if result.returncode != 0:
        raise SystemExit("Expected No changes after release:\n" + result.stdout + result.stderr)
    print("Plan after lock release: No changes", flush=True)
    print("S3 lock acquisition, exclusion and release: OK", flush=True)


if __name__ == "__main__":
    main()
