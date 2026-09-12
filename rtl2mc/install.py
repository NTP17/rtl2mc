"""Consent-gated portable installation of upstream stable releases only."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

from redstone_pdk.project import technology
from .common import CACHE, ROOT, dump, execute, read
from .toolchain import simulation_available


def fetch(url):
    if not url.startswith("https://"):
        raise ValueError("Downloads require HTTPS")
    request = urllib.request.Request(url, headers={"User-Agent": "RTL2MC/0.1"})
    with urllib.request.urlopen(request, timeout=60) as reply:
        return reply.read()


def stable_release(repo):
    release = json.loads(fetch("https://api.github.com/repos/" + repo + "/releases/latest"))
    if release.get("draft") or release.get("prerelease") or re.search(r"nightly|snapshot|dev|alpha|beta|rc\d", release["tag_name"], re.I):
        raise ValueError("Upstream did not publish a stable release: " + repo)
    tag = release["tag_name"]
    pattern = r"(?:v|yosys-)?(\d+[._]\d+(?:[._]\d+)?)(?:-\d+)?"
    m = re.fullmatch(pattern, tag)
    if not m:
        raise ValueError("Unrecognized stable version tag: " + tag)
    return release, m[1].replace("_", ".")


def msys_package(name, version=None):
    page = fetch("https://packages.msys2.org/packages/" + name).decode()
    url = re.search(r'href="(https://mirror.msys2.org/mingw/ucrt64/[^"<>]+\.pkg\.tar\.zst)"', page)
    digest = re.search(r"SHA256:.*?([0-9a-f]{64})", page, re.S)
    if not url or not digest:
        raise ValueError("Cannot resolve the stable MSYS2 package: " + name)
    if version and not re.fullmatch(re.escape(name + "-") + r"(?:\d+~)?" + re.escape(version) + r"-\d+-[^/]+\.pkg\.tar\.zst", url[1].rsplit("/", 1)[-1]):
        raise ValueError(f"MSYS2 does not currently supply upstream stable {name} {version}; no nightly/older substitute installed")
    return {"name": name, "url": url[1], "sha256": digest[1], "version": version}


def yowasp_package(upstream_version):
    metadata = json.loads(fetch("https://pypi.org/pypi/yowasp-yosys/json"))
    parts = list(map(int, upstream_version.split(".")))
    parts += [0] * (3-len(parts))
    candidates = []
    # YoWASP X.Y.Z.N.postM: N==0 means an upstream release, not a snapshot.
    for version, assets in metadata["releases"].items():
        m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)\.0\.post(\d+)", version)
        if not m or list(map(int, m.groups()[:3])) != parts:
            continue
        for asset in assets:
            if not asset.get("yanked") and asset["filename"].endswith("py3-none-any.whl"):
                candidates.append((int(m[4]), version, asset))
    if not candidates:
        raise ValueError("No portable package of the latest stable Yosys release is published; no older/nightly version substituted")
    _, version, asset = max(candidates, key=lambda item: item[0])
    return {"name": "yowasp-yosys", "version": version, "upstream_version": upstream_version,
            "url": asset["url"], "sha256": asset["digests"]["sha256"]}


def plan(found, target=None):
    """Resolve current upstream GA metadata each time installation is requested."""
    system = platform.system()
    machine = platform.machine().lower()
    if system not in ("Windows", "Linux") or machine not in ("amd64", "x86_64"):
        raise ValueError("Portable bootstrap currently supports Windows/Linux x86-64")
    result = {"policy": "latest upstream stable only; no prerelease/nightly substitution", "system": system,
              "destination": str(CACHE), "packages": [], "eda_versions": {}}
    have = lambda name: found.get(name, {}).get("available", False)
    required = []
    if not have("yosys"):
        required.append(("yosys", "YosysHQ/yosys"))
    if not any(simulation_available(found, n) for n in ("vcs", "xcelium", "questa", "icarus")):
        required.append(("iverilog", "steveicarus/iverilog"))
    for name, repo in required:
        release, version = stable_release(repo)
        result["eda_versions"][name] = version
        result.setdefault("upstream", {})[name] = release["html_url"]
        if name == "yosys":
            # Release-derived WebAssembly wheels avoid native package lag and
            # do not require a nightly tool bundle or a global compiler install.
            result["packages"].append(yowasp_package(version))
        elif system == "Windows":
            result["packages"].append(msys_package("mingw-w64-ucrt-x86_64-" + name, version))
    if any(name != "yosys" for name, _ in required) and system == "Linux":
        release, version = stable_release("mamba-org/micromamba-releases")
        asset = next(a for a in release["assets"] if a["name"] == "micromamba-linux-64")
        digest = asset.get("digest", "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("Stable micromamba has no published SHA256; bootstrap cannot verify it")
        result["packages"].append({"name": "micromamba", "version": version, "url": asset["browser_download_url"], "sha256": digest[7:]})
    if not have("java"):
        os_id = system.lower()
        major = target["java_major"] if target else 21
        assets = json.loads(fetch(f"https://api.adoptium.net/v3/assets/latest/{major}/hotspot?architecture=x64&image_type=jre&os=" + os_id + "&vendor=eclipse"))
        choices = [a for a in assets if a.get("version", {}).get("pre") is None and "-ea" not in a["release_name"]]
        if not choices:
            raise ValueError(f"No stable Java {major} runtime available")
        asset = max(choices, key=lambda a: tuple(a["version"].get(k, 0) for k in ("major", "minor", "security", "patch", "build")))
        p = asset["binary"]["package"]
        result["packages"].append({"name": "java", "version": asset["release_name"], "url": p["link"], "sha256": p["checksum"], "size": p["size"]})
    pin = target["server"] if target else technology()["server"]
    candidates = (ROOT / ".local/server/server.jar", CACHE / "server.jar", CACHE / "minecraft" / pin["sha1"] / "server.jar")
    if not any(p.exists() and hashlib.sha1(p.read_bytes()).hexdigest() == pin["sha1"] for p in candidates):
        result["packages"].append({"name": "minecraft", **pin, "version": target["id"] if target else technology()["minecraft_version"]})
    return result


def download(item):
    destination = CACHE / "downloads" / item["url"].rsplit("/", 1)[-1]
    destination.parent.mkdir(parents=True, exist_ok=True)
    algorithm = "sha256" if "sha256" in item else "sha1"
    def valid(path):
        return path.exists() and hashlib.new(algorithm, path.read_bytes()).hexdigest() == item[algorithm]
    if not valid(destination):
        data = fetch(item["url"])
        if hashlib.new(algorithm, data).hexdigest() != item[algorithm]:
            raise ValueError("Download checksum mismatch: " + item["name"])
        partial = destination.with_suffix(destination.suffix + ".partial")
        partial.write_bytes(data)
        partial.replace(destination)
    return destination


def extract(archive, destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for item in z.infolist():
                if not (destination / item.filename).resolve().is_relative_to(destination) or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Unsafe runtime archive member")
            z.extractall(destination)
    else:
        with tarfile.open(archive) as t:
            t.extractall(destination, filter="data")


def install(proposal, *, confirmed=False):
    if not confirmed:
        raise PermissionError("Portable installation requires explicit user confirmation")
    CACHE.mkdir(parents=True, exist_ok=True)
    # The approval covers these packages and their stable repository dependencies.
    dump(CACHE / "install-plan.json", proposal)
    installed = []
    pending = list(proposal["packages"])
    seen = set()
    while pending:
        item = pending.pop(0)
        if item["name"] in seen:
            continue
        seen.add(item["name"])
        print("Installing stable " + item["name"] + " " + str(item.get("version") or "dependency"), flush=True)
        archive = download(item)
        if item["name"].startswith("mingw-"):
            dest = CACHE / "msys"
            dest.mkdir(exist_ok=True)
            listing = subprocess.check_output(["tar", "-tf", str(archive)], text=True).splitlines()
            details = subprocess.check_output(["tar", "-tvf", str(archive)], text=True).splitlines()
            if len(listing) != len(details):
                raise ValueError("Archive listing mismatch")
            members = [p for p, d in zip(listing, details) if p.startswith("ucrt64/") and d.startswith("-")]
            if any(not (dest / p).resolve().is_relative_to(dest.resolve()) for p in members):
                raise ValueError("Unsafe MSYS2 archive member")
            for start in range(0, len(members), 100):
                subprocess.run(["tar", "-xf", str(archive), "-C", str(dest), *members[start:start+100]], check=True)
            info = subprocess.check_output(["tar", "-xOf", str(archive), ".PKGINFO"], text=True)
            for dep in re.findall(r"^depend = ([^\s<>=]+)", info, re.M):
                if dep == "mingw-w64-ucrt-x86_64-cc-libs":
                    dep = "mingw-w64-ucrt-x86_64-gcc-libs"
                if not dep.startswith("mingw-w64-ucrt-x86_64-"):
                    raise ValueError("Unexpected nonportable MSYS2 dependency: " + dep)
                if dep not in seen:
                    pending.append(msys_package(dep))
        elif item["name"] == "micromamba":
            target = CACHE / "micromamba"
            shutil.copyfile(archive, target)
            target.chmod(0o755)
            specs = [name + "==" + version for name, version in proposal["eda_versions"].items() if name != "yosys"]
            args = [str(target), "create", "--no-rc", "-y", "-r", str(CACHE / "mamba"), "-p", str(CACHE / "conda"),
                    "--override-channels", "-c", "conda-forge", "--strict-channel-priority", *specs]
            _, output = execute([*args, "--dry-run", "--json"], CACHE, "stable-solve", timeout=300)
            solved = json.loads(output)
            if not solved.get("success"):
                raise ValueError("The latest stable tools are unavailable for this platform; no older/nightly substitution installed")
            for p in solved.get("actions", {}).get("LINK", []):
                if re.search(r"dev|alpha|beta|rc|nightly", p["version"], re.I):
                    raise ValueError("Dependency solver selected a prerelease: " + p["name"])
            # Lock the exact solved packages, including SHA256, before extraction.
            packages = solved.get("actions", {}).get("LINK", [])
            if not packages or any(not p.get("sha256") for p in packages):
                raise ValueError("Dependency solver omitted required package checksums")
            explicit = CACHE / "conda-explicit.txt"
            explicit.write_text("@EXPLICIT\n" + "\n".join(p["url"] + "#" + p["sha256"] for p in packages) + "\n")
            execute([str(target), "create", "--no-rc", "-y", "-r", str(CACHE / "mamba"), "-p", str(CACHE / "conda"),
                     "--file", str(explicit)], CACHE, "stable-install", timeout=1800)
        elif item["name"] == "yowasp-yosys":
            python_dest = CACHE / "python"
            args = [sys.executable, "-m", "pip", "--isolated", "--disable-pip-version-check", "install", "--ignore-installed",
                    "--only-binary=:all:", "--index-url", "https://pypi.org/simple", "--target", str(python_dest)]
            execute([*args, "--dry-run", "--report", "python-solve.json", str(archive)], CACHE, "python-stable-solve")
            resolved = read(CACHE / "python-solve.json")["install"]
            requirements = []
            for p in resolved:
                name, version = p["metadata"]["name"], p["metadata"]["version"]
                if not re.fullmatch(r"\d+(?:\.\d+)*(?:\.post\d+)?", version):
                    raise ValueError("Python solver selected a prerelease: " + name)
                digest = p["download_info"]["archive_info"]["hashes"]["sha256"]
                if name.lower().replace("_", "-") == "yowasp-yosys" and digest != item["sha256"]:
                    raise ValueError("Resolved Yosys wheel differs from the approved stable package")
                requirements.append(f"{name}=={version} --hash=sha256:{digest}")
            lock = CACHE / "python-requirements.lock"
            lock.write_text("\n".join(requirements)+"\n")
            execute([*args, "--require-hashes", "--no-deps", "-r", str(lock)], CACHE, "python-stable-install", timeout=1800)
        elif item["name"] == "java":
            extract(archive, CACHE / "java")
        elif item["name"] == "minecraft":
            destination = CACHE / "minecraft" / item["sha1"] / "server.jar"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(archive, destination)
        else:
            raise ValueError("Unknown portable package")
        installed.append(item)
        dump(CACHE / "installed-lock.json", {"policy": proposal["policy"], "packages": installed})
    return installed
