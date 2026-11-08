"""CPU role plans shared by collection and recorded-evidence audit."""
import csv
from pathlib import Path

ROLES = ('du_cpus', 'main_pool_cpus', 'ru_cpus', 'dqn_cpus', 'observer_cpus')
# v4 adds explicit housekeeping/spare columns; v3 CSVs keep loading unchanged.
V4_ROLES = ROLES + ('spare_cpus', 'housekeeping_cpus')


def load_layout_plan(path=None):
    if path is None:
        layouts = {}
        for layout in ('shared', 'split'):
            du = list(range(8 if layout == 'shared' else 4))
            layouts[layout] = dict(du_cpus=du, main_pool_cpus=du, ru_cpus=du,
                                   dqn_cpus=list(range(8)) if layout == 'shared' else list(range(4, 8)),
                                   observer_cpus=[])
        return {'name': 'legacy-v2', 'layouts': layouts}
    path = Path(path)
    with path.open(newline='') as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if fields == {'layout', *ROLES}:
            columns = ROLES
        elif fields == {'layout', *V4_ROLES}:
            columns = V4_ROLES
        else:
            raise ValueError('CPU plan needs layout and all five (v3) or seven (v4) CPU role columns')
        layouts = {}
        for row in reader:
            name = row['layout']
            if name not in ('shared', 'split') or name in layouts:
                raise ValueError('CPU plan needs exactly one shared and one split row')
            roles = {}
            for role in columns:
                values = [int(v.strip()) for v in row[role].split(',')]
                if not values or min(values) < 0 or len(set(values)) != len(values):
                    raise ValueError(f'{name}: empty, duplicate or negative {role}')
                roles[role] = sorted(values)
            du, pool, ru, ai, observer = (set(roles[k]) for k in ROLES)
            if len(pool) < 3 or not (pool | ru) <= du:
                raise ValueError(f'{name}: DU must contain RU and at least three main-pool CPUs')
            if pool & ru or ru & ai or observer & (du | ai):
                raise ValueError(f'{name}: RU/pool/AI or observer CPU isolation violated')
            if name == 'split' and du & ai:
                raise ValueError('split: DU and AI overlap')
            if name == 'shared' and not pool & ai:
                raise ValueError('shared: AI must share main-pool CPUs')
            layouts[name] = roles
    if set(layouts) != {'shared', 'split'}:
        raise ValueError('CPU plan needs both layouts')
    if layouts['shared']['observer_cpus'] != layouts['split']['observer_cpus']:
        raise ValueError('Observer CPUs must match across layouts')
    if layouts['shared']['ru_cpus'] != layouts['split']['ru_cpus']:
        raise ValueError('RU CPUs must match across layouts')
    if columns == V4_ROLES:
        validate_v4(layouts)
    return {'name': path.stem, 'layouts': layouts, 'version': 4 if columns == V4_ROLES else 3}


def validate_v4(layouts):
    """v4: identical DU in both layouts, only AI placement differs."""
    for name, roles in layouts.items():
        du, pool, ru, ai, observer, spare, house = (set(roles[k]) for k in V4_ROLES)
        if spare != du - pool - ru:
            raise ValueError(f'{name}: spare_cpus must be exactly DU CPUs without RU/main-pool RT threads')
        if not house or house & du or not observer <= house:
            raise ValueError(f'{name}: housekeeping CPUs must be outside DU and contain the observer')
        if ai & house:
            raise ValueError(f'{name}: AI must not use housekeeping CPUs')
        if ai & (ru | spare):
            raise ValueError(f'{name}: AI may only overlap main-pool CPUs, never RU or spare CPUs')
    for key in ('du_cpus', 'main_pool_cpus', 'ru_cpus', 'spare_cpus', 'housekeeping_cpus'):
        if layouts['shared'][key] != layouts['split'][key]:
            raise ValueError(f'v4: {key} must be identical across layouts; only AI placement may differ')
    if len(layouts['shared']['dqn_cpus']) != len(layouts['split']['dqn_cpus']):
        raise ValueError('v4: AI CPU count must match across layouts')


def required_cpus(plan):
    return {cpu for roles in plan['layouts'].values() for role in ROLES for cpu in roles[role]}


def validate_du_roles(rows, roles):
    for prefix, key, count in [('main_pool#', 'main_pool_cpus', 3), ('ru_dummy', 'ru_cpus', 1)]:
        workers = [r for r in rows if r['name'].startswith(prefix)]
        if len(workers) != count or len({r['name'] for r in workers}) != count:
            raise RuntimeError(f'Expected {count} distinct {prefix} workers, observed {len(workers)}')
        for worker in workers:
            if (not worker['cpus'] or not set(worker['cpus']) <= set(roles[key]) or
                    worker['policy'] not in [1, 2] or worker['rt_priority'] <= 0):
                raise RuntimeError(f'{worker["name"]}: role CPU mask or RT policy mismatch')
