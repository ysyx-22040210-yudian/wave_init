#!/usr/bin/env python3
"""Developer-only SSH helper. Credentials come exclusively from the environment."""
import argparse
import os
import posixpath
import shlex
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", module=r"paramiko\..*")
import paramiko


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="192.168.31.116")
    p.add_argument("--user", default="root")
    p.add_argument("--remote", default="/root/wave_init")
    p.add_argument("--sync", action="store_true")
    p.add_argument("--get", nargs=2, metavar=("REMOTE_FILE", "LOCAL_FILE"))
    p.add_argument("--command")
    args = p.parse_args()
    c = paramiko.SSHClient()
    c.load_system_host_keys()
    c.set_missing_host_key_policy(paramiko.RejectPolicy())
    c.connect(args.host, username=args.user,
              password=os.environ.get("WAVE_INIT_SSH_PASSWORD"),
              look_for_keys=True, allow_agent=False, timeout=10)
    try:
        if args.sync:
            root = Path(__file__).resolve().parent.parent
            sftp = c.open_sftp()
            made = set()
            def mkdir(path):
                if path in made or path == "/":
                    return
                mkdir(posixpath.dirname(path))
                try:
                    sftp.stat(path)
                except IOError:
                    sftp.mkdir(path)
                made.add(path)
            count = 0
            for folder, dirs, files in os.walk(str(root)):
                dirs[:] = [d for d in dirs if d not in (
                    ".git", "__pycache__", "out", "build", "dist", ".vm_results", ".pytest_cache")]
                for name in files:
                    src = Path(folder) / name
                    if src.suffix in (".pyc", ".fsdb", ".pdf"):
                        continue
                    dst = posixpath.join(args.remote, src.relative_to(root).as_posix())
                    mkdir(posixpath.dirname(dst))
                    sftp.put(str(src), dst)
                    count += 1
            sftp.close()
            print("Synced {} files to {}:{}".format(count, args.host, args.remote), flush=True)
        if args.get:
            remote, local = args.get
            Path(local).parent.mkdir(parents=True, exist_ok=True)
            sftp = c.open_sftp()
            sftp.get(remote, local)
            sftp.close()
        if args.command:
            cmd = "builtin cd {} && bash --noprofile --norc -c {}".format(
                shlex.quote(args.remote), shlex.quote(args.command))
            _, out, _ = c.exec_command(cmd, get_pty=False)
            out.channel.set_combine_stderr(True)
            for line in out:
                print(line, end="", flush=True)
            return out.channel.recv_exit_status()
        return 0
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())
