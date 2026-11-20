import logging
import re


class Redactor:
    def __init__(self, *secrets: str):
        self.secrets = tuple(s for s in secrets if s)

    def text(self, value: str) -> str:
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")
        return re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[REDACTED]", value)

    def value(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {k: self.value(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.value(v) for v in value]
        return value


class SecretFilter(logging.Filter):
    def __init__(self, redactor):
        super().__init__()
        self.redactor = redactor

    def filter(self, record):
        record.msg = self.redactor.text(record.getMessage())
        record.args = ()
        # Third party exception reprs can contain request details.
        record.exc_info = None
        record.exc_text = None
        return True
