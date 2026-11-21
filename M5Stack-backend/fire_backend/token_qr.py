"""Plain-text device-token QR. Never a URL, file or credential-bearing log."""


def token_matrix(settings, device_id):
    import qrcode
    token = settings.device_tokens().get(device_id)
    if not token or len(token) < 24:
        raise ValueError("Lagre enhets-ID og token først.")
    forbidden = [settings.openai_api_key.get_secret_value(), settings.fire_backend_token.get_secret_value(),
                 *[value for key, value in settings.device_tokens().items() if key != device_id]]
    if any(secret and secret in token for secret in forbidden):
        raise ValueError("Enhetstoken må være forskjellig fra andre nøkler.")
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    code.add_data(token)
    code.make(fit=True)
    return code.get_matrix()
