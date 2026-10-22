"""List interface keys used in templates and code that have no translation. Run: python tools/i18n_check.py"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.i18n import T  # noqa: E402

root = Path(__file__).resolve().parent.parent / "app"
used = set()
for path in list(root.rglob("*.html")) + list(root.rglob("*.py")):
    text = path.read_text(encoding="utf-8")
    used |= set(re.findall(r"""\bt\(\s*'([a-z0-9_]+)'""", text))
    used |= set(re.findall(r"""\bt\(\s*"([a-z0-9_]+)\"""", text))
    used |= set(re.findall(r"""flash\(request,\s*"([a-z0-9_]+)\"""", text))
    used |= set(re.findall(r"""(?:raise OrderError|"err_[a-z_]+"|"form_[a-z_]+")""", text) and
                re.findall(r"""["']((?:err|form)_[a-z0-9_]+)["']""", text))
missing = sorted(k for k in used if k not in T)
print("\n".join(missing))
print(f"{len(missing)} missing", file=sys.stderr)
