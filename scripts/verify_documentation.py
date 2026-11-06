"""Static documentation contract; never imports runtime or contacts HA."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
version = re.search(r'^version: "([^"]+)"$', (ROOT / "priority_shadow/config.yaml").read_text(), re.M)[1]
readme = (ROOT / "README.md").read_text()
row = next(line for line in readme.splitlines() if "| Samostatné noční stínové" in line)
assert row.rstrip().endswith("| " + version + " |"), ("README version drift", version, row)
status = (ROOT / "docs/PROJECT_STATUS.md").read_text()
assert "<!-- shadow-version: " + version + " -->" in status, "Status version drift"
documents = [
    "README.md", "docs/PROJECT_STATUS.md", "docs/KNOWN_ISSUES.md",
    "docs/TEST_MATRIX.md", "docs/RELEASE_RUNBOOK.md",
    "docs/history/DOCUMENTATION_CLOSEOUT_20261106.md",
]
links = 0
for name in documents:
    path = ROOT / name
    assert path.is_file(), name
    for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
        if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            continue
        target = target.split("#", 1)[0]
        destination = (path.parent / target).resolve()
        assert destination.is_relative_to(ROOT), (name, target, "outside repository")
        assert destination.exists(), (name, target, "missing reference")
        links += 1
issues = (ROOT / "docs/KNOWN_ISSUES.md").read_text()
for issue in ("N06-01", "N06-02", "DB-01", "DATA-01", "BACKUP-01", "MON-01", "LIVE-01", "LIVE-02", "VAL-01"):
    assert len(re.findall(r"^\| " + re.escape(issue) + r" \|", issues, re.M)) == 1, issue
if version == "0.6.24":
    assert re.search(r"^\| N06-02 \| OTEVŘENO \|", issues, re.M), "Unproven root cause must remain open for 0.6.24"
ids = re.findall(r"^\| ([A-Z][A-Z0-9]*-\d+) \|", issues, re.M)
assert len(ids) == len(set(ids)), "Duplicate finding ID"
workflow = (ROOT / ".github/workflows/validate.yml").read_text()
assert "python scripts/verify_documentation.py" in workflow, "Documentation check is not wired into CI"
print(f"Documentation OK: shadow {version}, {len(documents)} documents, {links} local references, {len(ids)} tracked findings")
