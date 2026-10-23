"""Auto-updater, run by start.bat before ClipForge opens.

Downloads the newest version from GitHub and copies it over this folder,
never touching your settings, API key, sounds, clips or history. If the
internet is down or GitHub is unreachable, ClipForge just starts as it is.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

REPO = "bcf4038-hue/clipforge"
BRANCH = "main"
ROOT = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(ROOT, ".version")

# Never overwritten: your data, and the .bat files (Windows reads a running .bat
# line by line, so replacing it mid-run breaks it).
KEEP = {"config.json", "cookies.txt", "usage.json", ".version", "install.bat", "start.bat"}
KEEP_DIRS = ("work", "output", ".venv", os.path.join("sounds", "my_sfx"), os.path.join("sounds", "my_music"))


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "ClipForge-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest_commit():
    data = json.loads(fetch(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"))
    return data["sha"], data["commit"]["message"].splitlines()[0]


def protected(rel):
    rel = os.path.normpath(rel)
    return rel in KEEP or any(rel == d or rel.startswith(d + os.sep) for d in KEEP_DIRS)


def install(sha):
    archive = zipfile.ZipFile(io.BytesIO(fetch(f"https://codeload.github.com/{REPO}/zip/{sha}", timeout=120)))
    old_reqs = open(os.path.join(ROOT, "requirements.txt"), "rb").read() if os.path.exists(
        os.path.join(ROOT, "requirements.txt")) else b""
    for info in archive.infolist():
        # Entries look like "clipforge-<sha>/path/to/file".
        rel = info.filename.split("/", 1)[1] if "/" in info.filename else ""
        if not rel or info.is_dir() or protected(rel):
            continue
        dest = os.path.join(ROOT, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with archive.open(info) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
    with open(VERSION_FILE, "w") as f:
        f.write(sha)
    new_reqs = open(os.path.join(ROOT, "requirements.txt"), "rb").read()
    return new_reqs != old_reqs


def main():
    print("  Checking for ClipForge updates...")
    try:
        sha, message = latest_commit()
        current = open(VERSION_FILE).read().strip() if os.path.exists(VERSION_FILE) else ""
        if sha != current:
            print(f"  Updating ClipForge: {message}")
            if install(sha):
                print("  Installing new packages (one time, may take a minute)...")
                subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                                os.path.join(ROOT, "requirements.txt")])
            print("  Updated.")
        else:
            print("  ClipForge is up to date.")
    except Exception as e:  # offline, GitHub down, rate limited: start anyway
        print(f"  Couldn't check for updates ({e.__class__.__name__}). Starting the current version.")
    # These break when YouTube/Microsoft change things, so keep them fresh every start.
    print("  Checking the YouTube downloader and voice tool...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "yt-dlp[default,curl-cffi]", "edge-tts"])


if __name__ == "__main__":
    main()
