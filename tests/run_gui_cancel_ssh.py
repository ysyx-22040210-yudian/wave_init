#!/usr/bin/env python3
"""Cancel a deliberately slow remote vendor process using the real GUI button."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from waveinit.gui import WaveInitApp, read_profile
from waveinit.gui_runner import connect_ssh, remote_command


def main():
    root = tk.Tk()
    root.withdraw()
    app = WaveInitApp(root)
    for key, value in read_profile(ROOT/"examples/gui_vm.json").items():
        app.vars[key].set(value)
    app.vars["password"].set(os.environ.get("WAVE_INIT_SSH_PASSWORD", ""))
    app.vars["mode"].set("ssh")
    settings = app.ssh_settings()
    client = connect_ssh(settings)
    remote = settings.directory + "/build/gui_cancel_" + uuid.uuid4().hex
    evidence_dir = Path(tempfile.mkdtemp(prefix="gui_cancel_", dir=str(ROOT/"build")))
    try:
        sftp = client.open_sftp()
        sftp.get_channel().settimeout(10)
        sftp.mkdir(remote)
        fake = remote + "/slow_vendor.py"
        script = '''#!/usr/bin/env python3.8
import json,os,subprocess,sys,time
from pathlib import Path
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
Path(__file__).with_name('vendor.json').write_text(json.dumps([os.getpid(),child.pid]))
time.sleep(60)
'''
        with sftp.open(fake, "w") as handle:
            handle.write(script)
        sftp.chmod(fake, 0o700)
        for key, value in {"fsdb": settings.directory+"/build/fixture/waves.fsdb",
                           "kdb": settings.directory+"/build/fixture/simv.daidir", "scope": "snapshot_top.dut",
                           "out": remote+"/result", "verdi": fake, "timeout": "20"}.items():
            app.vars[key].set(value)
        app.mode_changed()
        app.run_button.invoke()
        deadline = time.monotonic()+10
        pids = None
        while app.busy and time.monotonic()<deadline:
            root.update()
            try:
                with sftp.open(remote+"/vendor.json") as handle:
                    pids = json.loads(handle.read().decode())
                break
            except IOError:
                time.sleep(.05)
        assert pids, app.log.get("1.0", "end")
        started = time.monotonic()
        app.cancel_button.invoke()
        while app.busy and time.monotonic()-started<15:
            root.update()
            time.sleep(.02)
        root.update()
        assert not app.busy
        assert app.run_result and app.run_result["code"] == 130, app.run_result
        assert "已取消" in app.status.get()
        code = "from pathlib import Path; pids="+repr(pids)+"; print(all(not (Path('/proc')/str(p)/'stat').exists() or (Path('/proc')/str(p)/'stat').read_text().split(') ',1)[1].startswith('Z') for p in pids))"
        _, stdout, _ = client.exec_command(remote_command(settings, [settings.python, "-c", code]))
        assert stdout.read().decode().strip() == "True", "remote vendor process survived cancellation"
        assert stdout.channel.recv_exit_status() == 0
        evidence = {"status": "pass", "mode": "ssh_cancel", "code": 130,
                    "seconds_after_cancel": round(time.monotonic()-started, 2),
                    "vendor_processes_stopped": len(pids), "remote_fixture": remote,
                    "local_report": str(app.result_directory)}
        (evidence_dir/"results.json").write_text(json.dumps(evidence, indent=2)+"\n", encoding="utf-8")
        (evidence_dir/"gui.log").write_text(app.log.get("1.0", "end"), encoding="utf-8")
        print(json.dumps(evidence, indent=2))
        print("RESULTS " + str(evidence_dir))
    finally:
        client.close()
        app.destroy()


if __name__ == "__main__":
    main()
