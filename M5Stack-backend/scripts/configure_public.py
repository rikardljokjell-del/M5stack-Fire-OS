"""Save nonsecret public endpoint settings into the SAME Windows config store."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fire_backend.desktop_config import DesktopConfig, DesktopStore


def main():
    p = argparse.ArgumentParser(description="Configure FIRE Studio public hosts; never prints credentials.")
    p.add_argument("--web-origin", required=True)
    p.add_argument("--device-host", required=True)
    p.add_argument("--access-issuer", required=True)
    p.add_argument("--access-audience", required=True)
    p.add_argument("--save", action="store_true", help="Save after validation; otherwise preview only")
    args = p.parse_args()
    try:
        store = DesktopStore()
        config = DesktopConfig.model_validate({**store.config.model_dump(), "public_enabled": True,
                 "web_origin": args.web_origin.rstrip("/"), "device_host": args.device_host,
                 "access_issuer": args.access_issuer.rstrip("/"), "access_audience": args.access_audience})
        if args.save:
            store.save(config)
        print("Offentlig oppsett er " + ("lagret" if args.save else "validert; ikke lagret") + ".")
        print("Nettleser: " + config.web_origin + "/ui/")
        print("FIRE: wss://" + config.device_host + "/ws/device")
        print("La aktive jobber bli ferdige. Avslutt og åpne Windows-programmet på nytt for å lese CLI-endringen fra disk.")
    except (ValueError, OSError):
        raise SystemExit("Oppsettet kunne ikke lagres. Kontroller HTTPS-adresse, ulike vertsnavn, Access issuer og audience.") from None


if __name__ == "__main__":
    main()
