"""Lossless SOC decision field sharing, deliberately isolated from control evidence.

Only large decisions are compacted; legacy zlib rows remain readable. The
complete canonical record, including decision_hash, must survive hydration.
The content-object table is append-only: do not garbage collect pinned objects.
"""
from .core import digest
from .store import pack, unpack

FORMAT = 'soc-deduplicated-fields-v1'
FIELDS = (
    'forecast_versions',
    'calibration_summary',
    'calibration_context',
    'house_validation',
    'battery_energy_model',
    'history_source',
    'assumptions',
)
MIN_RECORD_BYTES = 4096


def prepare(decision, original=None):
    """Pure preparation outside the SQLite writer gate.

    Returns packed record and immutable contents needed for a new decision.
    No reference may be persisted without its contents in the same transaction.
    """
    if original is None:
        original = pack(decision)
    if len(original) < MIN_RECORD_BYTES:
        return original, ()
    inline = dict(decision)
    refs = {}
    objects = []
    for name in FIELDS:
        if name not in inline:
            continue
        value = inline.pop(name)
        key = digest({'field': name, 'value': value})
        refs[name] = key
        objects.append((key, name, pack(value)))
    if not objects:
        return original, ()
    compact = pack({'storage_format': FORMAT, 'inline': inline, 'refs': refs})
    # A row with many tiny fields can grow rather than shrink.
    # Avoid new object churn unless the inline record itself shrinks enough.
    if len(compact) >= len(original) - 512:
        return original, ()
    return compact, tuple(objects)


def store_objects(db, objects):
    for key, name, packed in objects:
        previous = db.execute('SELECT field,payload FROM soc_decision_parts WHERE hash=?', (key,)).fetchone()
        if previous is None:
            db.execute('INSERT INTO soc_decision_parts VALUES(?,?,?)', (key, name, packed))
        elif previous != (name, packed):
            raise ValueError('SOC_PART_HASH_COLLISION_OR_CORRUPTION')


def read(db, blob):
    value = unpack(blob)
    if not isinstance(value, dict):
        raise ValueError('SOC_DECISION_CORRUPT_RECORD')
    # Ordinary legacy records are unchanged; compact envelope cannot be
    # confused with a genuine sealed decision.
    if value.get('storage_format') != FORMAT:
        return value
    refs = value.get('refs')
    inline = value.get('inline')
    if not isinstance(refs, dict) or not isinstance(inline, dict):
        raise ValueError('SOC_PART_INVALID_ENVELOPE')
    if set(refs) - set(FIELDS) or set(refs).intersection(inline):
        raise ValueError('SOC_PART_INVALID_REFERENCES')
    if not refs or 'decision_hash' not in inline:
        raise ValueError('SOC_PART_MISSING_DECISION_HASH')
    full = dict(inline)
    for name, key in refs.items():
        row = db.execute('SELECT field,payload FROM soc_decision_parts WHERE hash=?', (key,)).fetchone()
        if row is None or row[0] != name:
            raise ValueError('SOC_PART_MISSING_OR_WRONG_FIELD')
        field_value = unpack(row[1])
        if digest({'field': name, 'value': field_value}) != key:
            raise ValueError('SOC_PART_HASH_MISMATCH')
        full[name] = field_value
    return full
