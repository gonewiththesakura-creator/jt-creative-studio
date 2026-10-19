#!/usr/bin/env python3
"""Send a short backup failure alert; invoked by ``jt-backup-alert@.service``.

Usage: jt_backup_alert.py <failed-unit-name>

Channels (all optional, configured in /etc/jt-backup/backup.env):
  JT_BACKUP_ALERT_WEBHOOK   chat robot webhook URL (WeCom, DingTalk, Feishu or generic JSON)
  JT_BACKUP_ALERT_FORMAT    wecom | dingtalk | feishu | generic (default generic)
  JT_BACKUP_ALERT_EMAIL     recipient for the local sendmail binary, if one is installed

The message holds only the host, unit, time and the safe error category from
status.json. URLs, tokens and environment values are never printed or sent.
Exit status is non-zero when no channel accepted the alert, so the journal
shows the alert itself failed.
"""
import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path


def build_message(unit):
    root = Path(os.environ.get("JT_BACKUP_ROOT", "/var/backups/jt"))
    try:
        status = json.loads((root / "status.json").read_text())
    except (OSError, ValueError):
        status = {}
    host = os.environ.get("JT_BACKUP_HOST_TAG", "") or socket.gethostname()
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"[JT 备份告警] {host}",
        f"失败单元: {unit}",
        f"时间: {now}",
        f"错误: {status.get('error') or '见 journal'}",
        f"最近一次成功: {status.get('last_success') or '无记录'}",
        f"排查: journalctl -u {unit} -n 100",
    ]
    return "\n".join(lines)


def webhook_body(fmt, text):
    if fmt in ("wecom", "dingtalk"):
        return {"msgtype": "text", "text": {"content": text}}
    if fmt == "feishu":
        return {"msg_type": "text", "content": {"text": text}}
    return {"text": text}


def send_webhook(url, fmt, text):
    raw = json.dumps(webhook_body(fmt, text), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=raw, method="POST",
                                     headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return 200 <= response.status < 300


def send_mail(recipient, text):
    sendmail = shutil.which("sendmail") or ("/usr/sbin/sendmail" if os.path.exists("/usr/sbin/sendmail") else None)
    if not sendmail:
        return False
    subject = text.splitlines()[0]
    mail = f"To: {recipient}\nSubject: {subject}\nContent-Type: text/plain; charset=utf-8\n\n{text}\n"
    result = subprocess.run([sendmail, "-t"], input=mail.encode("utf-8"), timeout=30,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def main(argv):
    unit = argv[1] if len(argv) > 1 else "jt-backup.service"
    text = build_message(unit)
    delivered = 0
    url = os.environ.get("JT_BACKUP_ALERT_WEBHOOK", "").strip()
    if url:
        try:
            if send_webhook(url, os.environ.get("JT_BACKUP_ALERT_FORMAT", "generic").strip().lower(), text):
                delivered += 1
            else:
                print("jt-backup-alert: webhook rejected the alert")
        except Exception as error:
            print(f"jt-backup-alert: webhook failed ({type(error).__name__})")
    email = os.environ.get("JT_BACKUP_ALERT_EMAIL", "").strip()
    if email:
        try:
            if send_mail(email, text):
                delivered += 1
            else:
                print("jt-backup-alert: sendmail unavailable or failed")
        except Exception as error:
            print(f"jt-backup-alert: sendmail failed ({type(error).__name__})")
    # Always leave a greppable line in the journal as the channel of last resort.
    print("jt-backup-alert: " + text.replace("\n", " | "))
    return 0 if delivered else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
