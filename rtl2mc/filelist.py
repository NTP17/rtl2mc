"""Explicit source arguments, portable file lists and reproducible HDL snapshots."""
import os
from pathlib import Path
import re
import shlex
import shutil

from .common import dump, sha


def tokens(text):
    text = re.sub(r"\\\r?\n", " ", text)
    text = re.sub(r"(?m)(^|\s)//[^\r\n]*", r"\1", text)
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""  # Windows paths retain backslashes.
    lexer.commenters = "#"
    return list(lexer)


def expand(text, env):
    def replace(m):
        name = next(g for g in m.groups() if g is not None)
        if name not in env:
            raise ValueError("Undefined file-list environment variable: " + name)
        return env[name]
    return re.sub(r"\$\{(\w+)\}|\$(\w+)|%(\w+)%", replace, text)


def _add_source(result, path):
    path = Path(path).resolve()
    if not path.is_file() or path.suffix.lower() not in (".v", ".sv"):
        raise ValueError("Expected an existing .v/.sv source: " + str(path))
    if str(path) in result["sources"]:
        raise ValueError("Duplicate RTL source: " + str(path))
    result["sources"].append(str(path))


def _add_defines(result, values):
    for value in values:
        if not re.fullmatch(r"[A-Za-z_]\w*(?:=[^\r\n]*)?", value):
            raise ValueError("Invalid macro definition: " + value)
        result["defines"].append(value)


def parse_sources(arguments, filelist=None):
    """Expand a file list first, then append literal source paths and +define+ options."""
    result = parse(filelist, require_sources=False) if filelist else {
        "sources": [], "include_dirs": [], "defines": [], "filelists": []}
    for argument in arguments:
        token = str(argument)
        if token.startswith("+define+"):
            _add_defines(result, token[8:].split("+"))
        elif token.startswith("+"):
            raise ValueError("Unsupported source argument: " + token + "; use +define+NAME or a .v/.sv path")
        else:
            _add_source(result, token)
    if not result["sources"]:
        raise ValueError("No RTL sources; provide .v/.sv files or a -f file list containing sources")
    return result


def parse(path, env=None, *, require_sources=True):
    env = os.environ if env is None else env
    result = {"sources": [], "include_dirs": [], "defines": [], "filelists": []}
    stack = []

    def visit(path, base):
        path = Path(path).resolve()
        if path in stack or len(stack) >= 32:
            raise ValueError("Recursive or excessively nested file list: " + str(path))
        stack.append(path)
        result["filelists"].append({"path": str(path), "sha256": sha(path)})
        ts = tokens(path.read_text(encoding="utf-8-sig"))
        i = 0
        while i < len(ts):
            token = expand(ts[i], env)
            i += 1
            if token in ("-f", "-F", "-I", "-D"):
                if i == len(ts):
                    raise ValueError("Missing argument after " + token)
                value = expand(ts[i], env)
                i += 1
                if token in ("-f", "-F"):
                    child = (base / value).resolve()
                    visit(child, child.parent if token == "-F" else base)
                    continue
                token += value
            if token.startswith("+incdir+") or token.startswith("-I"):
                dirs = token[8:].split("+") if token.startswith("+incdir+") else [token[2:]]
                for d in dirs:
                    p = (base / d).resolve()
                    if not d or not p.is_dir():
                        raise ValueError("Include directory does not exist: " + str(p))
                    if str(p) not in result["include_dirs"]:
                        result["include_dirs"].append(str(p))
            elif token.startswith("+define+") or token.startswith("-D"):
                values = token[8:].split("+") if token.startswith("+define+") else [token[2:]]
                _add_defines(result, values)
            elif token in ("-sv", "-sverilog"):
                pass
            elif token.startswith(("-", "+")):
                raise ValueError("Unsupported file-list option (never ignored): " + token)
            else:
                _add_source(result, base / token)
        stack.pop()

    path = Path(path).resolve()
    visit(path, path.parent)
    if require_sources and not result["sources"]:
        raise ValueError("Empty file list")
    return result


def snapshot(inputs, folder):
    """Copy source/include trees once; every subsequent tool uses these bytes."""
    folder = Path(folder)
    roots = list(dict.fromkeys([str(Path(p).parent) for p in inputs["sources"]] + inputs["include_dirs"]))
    mappings, evidence = {}, []
    count, total = 0, 0
    for index, root in enumerate(roots):
        root = Path(root)
        dest = folder / "sources" / f"d{index}"
        mappings[str(root)] = dest.relative_to(folder).as_posix()
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in (".v", ".sv", ".vh", ".svh", ".h"):
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError("Include snapshots cannot follow links outside their root")
            count += 1
            total += path.stat().st_size
            if count > 4096 or total > 64 * 1024 * 1024:
                raise ValueError("HDL snapshot exceeds 4096 files / 64 MiB; narrow the include directories")
            target = dest / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            evidence.append({"original": str(path), "file": target.relative_to(folder).as_posix(), "sha256": sha(target)})
    sources = [mappings[str(Path(p).parent)] + "/" + Path(p).name for p in inputs["sources"]]
    manifest = {"sources": [{"file": p, "sha256": sha(folder / p)} for p in sources],
                "include_dirs": [mappings[p] for p in roots], "defines": inputs["defines"],
                "snapshots": evidence, "filelists": inputs["filelists"]}
    dump(folder / "inputs.json", manifest)
    return manifest
