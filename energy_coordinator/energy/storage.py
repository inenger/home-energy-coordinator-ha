"""Velikost SQLite bez závodu s běžným zánikem dočasných souborů."""
def sqlite_bytes(directory,required=False):
    database=directory/'evidence.sqlite'
    try:total=database.stat().st_size
    except FileNotFoundError:
        if required:raise
        total=0
    for suffix in ('-wal','-shm','-journal'):
        try:total+=database.with_name(database.name+suffix).stat().st_size
        except FileNotFoundError:pass
    return total
