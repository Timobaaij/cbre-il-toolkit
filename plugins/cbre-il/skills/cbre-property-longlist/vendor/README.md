# What is in this folder, and how to verify it

This folder holds one file: a **PyMuPDF wheel**, bundled so PDF extraction works on a
machine where PyMuPDF is not installed and cannot be installed (the common case in
Cowork). `helpers/_vendor_wheels.py` unpacks it into a temp directory and imports from
there; it is never installed into the system environment.

It is a **compiled binary**, so an automated security scan cannot read what is inside it.
That is why a scanner may report that it "found something that couldn't be confirmed" —
the warning is about *unverifiability*, not about anything it found. The provenance is
recorded here so a human can confirm it in one command.

## Provenance

| | |
|---|---|
| File | `pymupdf-1.27.2.3-cp310-abi3-manylinux_2_28_x86_64.whl` |
| Upstream | [PyMuPDF 1.27.2.3 on PyPI](https://pypi.org/project/PyMuPDF/1.27.2.3/#files) |
| Size | 24,963,198 bytes |
| SHA256 | `857842b4888827bd6155a1131341b2822a7ebe9a8c15a975fd7d490d7a64a30c` |
| Licence | GNU AGPL v3 (PyMuPDF's own licence; see the wheel's `dist-info`) |

The SHA256 above is the digest **PyPI publishes for that exact filename**. The bundled
copy is byte-identical to the official release: it has not been rebuilt, repacked or
modified.

## Verify it yourself

```bash
sha256sum pymupdf-1.27.2.3-cp310-abi3-manylinux_2_28_x86_64.whl
```

Compare the result with the SHA256 above, and with the digest PyPI shows for the same
filename at the link above. If the three agree, the wheel is the upstream artefact.

To see what it contains without executing anything:

```bash
python -c "import zipfile; print('\n'.join(zipfile.ZipFile('pymupdf-1.27.2.3-cp310-abi3-manylinux_2_28_x86_64.whl').namelist()))"
```

## Known gap

`assets/integrity.json` does **not** currently cover this file — `make_integrity.py`
hashes `helpers/*.py`, `prompts/*.md` and a fixed asset list, and the wheel is in none of
them. So `preflight.py` reports OK even if the wheel were swapped. The digest above is the
only check on it today. Adding `vendor/*.whl` to the manifest would close that.
