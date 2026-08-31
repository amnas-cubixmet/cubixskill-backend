import ipaddress
import urllib.parse
from rest_framework.exceptions import ValidationError

BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('169.254.0.0/16'),
    ipaddress.ip_network('0.0.0.0/8'),
    ipaddress.ip_network('::1/128'),
    ipaddress.ip_network('fc00::/7'),
    ipaddress.ip_network('fe80::/10'),
]

SUPPORTED_AUDIO_EXTENSIONS = (
    '.mp3', '.m4a', '.ogg', '.wav', '.aac', '.flac', '.opus', '.webm', '.mp4a'
)

GENERIC_WEBPAGE_EXTENSIONS = (
    '.html', '.htm', '.php', '.asp', '.aspx', '.jsp'
)

def validate_audio_url(url_str: str) -> str:
    if not url_str or not isinstance(url_str, str):
        raise ValidationError("Audio URL is required.")

    clean_url = url_str.strip()
    if not clean_url:
        raise ValidationError("Audio URL cannot be blank.")

    try:
        parsed = urllib.parse.urlparse(clean_url)
    except Exception:
        raise ValidationError("Enter a valid audio URL.")

    # 1. Scheme Check
    if parsed.scheme.lower() not in ['http', 'https']:
        raise ValidationError("Audio URL must use http or https scheme.")

    # 2. Embedded Credentials Check
    if parsed.username or parsed.password:
        raise ValidationError("Audio URL must not contain embedded user credentials.")

    # 3. Host Check & SSRF Protection
    hostname = (parsed.hostname or '').lower()
    if not hostname:
        raise ValidationError("Enter a valid audio URL with a valid domain or host.")

    if hostname in ['localhost', 'loopback', 'metadata', 'local']:
        raise ValidationError("Audio URL targets a restricted local address.")

    try:
        ip = ipaddress.ip_address(hostname)
        for net in BLOCKED_IP_NETWORKS:
            if ip in net:
                raise ValidationError("Audio URL targets a restricted private or internal IP address.")
    except ValueError:
        # Not a raw IP literal, which is normal for domains
        pass

    # 4. Audio Path / Format Validation
    path = parsed.path.lower()

    if any(path.endswith(ext) for ext in GENERIC_WEBPAGE_EXTENSIONS):
        raise ValidationError("This link points to a webpage, not a playable audio file.")

    is_direct_audio_ext = any(path.endswith(ext) for ext in SUPPORTED_AUDIO_EXTENSIONS)
    has_audio_path_keyword = any(kw in path or kw in parsed.query.lower() for kw in ['/audio/', 'audio/', '.mp3', '.m4a', '.ogg', '.wav', '.aac', '.flac', 'format=audio', 'type=audio'])

    if not is_direct_audio_ext and not has_audio_path_keyword:
        if path.count('/') <= 1 and not parsed.query and not is_direct_audio_ext:
            raise ValidationError("This link points to a webpage, not a playable audio file.")

    return clean_url
