"""Isolated generated public certificates, no host or key-file access."""
from datetime import datetime,timedelta,timezone
import importlib.util
from pathlib import Path
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes,serialization
import pytest
spec=importlib.util.spec_from_file_location('tls_check',Path(__file__).parents[1]/'scripts/check_tls_certificate.py')
tls=importlib.util.module_from_spec(spec);spec.loader.exec_module(tls)
NOW=datetime(2026,10,26,tzinfo=timezone.utc)

def certificate(days=30,hostname='candidate.example.test'):
    key=ec.generate_private_key(ec.SECP256R1())
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,hostname)])
    cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1).not_valid_before(NOW-timedelta(days=2)).not_valid_after(NOW+timedelta(days=days)).add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]),critical=False).sign(key,hashes.SHA256())
    return cert.public_bytes(serialization.Encoding.PEM)

def test_public_leaf_checks_expiry_hostname_and_does_not_claim_trust_or_renewal():
    result=tls.check_certificate(certificate(),'candidate.example.test',now=NOW)
    assert result['status']=='passed' and result['chain_trust']=='not_verified'
    assert result['renewal_mechanism']=='not_verified' and not result['production_change']
    assert tls.check_certificate(certificate(3),'candidate.example.test',now=NOW)['status']=='blocked'
    assert tls.check_certificate(certificate(),'other.example.test',now=NOW)['status']=='blocked'
    assert tls.check_certificate(certificate(-1),'candidate.example.test',now=NOW)['status']=='blocked'

def test_wildcard_one_label_only_and_private_key_refusal():
    assert tls.check_certificate(certificate(hostname='*.example.test'),'candidate.example.test',now=NOW)['status']=='passed'
    assert tls.check_certificate(certificate(hostname='*.example.test'),'deep.candidate.example.test',now=NOW)['status']=='blocked'
    with pytest.raises(ValueError):tls.check_certificate(b'-----BEGIN PRIVATE KEY-----','candidate.example.test')
    with pytest.raises(ValueError):tls.check_certificate(certificate(),'candidate.example.test',now=NOW.replace(tzinfo=None))
