"""Exercise the documentation verifier against external registry counterexamples."""
from pathlib import Path
import tempfile,shutil,subprocess,sys,re
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='documentation-contract-')as folder:
 target=Path(folder)/'repo';shutil.copytree(root,target,ignore=shutil.ignore_patterns('.git','__pycache__'))
 def run():return subprocess.run([sys.executable,'scripts/verify_documentation.py'],cwd=target,capture_output=True,text=True)
 assert run().returncode==0,'Baseline documentation must be valid'
 p=target/'docs/KNOWN_ISSUES.md';original=p.read_text()
 changed=re.sub(r'Platí pro veřejný zdroj [0-9.]+\.', 'Platí pro veřejný zdroj 0.0.0.',original,count=1);assert changed!=original;p.write_text(changed)
 assert run().returncode!=0,'Verifier accepted stale registry version'
 p.write_text(original)
 lines=original.splitlines();first=next(i for i,line in enumerate(lines)if re.match(r'^\| [A-Z][A-Z0-9]*-\d+ \|',line));lines.insert(first+1,'')
 p.write_text('\n'.join(lines)+'\n');assert run().returncode!=0,'Verifier accepted disconnected finding rows'
 p.write_text(original);assert run().returncode==0
print('PASS: registry version drift and broken Markdown table are rejected')
