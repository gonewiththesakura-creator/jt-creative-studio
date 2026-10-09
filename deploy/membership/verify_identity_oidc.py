#!/usr/bin/env python3
"""Exercise the real identity service with the bootstrap owner, without JT jobs.

Secrets, OAuth codes and tokens stay in memory. The report contains boolean checks
and public claim values only. Run as root on the identity server.
"""
import base64
import hashlib
import http.cookiejar
import json
from pathlib import Path
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def unb64(value):
    return base64.urlsafe_b64decode(value+'='*((-len(value))%4))


def main():
    root=Path('/opt/jt-identity')
    credentials=json.loads((root/'bootstrap-credentials.json').read_text())
    state=json.loads((root/'state.json').read_text())
    origin=credentials['issuer']
    cookies=http.cookiejar.CookieJar()
    client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    def request(path,data=None,form=False,headers=None):
        body=None if data is None else (urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode())
        request_headers={'Accept':'application/json','Origin':origin,'Content-Type':'application/x-www-form-urlencoded' if form else 'application/json'}
        request_headers.update(headers or {})
        req=urllib.request.Request(origin+path,data=body,headers=request_headers)
        try:
            with client.open(req,timeout=20) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as error:
            return error.code,json.loads(error.read())
    verifier=secrets.token_urlsafe(48)
    nonce=secrets.token_urlsafe(24)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    redirect=credentials['public_origin']+'/api/auth/callback'
    params={'clientId':credentials['client_id'],'responseType':'code','redirectUri':redirect,'type':'code',
            'scope':'openid profile email','state':secrets.token_urlsafe(24),'nonce':nonce,
            'code_challenge_method':'S256','code_challenge':challenge}
    _,login=request('/api/login?'+urllib.parse.urlencode(params),{
        'application':'jt-workbench','organization':'jt-users','username':'owner',
        'password':credentials['workbench_owner_password'],'type':'code','autoSignin':False,
        'signinMethod':'Password','loginMethod':'password','language':'zh'})
    if login.get('status')!='ok' or not isinstance(login.get('data'),str):
        raise RuntimeError('Owner authorization code login failed: '+str(login.get('msg',''))[:250])
    payload={'grant_type':'authorization_code','code':login['data'],'redirect_uri':redirect,
             'code_verifier':verifier,'client_id':credentials['client_id'],'client_secret':credentials['client_secret']}
    status,result=request('/api/login/oauth/access_token',payload,form=True)
    token=result.get('id_token','')
    if status!=200 or token.count('.')!=2:raise RuntimeError('ID token exchange failed: '+str(result.get('error_description',result.get('error',''))))
    header,claims,signature=token.split('.')
    token_header=json.loads(unb64(header)); claims=json.loads(unb64(claims))
    _,jwks=request('/.well-known/jwks')
    key=next(k for k in jwks['keys'] if k.get('kid')==token_header.get('kid'))
    public=rsa.RSAPublicNumbers(int.from_bytes(unb64(key['e']),'big'),int.from_bytes(unb64(key['n']),'big')).public_key()
    public.verify(unb64(signature),'.'.join(token.split('.')[:2]).encode(),padding.PKCS1v15(),hashes.SHA256())
    checks={'signature_valid':True,'rsa_bits':public.key_size,'algorithm_rs256':token_header.get('alg')=='RS256',
            'issuer_matches':claims.get('iss')==origin,'subject_matches':claims.get('sub')==state['owner_subject'],
            'organization_matches':claims.get('owner')=='jt-users','nonce_matches':claims.get('nonce')==nonce,
            'audience_matches':claims.get('aud') in [credentials['client_id'],[credentials['client_id']]],
            'token_is_id_token':claims.get('tokenType')=='id-token',
            'expiry_valid':isinstance(claims.get('iat'),int) and isinstance(claims.get('exp'),int) and claims['iat']<=time.time()+30<claims['exp']}
    replay_status,replay=request('/api/login/oauth/access_token',payload,form=True)
    checks['authorization_code_replay_rejected']=bool(replay.get('error')) and 'id_token' not in replay
    # An authenticated ordinary JT identity must not list global identity users.
    unauthorized_status,unauthorized=request('/api/get-users?owner=built-in',headers={'Authorization':'Bearer '+result['access_token']})
    checks['ordinary_user_global_admin_denied']=unauthorized_status in [401,403] or unauthorized.get('status')=='error'
    if any(v is not True for k,v in checks.items() if k!='rsa_bits') or public.key_size<2048:
        raise RuntimeError('Identity verification failed: '+json.dumps(checks))
    report={'checks':checks,'claim_keys':sorted(claims),'public_claims':{k:claims.get(k) for k in ['iss','owner','aud','tokenType']}}
    (root/'oidc-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
