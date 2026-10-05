"""One build path for local Windows builds and GitHub Actions."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def command(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-install", action="store_true",
                        help="Install/uninstall on a disposable Windows CI runner only")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Build this installer on Windows (or use GitHub Actions).")
    version = (ROOT / "VERSION.txt").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit("VERSION.txt must contain a numeric x.y.z version")
    compiler = shutil.which("ISCC.exe") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if not Path(compiler).is_file():
        raise SystemExit("Install Inno Setup 6 before building the installer.")
    command(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v")
    command(sys.executable, "tests/smoke_test.py")
    command(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
            "--windowed", "--name", "956A_Generator",
            "--collect-data", "reportlab",
            "--add-data", "templates/australia/FORM_956A.pdf:templates/australia",
            "--add-data", "templates/canada/IMM5257.pdf:templates/canada",
            "--add-data", "templates/canada/IMM5707.pdf:templates/canada",
            "--add-data", "templates/canada/IMM5476.pdf:templates/canada",
            "--add-data", "canada/coverage_matrix.yaml:canada",
            "--add-data", "VERSION.txt:.", "app.py")
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    application = ROOT / "dist" / "956A_Generator"

    def verify(executable, name):
        report_path = release / name
        report_path.unlink(missing_ok=True)
        command(executable, "--self-test", report_path, timeout=90)
        report = json.loads(report_path.read_text())
        if not report["ok"] or report["version"] != version:
            raise RuntimeError(f"Packaged application failed: {report}")

    verify(application / "956A_Generator.exe", "portable-self-test.json")
    shutil.copy2(ROOT / "instructions.txt", application / "instructions.txt")
    command(compiler, f"/DMyAppVersion={version}", "installer/956A_Generator.iss")
    installer = release / "956A_Generator_Setup.exe"
    if args.verify_install:
        with tempfile.TemporaryDirectory(prefix="956a-install-test-") as tmp:
            destination = Path(tmp) / "application"
            command(installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                    "/SP-", f"/DIR={destination}", timeout=90)
            try:
                verify(destination / "956A_Generator.exe", "installed-self-test.json")
            finally:
                command(destination / "unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES",
                        "/NORESTART", timeout=90)
    portable = Path(shutil.make_archive(str(release / "956A_Generator_Windows_Portable"),
                                       "zip", application))
    for artifact in (installer, portable):
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        artifact.with_suffix(artifact.suffix + ".sha256").write_text(
            f"{digest}  {artifact.name}\n", encoding="ascii")
    shutil.copy2(ROOT / "instructions.txt", release / "instructions.txt")
    print(f"Verified Windows release {version}: {installer}")


if __name__ == "__main__":
    main()
