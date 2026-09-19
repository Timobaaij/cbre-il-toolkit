#!/usr/bin/env python3
"""Validate every SKILL.md in this marketplace the way a client actually reads it.

WHY THIS EXISTS. `claude plugin validate .` checks the marketplace and plugin
manifests. It does NOT parse skill front matter, so a skill whose YAML is invalid
passes validation, installs cleanly, reports the right plugin version, and then
simply does not appear. There is no error anywhere. Four skills shipped that way
before anyone noticed, and the first two were missing for weeks.

TWO FAULTS CAUSE IT, and both are silent.

1. AN UNQUOTED COLON-SPACE INSIDE THE DESCRIPTION.

       description: Produce a CBRE I&L OCCUPIER BRIEF: a short, dense dossier ...
                                                      ^^ here

   In YAML a plain (unquoted) scalar cannot contain ": " - the parser reads it as a
   nested mapping key and raises "mapping values are not allowed here". Quote the
   whole value. Prose descriptions want colons, so this will keep happening.

2. A DESCRIPTION LONGER THAN 1024 CHARACTERS. Measured, not documented: on a real
   install, every skill at or below 993 characters loaded and both skills above 1024
   did not, with the YAML valid in all cases. Two of them were missing for weeks.
   Keep descriptions comfortably under the cap; the body of SKILL.md is the place for
   detail, and a shorter description is better for triggering anyway.

Run it before every release:

    python tools/validate_skills.py

Exit 0 = every skill will load. Exit 1 = at least one will vanish silently.
"""

import pathlib
import re
import sys

try:
    import yaml
except ImportError:                                   # pragma: no cover
    print("PySkip: PyYAML not installed; cannot validate. pip install pyyaml")
    sys.exit(1)

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# Measured on a real install, not documented: skills at or below 993 characters loaded,
# skills above 1024 did not. WARN short of the cap so a description that grows by a
# sentence in the next release does not silently cross it.
DESC_MAX = 1024
DESC_WARN = 950


def front_matter(text: str):
    """Return the front-matter block, or None when the file has none."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 3)
    return None if end == -1 else text[4:end + 1]


def check(path: pathlib.Path, warnings: list[str]) -> list[str]:
    faults = []
    rel = path.relative_to(ROOT)
    directory = path.parent.name
    text = path.read_text(encoding="utf-8")

    fm = front_matter(text)
    if fm is None:
        return [f"{rel}: no `---` front matter block"]

    try:
        data = yaml.safe_load(fm)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        hint = ""
        # The one that keeps happening, named explicitly so the fix is obvious.
        if isinstance(exc, yaml.scanner.ScannerError) and "mapping values" in str(exc):
            hint = ("\n      likely an unquoted ': ' inside a value - wrap the whole "
                    "value in double quotes")
        return [f"{rel}: front matter is not valid YAML{where}{hint}"]

    if not isinstance(data, dict):
        return [f"{rel}: front matter is {type(data).__name__}, expected a mapping"]

    name = data.get("name")
    if not isinstance(name, str) or not name:
        faults.append(f"{rel}: `name` is missing or not a string")
    else:
        if name != directory:
            faults.append(f"{rel}: `name` is {name!r} but the directory is "
                          f"{directory!r} - they must match")
        if not NAME_RE.match(name):
            faults.append(f"{rel}: `name` {name!r} is not lowercase-hyphenated")

    desc = data.get("description")
    if not isinstance(desc, str) or not desc.strip():
        faults.append(f"{rel}: `description` is missing or not a string")
    elif len(desc) > DESC_MAX:
        faults.append(f"{rel}: `description` is {len(desc)} characters, over the "
                      f"{DESC_MAX} cap - the skill will not load. Move detail into the "
                      f"body of SKILL.md.")
    elif len(desc) > DESC_WARN:
        warnings.append(f"{rel}: `description` is {len(desc)} characters, only "
                        f"{DESC_MAX - len(desc)} under the {DESC_MAX} cap")

    return faults


def main() -> int:
    skills = sorted(ROOT.glob("plugins/*/skills/*/SKILL.md"))
    if not skills:
        print("no SKILL.md files found - is this the marketplace root?")
        return 1

    faults, warnings = [], []
    for path in skills:
        found = check(path, warnings)
        faults += found
        status = "FAIL" if found else "ok"
        print(f"  {status:4s}  {path.parent.name}")

    print()
    if warnings:
        print("close to the limit:")
        for w in warnings:
            print(f"  - {w}")
        print()
    if faults:
        print(f"{len(faults)} fault(s) - these skills will NOT load:")
        for f in faults:
            print(f"  - {f}")
        return 1

    print(f"{len(skills)} skills, all will load")
    return 0


if __name__ == "__main__":
    sys.exit(main())
