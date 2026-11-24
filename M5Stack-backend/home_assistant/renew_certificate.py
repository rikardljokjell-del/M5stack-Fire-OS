"""Renew the LAN broker certificate without changing FIRE's CA or credentials."""
import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path


def renew(directory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    from .contract import DeviceProfile
    directory=Path(directory).resolve()
    profile=DeviceProfile.model_validate_json((directory/"device-profile.json").read_text())
    folder=directory/"certs"
    ca=x509.load_pem_x509_certificate((folder/"ca.pem").read_bytes())
    key=serialization.load_pem_private_key((folder/"ca-private.key").read_bytes(),password=None)
    a=ca.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    b=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    if a!=b:raise ValueError("Local CA key does not match its public certificate")
    now=datetime.now(timezone.utc)
    if ca.not_valid_after_utc<now+timedelta(days=7):raise ValueError("Local CA is expiring; create a new profile and pair FIRE again")
    try:san=x509.IPAddress(ipaddress.ip_address(profile.local_host))
    except ValueError:san=x509.DNSName(profile.local_host)
    serverkey=ec.generate_private_key(ec.SECP256R1())
    cert=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,profile.local_host)]))
       .issuer_name(ca.subject).public_key(serverkey.public_key()).serial_number(x509.random_serial_number())
       .not_valid_before(now-timedelta(minutes=5)).not_valid_after(min(ca.not_valid_after_utc,now+timedelta(days=365)))
       .add_extension(x509.SubjectAlternativeName([san]),critical=False)
       .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
       .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
       .add_extension(x509.SubjectKeyIdentifier.from_public_key(serverkey.public_key()),critical=False)
       .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),critical=False)
       .sign(key,hashes.SHA256()))
    contents={"server.pem":cert.public_bytes(serialization.Encoding.PEM),
              "server.key":serverkey.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())}
    for name,data in contents.items():
        temp=folder/(name+".next");temp.write_bytes(data)
        try:temp.chmod(0o600)
        except OSError:pass
    # Restart/reload the broker only after both replacements finish.
    for name in contents:os.replace(folder/(name+".next"),folder/name)
    return cert.not_valid_after_utc.isoformat()


def main():
    parser=argparse.ArgumentParser(description="Forny lokalt Home-sertifikat; behold CA og alle passord")
    parser.add_argument("--directory",type=Path,required=True)
    args=parser.parse_args()
    print("Lokalt serversertifikat fornyet til "+renew(args.directory)+". Start bare Home-MQTT-tjenesten på nytt etter kopiering.")


if __name__=="__main__":main()
