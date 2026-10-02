"""Contracts needed when relocating the app or using the bundled interpreter."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from waveinit import __version__
from waveinit.gui_runner import SSHSettings, Task
from waveinit.portable import cli_command, download_root, external_environment, output_root, resource_root


class PortableContracts(unittest.TestCase):
    def test_frozen_external_process_gets_original_eda_libraries(self):
        bundle = str(Path("/portable/_internal"))
        original = {"LD_LIBRARY_PATH": "/portable/_internal:/eda/lib", "LD_LIBRARY_PATH_ORIG": "/eda/lib",
                    "TCL_LIBRARY": str(Path(bundle)/"_tcl_data"), "TK_LIBRARY": str(Path(bundle)/"_tk_data"),
                    "FONTCONFIG_FILE": "/portable/fonts/fonts.conf", "WAVE_INIT_FONTCONFIG_ORIG": "/site/fonts.conf",
                    "VERDI_HOME": "/eda/verdi", "SNPSLMD_LICENSE_FILE": "test-license", "PATH": "/bin"}
        with mock.patch.dict(os.environ, original, clear=True), mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "_MEIPASS", bundle, create=True):
            cleaned = external_environment()
            self.assertEqual(cleaned["LD_LIBRARY_PATH"], "/eda/lib")
            self.assertNotIn("TCL_LIBRARY", cleaned)
            self.assertNotIn("TK_LIBRARY", cleaned)
            self.assertEqual(cleaned["FONTCONFIG_FILE"], "/site/fonts.conf")
            self.assertEqual(cleaned["SNPSLMD_LICENSE_FILE"], "test-license")
            self.assertEqual(dict(os.environ), original)

    def test_frozen_cli_uses_executable_without_a_python_script(self):
        with mock.patch.object(sys, "frozen", True, create=True):
            argv = cli_command(["--scope", "tb.dut"])
        self.assertEqual(argv, [sys.executable, "--cli", "--scope", "tb.dut"])

    def test_user_data_locations_are_independent_of_install_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {"WAVE_INIT_OUTPUT_DIR": directory+"/my results", "XDG_CACHE_HOME": directory+"/cache", "LOCALAPPDATA": directory+"/cache"}
            with mock.patch.dict(os.environ, env):
                self.assertEqual(output_root(), Path(directory)/"my results")
                self.assertEqual(download_root(), Path(directory)/"cache/wave_init/downloads")
        settings = SSHSettings()
        self.assertEqual(settings.host, "")
        self.assertEqual(settings.directory, "")
        self.assertEqual(settings.environment, "")

    def test_relative_input_paths_remain_bound_to_launch_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base/"waves.fsdb").touch()
            (base/"kdb").mkdir()
            (base/"kdb/db").touch()
            original = Path.cwd()
            try:
                os.chdir(str(base))
                task = Task(fsdb="waves.fsdb", kdb="kdb", scope="tb.dut", out="new output")
                task.validate()
            finally:
                os.chdir(str(original))
            self.assertEqual(task.fsdb, str((base/"waves.fsdb").resolve()))
            self.assertEqual(task.out, str((base/"new output").resolve()))

    @unittest.skipUnless(os.name == "posix", "requires Bash")
    def test_source_launcher_resolves_symlink_from_another_directory(self):
        with tempfile.TemporaryDirectory(prefix="launch with spaces ") as directory:
            link = Path(directory)/"GUI link.sh"
            link.symlink_to(resource_root()/"start_gui.sh")
            env = os.environ.copy()
            env["WAVE_INIT_PYTHON"] = sys.executable
            result = subprocess.check_output(["bash", str(link), "--version"], cwd=directory, env=env, universal_newlines=True)
            self.assertEqual(result.strip(), __version__)


if __name__ == "__main__":
    unittest.main()
