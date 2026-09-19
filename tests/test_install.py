"""Headless installer contracts, exercised without network or device side effects."""

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install_unoq.sh"


@pytest.fixture
def installation(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "commands.log"
    scripts = {
        "uname": 'printf "Linux\\n"',
        "id": 'if [[ "$1" == -u ]]; then echo 1000; else echo arduino; fi',
        "hostname": 'echo test-uno',
        "loginctl": 'echo yes',
        "systemctl": 'if [[ "$*" == *"cat braccio-calibrate.service"* ]]; then exit 1; fi; exit 0',
        "arduino-app-cli": 'exit 0',
        "python3": '''if [[ "$*" == *"-m venv"* ]]; then
destination="${@: -1}"
mkdir -p "$destination/bin"
cp "$FAKE_PYTHON" "$destination/bin/python"
chmod +x "$destination/bin/python"
fi''',
        "git": '''if [[ "$1" == clone ]]; then
destination="${@: -1}"
mkdir -p "$destination/.git" "$destination/app_lab"
cp -R "$TEST_SOURCE/app_lab/braccio_remote_agent" "$destination/app_lab/"
cp "$TEST_SOURCE/requirements.txt" "$destination/"
elif [[ "$*" == *"remote get-url origin"* ]]; then
echo "${FAKE_ORIGIN:-https://github.com/eoinjordan/unoq-braccio-sketchbot.git}"
elif [[ "$*" == *"status --porcelain"* ]]; then
printf '%s' "${FAKE_DIRTY:-}"
elif [[ "$*" == *"symbolic-ref --short HEAD"* ]]; then
echo "${FAKE_BRANCH:-main}"
fi''',
        "venv-python": 'exit 0',
    }
    for name, code in scripts.items():
        path = binaries / name
        path.write_text('#!/usr/bin/env bash\nprintf "%s %s\\n" "$(basename "$0")" "$*" >> "$INSTALL_LOG"\n' + code + '\n')
        path.chmod(0o755)
    environment = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
                   "PATH": f"{binaries}:{os.environ['PATH']}", "INSTALL_LOG": str(log),
                   "TEST_SOURCE": str(ROOT), "FAKE_PYTHON": str(binaries / "venv-python")}
    return home, environment, log


def execute(environment, *arguments):
    return subprocess.run(["bash", str(INSTALLER), *arguments], env=environment, text=True,
                          capture_output=True, timeout=20)


def test_installer_dry_run_has_no_side_effects(installation):
    home, environment, log = installation
    result = execute(environment, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "no network access" in result.stdout
    assert not log.exists()
    assert not list(home.iterdir())


def test_default_installer_creates_persistent_no_motion_service(installation):
    home, environment, log = installation
    result = execute(environment)
    assert result.returncode == 0, result.stderr
    override = home / ".config/systemd/user/sketchbot-studio.service.d/10-installer.conf"
    assert override.exists()
    assert "--allow-motion" not in override.read_text()
    assert '.venv/bin/python" -m web.server --port 7100' in override.read_text()
    commands = log.read_text()
    assert "enable sketchbot-studio.service" in commands
    assert "arduino-app-cli" not in commands
    assert "http://test-uno.local:7100" in result.stdout


def test_installer_preserves_dirty_checkout_and_settings(installation):
    home, environment, log = installation
    target = home / "unoq-braccio-sketchbot"
    (target / ".git").mkdir(parents=True)
    (target / "config").mkdir()
    settings = target / "config/runtime.yaml"
    settings.write_text("custom: retained\n")
    environment["FAKE_DIRTY"] = " M sketch_artist/cli.py"
    result = execute(environment)
    assert result.returncode != 0
    assert "local changes" in result.stderr
    assert settings.read_text() == "custom: retained\n"
    assert "pull --ff-only" not in log.read_text()
    assert "systemctl --user stop" not in log.read_text()


def test_agent_install_requires_power_confirmation(installation):
    home, environment, log = installation
    result = execute(environment, "--install-agent")
    assert result.returncode != 0
    assert "Disconnect servo power" in result.stderr
    assert not log.exists()


def test_confirmed_agent_install_and_motion_are_explicit(installation):
    home, environment, log = installation
    result = execute(environment, "--install-agent", "--servo-power-off", "--allow-motion")
    assert result.returncode == 0, result.stderr
    assert "arduino-app-cli app start" in log.read_text()
    assert "--allow-motion" in (home / ".config/systemd/user/sketchbot-studio.service.d/10-installer.conf").read_text()


def test_existing_agent_is_never_overwritten(installation):
    home, environment, log = installation
    (home / "ArduinoApps/braccio_remote_agent").mkdir(parents=True)
    result = execute(environment, "--install-agent", "--servo-power-off")
    assert result.returncode != 0
    assert "already exists" in result.stderr
    assert "git clone" not in log.read_text()


def test_no_start_installs_without_service_changes(installation):
    home, environment, log = installation
    result = execute(environment, "--no-start")
    assert result.returncode == 0, result.stderr
    assert "systemctl" not in log.read_text()
    assert not (home / ".config").exists()


def test_tablet_camera_is_an_explicit_no_motion_setup_step(installation):
    home, environment, log = installation
    result = execute(environment, "--tablet-camera")
    assert result.returncode == 0, result.stderr
    assert 'app.save_camera("face", {"format":"tablet"' in log.read_text()
    assert "arduino-app-cli" not in log.read_text()
    assert "--allow-motion" not in (home / ".config/systemd/user/sketchbot-studio.service.d/10-installer.conf").read_text()


def test_custom_service_overrides_are_preserved(installation):
    home, environment, log = installation
    custom = home / ".config/systemd/user/sketchbot-studio.service.d/override.conf"
    custom.parent.mkdir(parents=True)
    custom.write_text("[Service]\nExecStart=custom-command\n")
    result = execute(environment)
    assert result.returncode != 0
    assert "Custom Studio service overrides" in result.stderr
    assert "custom-command" in custom.read_text()
    assert "git clone" not in log.read_text()


def test_non_main_checkout_is_not_modified(installation):
    home, environment, log = installation
    (home / "unoq-braccio-sketchbot/.git").mkdir(parents=True)
    environment["FAKE_BRANCH"] = "my-custom-firmware"
    result = execute(environment)
    assert result.returncode != 0
    assert "not on main" in result.stderr
    assert "pull --ff-only" not in log.read_text()