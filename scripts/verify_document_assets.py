"""Verify a stored page-asset catalogue without trusting file existence alone."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def verify(catalogue: Path, storage_root: Path) -> dict:
    from PIL import Image
    data = json.loads(catalogue.read_text(encoding="utf-8"))
    failures: list[dict] = []
    for item in data.get("items", []):
        path = (storage_root / item.get("asset_path", "")).resolve()
        try:
            payload = path.read_bytes()
            with Image.open(path) as image:
                image.verify()
            if item.get("sha256") and hashlib.sha256(payload).hexdigest() != item["sha256"]:
                raise ValueError("sha256 mismatch")
        except Exception as exc:  # report every bad page for release evidence
            failures.append({"page_no": item.get("page_no"), "error": str(exc)})
    return {"valid": not failures, "checked": len(data.get("items", [])), "failures": failures}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("--storage-root", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.catalogue, args.storage_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)
