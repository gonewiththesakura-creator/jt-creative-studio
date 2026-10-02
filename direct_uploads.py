"""Bind browser-uploaded RunningHub references without receiving files or API keys."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time


def challenge(secret, session_hash, scope):
    payload = dict(scope, owner=session_hash, expires=int(time.time())+900, nonce=secrets.token_hex(16))
    encoded = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()).decode()
    signature = hmac.new(secret, encoded.encode(), hashlib.sha256).hexdigest()
    return encoded+'.'+signature


def verify(secret, api_key, session_hash, token, proof, provider_name=''):
    if not isinstance(token, str) or len(token)>4096 or not isinstance(proof, str):
        raise ValueError('直传凭证无效，请重新选择文件')
    try:
        encoded, signature = token.rsplit('.', 1)
        expected = hmac.new(secret, encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected): raise ValueError()
        scope = json.loads(base64.urlsafe_b64decode(encoded))
        if scope['owner'] != session_hash or scope['expires'] <= time.time(): raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError('直传凭证已失效，请重新选择文件') from None
    if not isinstance(provider_name, str) or (provider_name and (
        not re.fullmatch(r'(?:api|openapi)/[A-Za-z0-9._/-]{1,900}', provider_name)
        or any(part in ('', '.', '..') for part in provider_name.split('/')))):
        raise ValueError('云端返回了无效的文件标识')
    expected = hmac.new(api_key.encode(), (token+'\n'+provider_name).encode(), hashlib.sha256).hexdigest()
    if not api_key or not re.fullmatch(r'[0-9a-f]{64}', proof) or not hmac.compare_digest(proof, expected):
        raise ValueError('个人 Key 与工作台生成账户不一致，请填写工作台当前使用的 API Key')
    return scope
