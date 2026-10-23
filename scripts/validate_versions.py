"""Static distribution/version validation; never imports an addon runtime."""
import ast
from pathlib import Path
import re
import tomllib

root=Path(__file__).resolve().parents[1]
for name in ('energy_coordinator','priority_shadow'):
    app=root/name
    version=re.search(r'^version: "([^"]+)"$',(app/'config.yaml').read_text(),re.M)[1]
    constants={t.id:n.value.value for n in ast.parse((app/'energy/core.py').read_text()).body
               if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant)
               for t in n.targets if isinstance(t,ast.Name)}
    metadata=tomllib.loads((app/'pyproject.toml').read_text())['project']['version']
    assert version==constants['VERSION'],(name,version,constants.get('VERSION'))
    if name=='priority_shadow':
        assert version==metadata,(name,version,metadata)
    elif version!=metadata:
        print('Known legacy packaging metadata:',name,metadata,'runtime/catalog:',version)
    for directory in ('energy','config','tests'):
        assert (app/directory).is_dir(),(name,directory)
    assert not any(p.is_symlink() for p in app.rglob('*')),'Build contexts must be self-contained'
    print(name,version,'self-contained')
