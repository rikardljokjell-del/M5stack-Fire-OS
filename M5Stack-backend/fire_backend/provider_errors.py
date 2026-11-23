"""Classify account limits without copying provider bodies into logs or events."""


def account_limit(error):
    return (getattr(error,'code',None) in {
        'insufficient_quota','credit_balance_exhausted','billing_hard_limit_reached',
        'organization_usage_limit_exceeded','billing_not_active',
    } or getattr(error,'type',None)=='insufficient_quota')
