"""Wire compatibility with FIRE's current case-sensitive HTTP header parser."""
from starlette.responses import FileResponse


class DeviceFileResponse(FileResponse):
    def __init__(self, *args, transfer=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.transfer = transfer

    async def __call__(self, scope, receive, send):
        async def device_send(message):
            if message["type"] == "http.response.start":
                # HTTP names are case-insensitive, but current native firmware
                # searches for literal Content-Length:. Preserve range support
                # and streaming while making the final on-wire name compatible.
                message = {**message, "headers": [
                    (b"Content-Length" if name.lower() == b"content-length" else name, value)
                    for name, value in message["headers"]]}
            await send(message)
        if self.transfer:
            self.transfer(1)
        try:
            await super().__call__(scope, receive, device_send)
        finally:
            if self.transfer:
                self.transfer(-1)
