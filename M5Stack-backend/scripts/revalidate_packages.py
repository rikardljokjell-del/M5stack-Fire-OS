"""Stop normal backend first. Retests existing bytes; never invokes AI or FIRE."""
import argparse
import asyncio
import json

from fire_backend.config import Settings
from fire_backend.desktop_runtime import WorkspaceLock
from fire_backend.revalidation import revalidate_package
from fire_backend.security import Redactor
from fire_backend.storage import Store


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop',action='store_true',help='Use saved Windows backend workspace')
    parser.add_argument('--apply',action='store_true',help='Save validation metadata; block newly failing versions')
    args=parser.parse_args()
    if args.desktop:
        from fire_backend.desktop_config import DesktopStore
        settings=DesktopStore().settings()
    else:settings=Settings()
    lock=WorkspaceLock(settings.fire_workspace)
    try:
        redactor=Redactor(settings.openai_api_key.get_secret_value(),settings.fire_backend_token.get_secret_value(),*settings.device_tokens().values())
        store=Store(settings.fire_workspace,redactor,settings.fire_max_workspace_mb*1024*1024)
        for package in store.list('packages'):
            if package.get('validation',{}).get('suite')=='release-v4':continue
            print(json.dumps(await revalidate_package(store,package['id'],apply=args.apply),ensure_ascii=True))
    finally:lock.close()


if __name__=='__main__':asyncio.run(main())
