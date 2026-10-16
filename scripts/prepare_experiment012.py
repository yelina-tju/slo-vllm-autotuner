"""Freeze order-control and repeated-shift protocols without changing controller code."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def protocols():
    base = json.loads((ROOT / 'configs/asymmetric_recovery.json').read_text())
    reverse = {**base, 'seed': 82, 'description': 'Experiment 012: same seed82 trace, legacy first.',
               'modes': list(reversed(base['modes']))}
    repeated = {**base, 'seed': 85, 'description': 'Experiment 012: two mixed/short cycles; legacy first.',
                'modes': list(reversed(base['modes'])),
                'phases': base['phases'] + [
                    {'name': 'mixed_again', 'duration_s': 120, 'request_rate': 6, 'long_fraction': 0.2},
                    {'name': 'balanced_final', 'duration_s': 120, 'request_rate': 16, 'long_fraction': 0}]}
    return {'order_control012': reverse, 'repeated_shift012': repeated}

if __name__ == '__main__':
    for name, config in protocols().items():
        target = ROOT / 'configs' / (name + '.json')
        content = json.dumps(config, indent=2) + '\n'
        if target.exists():
            if target.read_text() != content:
                raise RuntimeError(f'Refusing to replace different protocol: {target}')
        else:
            with target.open('x') as stream:
                stream.write(content)
        print(target.name, sum(p['duration_s'] for p in config['phases']))
