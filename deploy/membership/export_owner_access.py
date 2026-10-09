#!/usr/bin/env python3
"""Create a private operator handoff containing only the two login passwords."""
import json
import os
from pathlib import Path


def main():
    if os.geteuid()!=0:raise RuntimeError('Run as root')
    root=Path('/opt/jt-identity')
    credentials=json.loads((root/'bootstrap-credentials.json').read_text())
    body=f'''JT 创作台管理员登录信息

此文件只交付站主，不要放进网站目录、群聊或公开网盘。

一、工作台管理员（管理套餐、激活码、会员）
网址：https://studio.dreamapi.club/
账号：owner
初始密码：{credentials['workbench_owner_password']}
账户资料：https://auth.dreamapi.club/login/jt-users

二、身份后台管理员（管理账号、密码、登录安全）
网址：https://auth.dreamapi.club/login/built-in
账号：admin
初始密码：{credentials['identity_admin_password']}

首次登录后请各自修改密码，并在个人资料中添加身份验证器（TOTP）二次验证。
启用二次验证前请保存恢复码；目前没有强制扫码，不会因未配置而锁定登录。
套餐线下收款后，由工作台管理员在后台生成激活码；普通用户兑换获得套餐。
没有为普通用户开放任何后台服务的共享密钥，此文件也不包含 OAuth 客户端密钥。
'''
    target=root/'owner-access.txt'
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as handle:
        handle.write(body);handle.flush();os.fsync(handle.fileno())
    os.chmod(target,0o600)
    print(json.dumps({'created':str(target),'contains_client_secret':False,'passwords_printed':False}))


if __name__=='__main__':main()
