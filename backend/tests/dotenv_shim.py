from pathlib import Path


def load_env(path: Path) -> dict:
    """Minimal .env parser (avoids an extra dependency for tests)."""
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out
