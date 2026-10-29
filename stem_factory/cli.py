import argparse
import json
from pathlib import Path
import sys
from .adapters import create
from .config import load, require_models
from .errors import FactoryError
from .factory import Factory, dry_plan
from .packaging import static_check
from .reporting import report, redact
from .validation import Validator


def parser():
    result = argparse.ArgumentParser(prog='stem-factory', description='STEM task authoring/review/local validation. Never Harbor benchmarks.')
    result.add_argument('--config', default='config/models.yaml')
    sub = result.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    run = sub.add_parser('run')
    run.add_argument('--target', type=int, default=5)
    run.add_argument('--dry-run', action='store_true')
    run.add_argument('--recover-lock', action='store_true')
    run.add_argument('--retry-uncertain', action='store_true')
    validate = sub.add_parser('validate')
    validate.add_argument('--package', type=Path)
    validate.add_argument('--static-only', action='store_true')
    validate.add_argument('--dry-run', action='store_true')
    sub.add_parser('report')
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        config = load(args.config)
        code = 0
        if args.command == 'doctor':
            output = {'python': sys.version, 'config_valid': True, 'roles': {}, 'local_validation': Validator(config).doctor()}
            for name, role in config.roles.items():
                adapter = create(role, config.adapters)
                try:
                    info = adapter.inspect()
                    output['roles'][name] = info
                    adapter.preflight()
                except FactoryError as exc:
                    output['roles'].setdefault(name, {})['ready'] = False
                    output['roles'][name]['reason'] = str(exc)
                    code = 2
            try:
                require_models(config)
            except FactoryError as exc:
                output['configuration_action'] = str(exc)
                code = 2
            if not all(v['available'] for v in output['local_validation'].values()):
                code = 2
        elif args.command == 'report':
            output = report(config.output)
        elif args.command == 'run':
            if not 1 <= args.target <= config.limits['max_candidates']:
                raise FactoryError('Target must be positive and no greater than max_candidates')
            if args.dry_run:
                output = dry_plan(config, args.target)
            else:
                output = Factory(config, retry_uncertain=args.retry_uncertain).run(args.target, args.recover_lock)
                code = 0 if output['accepted'] >= args.target else 2
        elif args.command == 'validate':
            packages = [args.package.resolve()] if args.package else sorted((config.output / 'accepted').glob('*'))
            if not packages:
                raise FactoryError('No packages to validate')
            if args.dry_run:
                output = {'dry_run': True, 'packages': [str(p) for p in packages], 'static_only': args.static_only}
            else:
                output = []
                for package in packages:
                    package = package.resolve()
                    # Author-owned factory packages only; never execute arbitrary existing task scripts.
                    if not package.is_relative_to(config.output / 'accepted') and not package.is_relative_to(config.output / 'staging'):
                        raise FactoryError('Validation is limited to factory accepted/staging packages')
                    if args.static_only:
                        output.append(static_check(package, config.validation['image']))
                        code = 2  # Explicitly incomplete; static checks do not establish runnable validity.
                    else:
                        item = Validator(config).validate(package, config.output / 'validation' / (package.name + '-manual.json'))
                        output.append(item)
                        if not item['passed']:
                            code = 2
        print(redact(json.dumps(output, indent=2, ensure_ascii=False)))
        return code
    except (FactoryError, OSError, ValueError) as exc:
        print(redact(str(exc)), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
