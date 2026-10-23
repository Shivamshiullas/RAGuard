"""Download the embedding model into ./models (run once, before starting the app).

The app itself never downloads models: it loads them from this folder at startup, so a slow
network can't make the first question time out.

Usage:  python scripts/download_models.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from raguard.config import load_settings  # noqa: E402
from raguard.indexes import download_model  # noqa: E402


def main() -> None:
    s = load_settings()
    print(f"Downloading {s.embedding_model} into {s.models_dir} …")
    for path in download_model(s.embedding_model, s.models_dir):
        print("  ", path)
    print("Done.")


if __name__ == "__main__":
    main()
