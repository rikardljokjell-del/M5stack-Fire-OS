"""Safe model outcome diagnostics. Never retain model text or reasoning content."""


class GenerationResponseError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(detail)


def response_meta(response, limit, effort):
    def field(obj, name, default=None):
        return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)
    status = field(response, 'status')
    reason = field(field(response, 'incomplete_details'), 'reason')
    refusal = any(field(part, 'type') == 'refusal' for item in field(response, 'output', [])
                  for part in field(item, 'content', []) or [])
    code = ('ai_refused' if refusal or reason == 'content_filter' else
            'ai_output_limit' if status == 'incomplete' and reason == 'max_output_tokens' else
            'ai_incomplete' if status != 'completed' else
            'ai_invalid_response' if field(response, 'output_parsed') is None else '')
    return {'provider_status': status if status in {'completed','incomplete','failed','cancelled'} else 'unknown',
            'incomplete_reason': reason if reason in {'max_output_tokens','content_filter'} else None,
            'failure_code': code, 'max_output_tokens': limit, 'reasoning_effort': effort}


def response_error(meta, usage):
    code = meta['failure_code']
    if not code:
        return None
    def field(obj, name, default=0):
        return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)
    output = field(usage, 'output_tokens')
    reasoning = field(field(usage, 'output_tokens_details', {}), 'reasoning_tokens')
    ceiling=f"backendens svargrense på {meta['max_output_tokens']} tokens" if meta['max_output_tokens'] else 'modellens egen svargrense'
    details = {
        'ai_output_limit': f"AI-svaret nådde {ceiling}. "
            f"{reasoning} av {output} outputtokens var intern resonnering; "
            "ingen fullstendig, validert app ble levert. Planen er bevart. Velg Resume for å prøve igjen.",
        'ai_refused': 'AI avslo forespørselen. Planen er bevart; velg Resume for å endre den.',
        'ai_incomplete': 'Forbindelsen til AI ga ikke et fullført svar. Planen er bevart; velg Resume og prøv igjen.',
        'ai_invalid_response': 'AI returnerte ikke gyldig appkode/kodekontroll. Planen er bevart; velg Resume og prøv igjen.',
    }
    return GenerationResponseError(code, details[code])


def build_failure(store, build):
    """Also explain old failed jobs whose original response metadata was lost."""
    detail = build.get('error', '')
    code = build.get('error_code', '')
    if 'validation error' in detail and 'GeneratedApp' in detail:
        code='ai_invalid_response'
        detail='AI returnerte et ugyldig appformat. Planen er bevart; velg Resume og prøv igjen. Detalj: '+detail
    if 'incomplete or refused' in detail:
        rows = [r for r in store.list('usage') if r.get('build_id') == build['id'] and r.get('operation') in {'generate','review'}]
        last = max(rows, key=lambda r:r.get('started_at',0), default={})
        output, reasoning = last.get('output_tokens',0), last.get('reasoning_tokens',0)
        if output >= 8000 and reasoning == output:
            code = 'ai_output_limit'
            detail = (f'AI brukte alle {output} svartokens på intern resonnering og returnerte ingen appkode. '
                      'Dette var en grense i backend-oppsettet, ikke en feil fra FIRE. Planen er bevart; velg Resume.')
        else:
            code='ai_incomplete'
            detail='AI returnerte ikke et komplett svar. Den gamle loggen skiller ikke avkutt fra avslag. Planen er bevart; velg Resume.'
    from .status_text import error_text
    return {'error_code': code or 'operation_failed', 'error_status': error_text(detail, code),
            'diagnostic_message': detail, 'retryable': build.get('status') == 'failed'}
