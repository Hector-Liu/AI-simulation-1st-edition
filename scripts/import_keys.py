"""Copy API keys from the old Concordia builder's .env into this project's .env.

Only keys that are missing here and look real there are copied. Values are
never printed. Run automatically by start.sh.
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEW = ROOT / ".env"
OLD = ROOT.parent / "concordia-sim-builder" / ".env"
NAMES = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY")


def read(path):
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$", line)
            if m:
                out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def real(v):
    return bool(v) and len(v) >= 12 and "xxx" not in v and not v.lower().startswith("your")


def main():
    have, old = read(NEW), read(OLD)
    add = {k: old[k] for k in NAMES if not real(have.get(k)) and real(old.get(k))}
    if add:
        lines = NEW.read_text().splitlines() if NEW.exists() else ["# Local secrets. Never commit this file."]
        lines = [ln for ln in lines if not any(ln.startswith(k + "=") for k in add)]
        lines += [f"{k}={v}" for k, v in add.items()]
        NEW.write_text("\n".join(lines) + "\n")
        os.chmod(NEW, 0o600)
        print("已从旧项目导入密钥：" + ", ".join(add))
    present = [k for k in NAMES if real(read(NEW).get(k))]
    print("可用的 API 密钥：" + (", ".join(present) if present else "无（可在网页的「API 密钥」页填写）"))


if __name__ == "__main__":
    sys.exit(main())
