"""Offline public-certificate metadata gate. Never connects, renews or reads keys.

A pass is NOT chain trust, installed Nginx, active renewal or deployment evidence.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from cryptography import x509


def check_certificate(pem, hostname, *, now=None, minimum_days=14):
    if not hostname or hostname != hostname.lower() or any(c in hostname for c in '/:@*') or minimum_days < 1:
        raise ValueError('invalid_certificate_check')
    if len(pem) > 65536 or b'PRIVATE KEY' in pem or not pem.startswith(b'-----BEGIN CERTIFICATE-----'):
        raise ValueError('public_certificate_only')
    cert=x509.load_pem_x509_certificate(pem)
    names=cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    def matches(name):
        name=name.lower()
        return name==hostname or name.startswith('*.') and hostname.endswith(name[1:]) and hostname.count('.')==name.count('.')
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('timezone_required')
    current=current.astimezone(timezone.utc)
    hostname_valid=any(matches(name) for name in names)
    time_valid=cert.not_valid_before_utc<=current and cert.not_valid_after_utc>current+timedelta(days=minimum_days)
    return {'scope':'offline public leaf certificate metadata only','status':'passed' if hostname_valid and time_valid else 'blocked',
            'hostname_matches':hostname_valid,'validity_reserve_met':time_valid,'minimum_days_remaining':minimum_days,
            'not_before_utc':cert.not_valid_before_utc.isoformat(),'expires_utc':cert.not_valid_after_utc.isoformat(),
            'chain_trust':'not_verified','installed_certificate':'not_verified','renewal_mechanism':'not_verified',
            'production_change':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--certificate',type=Path,required=True);p.add_argument('--hostname',required=True);p.add_argument('--minimum-days',type=int,default=14)
    args=p.parse_args()
    try:
        if args.certificate.is_symlink() or not args.certificate.is_file() or args.certificate.stat().st_size>65536:
            raise ValueError('regular_public_certificate_required')
        result=check_certificate(args.certificate.read_bytes(),args.hostname,minimum_days=args.minimum_days)
        print(json.dumps(result,indent=2));raise SystemExit(0 if result['status']=='passed' else 1)
    except (OSError,ValueError,x509.ExtensionNotFound):
        print(json.dumps({'status':'blocked','detail':'Public certificate metadata could not be validated.','production_change':False}));raise SystemExit(1)
