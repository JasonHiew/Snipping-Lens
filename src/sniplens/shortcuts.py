import logging
import os

from sniplens import APP_NAME, paths

LNK_NAME = f"{APP_NAME}.lnk"

if paths.IS_WINDOWS:
    import winshell

    ROOT_LNK = os.path.join(paths.ROOT, LNK_NAME)
    LNK_ICON = os.path.join(paths.ASSETS_DIR, "sniplens.ico")
    # pythonw runs without a console, so the shortcut needs no script wrapper
    # to hide one for it
    PYTHONW = os.path.join(paths.VENV_DIR, "Scripts", "pythonw.exe")
    LNK_ARGUMENTS = f'"{paths.MAIN_SCRIPT}"'
elif paths.IS_MAC:
    import plistlib
    import re
    import shutil
    import subprocess
    import sys

    # Every launch goes through this bundle so macOS attributes the Screen
    # Recording and Input Monitoring permissions to "Snipping Lens" rather than to
    # Terminal or a bare python binary. It is built locally, so it carries no
    # quarantine flag and Gatekeeper never asks for a signature.
    APP_BUNDLE = os.path.expanduser(f"~/Applications/{APP_NAME}.app")
    BUNDLE_ID = "com.snippinglens.app"
    BUNDLE_EXECUTABLE = "snipping-lens"
    # The bundle's executable is a copy of the Python interpreter itself.
    # macOS tracks a launched app by its pid and an exec count, so a launcher
    # script that execs Python leaves a process the menu bar and the privacy
    # prompts cannot match to Snipping Lens: the icon is never placed and no
    # permission is ever asked for. The interpreter is statically linked, so
    # the copy needs only to be told where the stdlib and the venv are.
    PYTHON_LIB = f"python{sys.version_info.major}.{sys.version_info.minor}"
    VENV_SITE_PACKAGES = os.path.join(paths.VENV_DIR, "lib", PYTHON_LIB, "site-packages")
    SETUP_SCRIPT = os.path.join(paths.ROOT, "setup_mac.sh")
    LAUNCH_AGENT_FILE = os.path.expanduser(f"~/Library/LaunchAgents/{BUNDLE_ID}.plist")
    # a self-signed code signing certificate the user can create in Keychain
    # Access, so permissions survive the bundle being re-signed
    SIGNING_CERTIFICATE = "Snipping Lens Signing"
    # what the app asks macOS for; Accessibility was asked for by older builds
    TCC_SERVICES = ("ScreenCapture", "ListenEvent", "Accessibility")

    INFO_PLIST = plistlib.dumps(
        {
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleExecutable": BUNDLE_EXECUTABLE,
            "CFBundleIconFile": "sniplens",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "5",
            # menu bar only: no Dock icon and no app menu for the bundle
            "LSUIElement": True,
        }
    )
    # macOS starts the bundle with no arguments, which would leave Python
    # reading a program from stdin. This hook runs the setup script so a
    # dependency change is installed before the app starts, as on Linux, then
    # hands Python main.py as that stdin program. The config window, started
    # with a script, skips it. It is an import line of a .pth file, which
    # site runs as is, rather than a module: Python would cache a module's
    # bytecode inside the bundle, breaking its signature, and with it the
    # permissions macOS granted.
    BUNDLE_BOOT = f'''
import subprocess
subprocess.run(["/bin/bash", {SETUP_SCRIPT!r}, "--hidden"], stdin=subprocess.DEVNULL)
os.chdir({paths.ROOT!r})
sys.path.insert(0, {paths.SRC_DIR!r})
main = os.open({paths.MAIN_SCRIPT!r}, os.O_RDONLY)
os.dup2(main, 0)
os.close(main)
'''
    BUNDLE_PTH = (
        f"{VENV_SITE_PACKAGES}\n"
        f"import os, sys; exec({BUNDLE_BOOT!r}) if len(sys.orig_argv) == 1 else None\n"
    )
    LAUNCH_AGENT_CONTENT = plistlib.dumps(
        {
            "Label": BUNDLE_ID,
            "ProgramArguments": ["/usr/bin/open", APP_BUNDLE],
            "RunAtLoad": True,
        }
    )
else:
    AUTOSTART_FILE = os.path.expanduser(
        "~/.config/autostart/snipping-lens-startup.desktop"
    )
    APP_MENU_FILE = os.path.expanduser(
        "~/.local/share/applications/snipping-lens.desktop"
    )
    SETUP_SCRIPT = os.path.join(paths.ROOT, "setup_linux.sh")
    # quoted per the Desktop Entry spec so an install path containing spaces
    # still launches, and run through bash so the script needs no exec bit
    LAUNCH_COMMAND = f'bash "{SETUP_SCRIPT}" --hidden'

    AUTOSTART_CONTENT = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Exec={LAUNCH_COMMAND}\n"
        "Terminal=false\n"
        "Hidden=false\n"
        "NoDisplay=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        f"Name={APP_NAME}\n"
    )
    APP_MENU_CONTENT = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Exec={LAUNCH_COMMAND}\n"
        "Terminal=false\n"
        f"Icon={paths.TRAY_ICON_PATH}\n"
        f"Name={APP_NAME}\n"
        "Comment=Screenshot to Google Lens\n"
        "Categories=Utility;\n"
    )


def ensure_integration_entries(startup_enabled, app_menu_enabled=False):
    """Recreates this install's shortcuts so they keep pointing at the current
    folder after the user moves the project. Called on every app start."""
    if paths.IS_WINDOWS:
        _ensure_lnk(ROOT_LNK)
        if startup_enabled:
            _ensure_lnk(os.path.join(winshell.startup(), LNK_NAME))
    elif paths.IS_MAC:
        ensure_app_bundle()
        if startup_enabled:
            _write_file(LAUNCH_AGENT_FILE, LAUNCH_AGENT_CONTENT)
    else:
        if startup_enabled:
            _write_desktop_file(AUTOSTART_FILE, AUTOSTART_CONTENT)
        if app_menu_enabled:
            _write_desktop_file(APP_MENU_FILE, APP_MENU_CONTENT)


def set_startup(enabled):
    if paths.IS_WINDOWS:
        startup_lnk = os.path.join(winshell.startup(), LNK_NAME)
        if enabled:
            _ensure_lnk(ROOT_LNK)
            _ensure_lnk(startup_lnk)
            logging.info("%s added to startup.", APP_NAME)
        else:
            _remove(startup_lnk)
            logging.info("%s removed from startup.", APP_NAME)
    elif paths.IS_MAC:
        if enabled:
            ensure_app_bundle()
            _write_file(LAUNCH_AGENT_FILE, LAUNCH_AGENT_CONTENT)
            logging.info("%s added to login items.", APP_NAME)
        else:
            _remove(LAUNCH_AGENT_FILE)
            logging.info("%s removed from login items.", APP_NAME)
    else:
        if enabled:
            _write_desktop_file(AUTOSTART_FILE, AUTOSTART_CONTENT)
            logging.info("%s added to autostart.", APP_NAME)
        else:
            _remove(AUTOSTART_FILE)
            logging.info("%s removed from autostart.", APP_NAME)


def set_app_menu(enabled):
    if not paths.IS_LINUX:
        return
    if enabled:
        _write_desktop_file(APP_MENU_FILE, APP_MENU_CONTENT)
        logging.info("%s added to the app menu.", APP_NAME)
    else:
        _remove(APP_MENU_FILE)
        logging.info("%s removed from the app menu.", APP_NAME)


if paths.IS_WINDOWS:

    def _ensure_lnk(lnk_path):
        if os.path.exists(lnk_path):
            link = winshell.shortcut(lnk_path)
            if (
                link.path
                and os.path.abspath(link.path) == os.path.abspath(PYTHONW)
                and link.arguments == LNK_ARGUMENTS
                and link.icon_location == (LNK_ICON, 0)
            ):
                return
        with winshell.shortcut(lnk_path) as link:
            link.path = PYTHONW
            link.arguments = LNK_ARGUMENTS
            link.icon_location = (LNK_ICON, 0)
            link.description = APP_NAME
            link.working_directory = paths.ROOT

elif paths.IS_MAC:

    def ensure_app_bundle():
        """(Re)creates the launcher bundle so it keeps pointing at this install
        after the folder is moved. setup_mac.sh calls this on first install."""
        contents = os.path.join(APP_BUNDLE, "Contents")
        _write_file(os.path.join(contents, "Info.plist"), INFO_PLIST)
        icon = os.path.join(contents, "Resources", "sniplens.icns")
        if not os.path.exists(icon):
            os.makedirs(os.path.dirname(icon), exist_ok=True)
            # sips ships with macOS; a missing icon only costs the bundle its artwork
            result = subprocess.run(
                ["/usr/bin/sips", "-s", "format", "icns", paths.TRAY_ICON_PATH, "--out", icon],
                capture_output=True,
            )
            if result.returncode != 0:
                logging.warning("Could not build the app icon: %s", result.stderr.decode(errors="replace"))
        _ensure_bundle_python(contents)
        _ensure_signed()

    def _ensure_signed():
        """macOS neither asks for privacy permissions nor shows the menu bar icon
        of an unsigned app, and it ties the permissions it grants to the
        signature. An ad-hoc one needs no developer account but is the exact
        build, so every re-sign makes macOS forget them; one made with a
        certificate keeps them, since macOS then checks the certificate and
        the bundle ID instead. So the bundle is signed with a certificate when
        the keychain has one, and only re-signed when a file above broke the
        signature or a certificate has become available."""
        identity, name = _signing_identity()
        verify = subprocess.run(
            ["/usr/bin/codesign", "--verify", "--deep", "--strict", APP_BUNDLE],
            capture_output=True,
        )
        if verify.returncode == 0 and (identity == "-" or _signed_by(name)):
            return
        previous = _designated_requirement()
        result = subprocess.run(
            ["/usr/bin/codesign", "--force", "--deep", "--sign", identity, APP_BUNDLE],
            capture_output=True,
        )
        if result.returncode == 0:
            logging.info("Signed the app bundle with %s.", name)
        else:
            logging.warning("Could not sign the app bundle with %s: %s", name, result.stderr.decode(errors="replace"))
            if identity != "-" and verify.returncode != 0:
                subprocess.run(
                    ["/usr/bin/codesign", "--force", "--deep", "--sign", "-", APP_BUNDLE],
                    capture_output=True,
                )
        if previous is not None and _designated_requirement() != previous:
            _forget_permissions()

    def _designated_requirement():
        result = subprocess.run(["/usr/bin/codesign", "-d", "-r-", APP_BUNDLE], capture_output=True)
        for line in result.stdout.decode(errors="replace").splitlines():
            if line.startswith("designated =>"):
                return line
        return None

    def _forget_permissions():
        """The permissions macOS granted belong to the old signature, and it
        keeps listing them, switched on, though they no longer apply: the app
        looks allowed and is not, until each is removed and added again. They
        are void anyway, so clearing them leaves macOS to ask afresh."""
        for service in TCC_SERVICES:
            subprocess.run(["/usr/bin/tccutil", "reset", service, BUNDLE_ID], capture_output=True)
        logging.info("The app's signature changed; its old permissions were cleared.")

    def _signing_identity():
        """(codesign identity, name) for the certificate to sign with: one named
        SIGNING_CERTIFICATE, self-signed so never "valid" to macOS, else a valid
        Apple Development one, else an ad-hoc signature."""
        result = subprocess.run(
            ["/usr/bin/security", "find-identity", "-p", "codesigning"],
            capture_output=True,
        )
        identities = []
        for line in result.stdout.decode(errors="replace").splitlines():
            match = re.match(r'\s*\d+\) ([0-9A-F]{40}) "([^"]+)"\s*(\(.*\))?', line)
            if match:
                identities.append(match.groups())
        for sha1, name, status in identities:
            if name == SIGNING_CERTIFICATE and "EXPIRED" not in (status or ""):
                return sha1, name
        for sha1, name, status in identities:
            if name.startswith("Apple Development:") and not status:
                return sha1, name
        return "-", "an ad-hoc signature"

    def _signed_by(name):
        result = subprocess.run(["/usr/bin/codesign", "-dvv", APP_BUNDLE], capture_output=True)
        return f"Authority={name}" in result.stderr.decode(errors="replace").splitlines()

    def _ensure_bundle_python(contents):
        base_python = os.path.realpath(os.path.join(paths.VENV_DIR, "bin", "python"))
        if not os.path.isfile(base_python):
            logging.warning("No Python at %s to copy into the app bundle.", base_python)
            return
        bundle_python = os.path.join(contents, "MacOS", BUNDLE_EXECUTABLE)
        # signing rewrites the copy, so it never matches the original again;
        # the stamp records which interpreter it was made from instead
        stamp_path = os.path.join(contents, "Resources", "python-source")
        source = os.stat(base_python)
        stamp = f"{base_python}\n{source.st_size} {source.st_mtime_ns}\n".encode()
        try:
            with open(stamp_path, "rb") as f:
                current = f.read() == stamp
        except OSError:
            current = False
        if not current or not os.path.exists(bundle_python):
            try:
                # copied aside and renamed, since the running app may be this
                # very file and rewriting it in place would crash it
                staged = bundle_python + ".new"
                os.makedirs(os.path.dirname(bundle_python), exist_ok=True)
                shutil.copy2(base_python, staged)
                os.replace(staged, bundle_python)
            except OSError as e:
                logging.error("Failed to copy Python into the app bundle: %s", e)
                return
            _write_file(stamp_path, stamp)
        # a pyvenv.cfg beside Contents/MacOS points the copy at the stdlib, and
        # the .pth adds the venv's packages, so the config window, started
        # with sys.executable, finds them too; the .pth also boots the app
        _write_file(
            os.path.join(contents, "pyvenv.cfg"),
            f"home = {os.path.dirname(base_python)}\ninclude-system-site-packages = false\n".encode(),
        )
        site_packages = os.path.join(contents, "lib", PYTHON_LIB, "site-packages")
        _write_file(os.path.join(site_packages, "sniplens.pth"), BUNDLE_PTH.encode())

    def _write_file(path, content):
        try:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    if f.read() == content:
                        return
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(content)
        except OSError as e:
            logging.error("Failed to write %s: %s", path, e)

else:

    def _write_desktop_file(path, content):
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    if f.read() == content:
                        return
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
        except OSError as e:
            logging.error("Failed to write %s: %s", path, e)


def _remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as e:
        logging.error("Failed to remove %s: %s", path, e)
