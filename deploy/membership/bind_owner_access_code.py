#!/usr/bin/env python3
"""Bind one reusable credential to the verified existing owner; never print it."""
import json
import os
from pathlib import Path
import sys


def private_write(path, value):
    temporary = path.with_name(path.name + '.pending')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    os.fsync(directory)
    os.close(directory)


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run as root')
    identity = Path('/opt/jt-identity')
    sys.path.insert(0, '/home/admin/comfy-panel')
    from membership_store import MembershipStore
    state = json.loads((identity / 'state.json').read_text())
    assert state['phase'] == 'sealed'
    target = identity / 'owner-access-code.json'
    item = json.loads(target.read_text()) if target.exists() else None
    database = Path('/home/admin/comfy-panel/panel_data/membership.sqlite3')
    metadata = database.stat()
    # Use the running service's file owner for SQLite/WAL creation. Only the
    # private operator handoff is written as root after restoring privileges.
    os.setegid(metadata.st_gid)
    os.seteuid(metadata.st_uid)
    try:
        store = MembershipStore(database)
        owner = store.get_user_by_identity(state['owner_issuer'], state['owner_subject'])
        assert owner and owner['is_admin'] and not owner['disabled'], 'Original owner was not verified'
        if item:
            assert item['user_id'] == owner['id'], 'Existing private handoff belongs to another account'
            with store._connection() as db:
                row = db.execute('SELECT user_id,revoked_at FROM login_credentials WHERE id=?', (item['id'],)).fetchone()
                assert row and row['user_id'] == owner['id'] and row['revoked_at'] is None, 'Saved credential was replaced; use the latest operator handoff'
        else:
            item = store.rotate_access_code(owner['id'], owner['id'], '站主切换为长期激活码登录，沿用原账号与数据')
    finally:
        os.seteuid(0)
        os.setegid(0)
    if not target.exists():
        private_write(target, json.dumps(item, ensure_ascii=False, indent=2))
    body = f'''JT 创作台 · 站主登录激活码

工作台：https://studio.dreamapi.club/
登录激活码：{item['code']}

这是原站主账号的长期登录凭证，原套餐、任务、历史和收藏都沿用。
复制上面的完整激活码，在工作台登录页输入即可；不用注册用户名或密码。
请像密码一样保管，不要把此站主码发给顾客。

给新顾客：管理后台 → 登录激活码 → 选择套餐并生成，单独发给每位付款用户。
老顾客续费：管理后台 → 续费码 → 发给用户在原账号中兑换，原登录码继续使用。
丢码恢复：核实订单与原用户后，在管理后台 → 用户 → 更换登录码，原数据保留。
原管理员身份入口仍保留作为恢复入口，账号密码见之前私密交付文件。
'''
    private_write(identity / 'owner-access-code.txt', body)
    print(json.dumps({'owner_preserved': True, 'credential_file': str(identity / 'owner-access-code.txt'),
                      'code_printed': False, 'created_user': False}))


if __name__ == '__main__':
    main()
