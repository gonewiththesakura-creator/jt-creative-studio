# JT 工作台：定时备份、异地副本与恢复演练

本文对应 `deploy/backup/` 下的脚本和 systemd 单元，日期 2026-10-19。写这份文档时这套方案**只在本地准备好，还没有部署**；服务器上实际装了什么，以执行文末清单时的记录和 `systemctl list-timers` 的结果为准。2026-10-19 审查时仓库里没有任何定时备份，服务器上是否另有 cron 也没有核实，所以清单第 1 步先只读核对现状。

## 备份范围

| 来源（生产服务器） | 快照中的位置 | 方式 |
| --- | --- | --- |
| `panel_data/membership.sqlite3`（WAL） | `panel_data/membership.sqlite3` | SQLite 在线备份 API，在一致性窗口内完成 |
| `panel_data/jobs.json`、`favorites.json`、`upload_capabilities.json`、`upload_usage.json`、`membership-owner-migration.json` | `panel_data/` 同名 | 在同一个一致性窗口内读取；`jobs.json` 必须存在，其余缺失时记为不存在 |
| `panel_data/jobs/`、`favorites/`、`media_library/`、`membership-owner-backups/` 及 `panel_data` 下其他文件 | `panel_data/` 同路径 | 增量硬链接：大小和修改时间不变的文件链接到上一份快照，不重复占空间 |
| `/opt/jt-identity/data/`（Casdoor `casdoor.db`） | `identity/` | `.db` 文件走 SQLite 在线备份，其余文件照常复制 |
| `JT_BACKUP_EXTRA_PATHS` 列出的私有配置（身份服务 compose 和 conf、`panel-membership.env`、`/etc/comfy-panel/`、`comfy-panel.service` 及 drop-in） | `config/<原绝对路径>` | 普通复制；只存在于 0600 的本地快照和加密的 restic 仓库里 |

不备份的内容：`result_image_cache/`（可以重新生成的缩略图缓存）、`*.tmp`、`.<文件名>.<uuid>.tmp` 写入临时文件、`-wal`、`-shm`、`-journal`、`*.log`、`__pycache__`。

快照中的 SQLite 副本已转成单文件（`journal_mode=DELETE`），读取时不会再产生 `-wal`/`-shm`；恢复后面板首次打开会自动切回 WAL。

## 一致性：不停服取得同一时间点

`server.py` 并没有一把覆盖所有账本的全局锁：`_lock_jobs`、`_upload_usage_lock`、`_upload_capabilities_lock` 各自保护不同的账本，每个 JSON 账本都通过 `_atomic_write_bytes`（临时文件、fsync、`os.replace`）原子替换。另一个事实是，`register_billable_job` 会**先**在 SQLite 中预占额度，**再**写 `jobs.json`。两个文件如果在不同时刻复制，就可能得到“有额度预占、没有任务”的组合。

这些锁都在进程内，外部进程拿不到，所以 `jt_backup.py` 采用“前后核对”的办法：

1. 记录每个 JSON 账本的 `(inode, 大小, mtime_ns)`，打开会员库并读取 `PRAGMA data_version`。
2. 用在线备份 API 一次性复制整个会员库（一次 `step(-1)`，处于同一个读事务内）。
3. 逐个打开 JSON 账本，读出全部字节，并用 `fstat` 记录实际读到的 inode。原子替换保证读到的是某一个完整版本。
4. 再读一次 JSON 的 stat 和 `data_version`。

只有在第 1 步到第 4 步之间**既没有任何 SQLite 提交**（其他连接一提交，`data_version` 就会变），**也没有任何 JSON 被替换**，而且读到的 inode 正是前后两次看到的那个，这份结果才被接受。这时所有文件反映的都是这个窗口里同一个时刻的状态，manifest 记为 `point-in-time`。这个窗口通常不到 1 秒；不满足条件就随机等待 0.2～2 秒再试，默认最多 20 次（`JT_BACKUP_BRACKET_ATTEMPTS`）。

如果一直被写入打断：

- 配置了 `JT_BACKUP_FREEZE_UNIT=comfy-panel.service` 时，用 `systemctl freeze` 冻结面板的 cgroup，再取一次，随后立即 `thaw`。这就是**最短停写窗口**，只有复制账本的那不到 1 秒，不会杀进程，也不会中断任务，进行中的请求只是稍有停顿。冻结时即使面板正持有 SQLite 写事务也没有关系：WAL 模式下读不被写阻塞，读到的是最后一次已提交的状态。服务单元的 `ExecStopPost` 还会再执行一次 `thaw`，保证备份脚本异常退出时面板也不会一直冻着。manifest 记为 `point-in-time-frozen`。
- 没有配置冻结，或者冻结后仍不稳定时，接受最后一次结果并记为 `crash-consistent`：每个文件各自完整，跨文件相当于在那一刻断电，面板重启时本来就要能处理这种情况。日志和演练报告会出警告。

媒体目录在账本之后复制，所以账本引用的文件只要当时还在，就一定会被收进快照。账本之后新增的文件会作为多余文件存在，不影响恢复；之后被用户删除的文件则会缺失，演练报告中统计为警告。

## 本地快照、权限与保留

- 根目录 `/var/backups/jt/`：`snapshots/<UTC 时间戳>/` 为完成的快照，`work/snapshot` 为构建中的快照（固定路径，便于 restic 找到父快照），`logs/restic-YYYYMMDD.log` 为 restic 输出，`status.json` 记录最近一次运行和最近一次成功。
- 进程 `umask 0077`；快照中所有文件 0600、所有目录 0700，属主 root。
- 每份快照都有 `manifest.json`：一致性级别、尝试次数、窗口时长、各数据库和账本的 sha256、媒体统计。完成前会对副本运行 `integrity_check` 并解析全部 JSON。
- 保留策略：每日 7 份、每周 4 份、每月 3 份（GFS，每个时间桶保留最新的一份，与 restic `forget` 语义一致，最新一份始终保留），通过 `JT_BACKUP_KEEP_*` 调整。本地快照和 restic 使用同一套规则。
- 硬链接让未变化的媒体只占一份空间；剩余空间低于 `JT_BACKUP_MIN_FREE_MB`（默认 2048）时直接失败并告警，不会把磁盘写满。
- 恢复到服务器时要 `chown -R jt-panel:jt-panel`，因为快照中的文件属主是 root。

## 异地副本（两个选项）

异地副本统一用 [restic](https://restic.net/)：客户端加密，按内容去重，自带 `forget --prune` 和 `check`。每天备份固定路径 `work/snapshot`，并带上 `--ignore-ctime --ignore-inode`，因为硬链接会改变 ctime，未变化的文件不会重复上传。

| | A. S3 兼容对象存储（阿里云 OSS、腾讯云 COS、Cloudflare R2、Backblaze B2 等） | B. 自己控制的第二台机器，运行 `rest-server --append-only` |
| --- | --- | --- |
| 运维量 | 最小：建桶、建只限这个桶的访问密钥即可 | 需要维护另一台机器的磁盘、更新和可用性 |
| 生产机被入侵后 | 服务器上的密钥有删除权限，攻击者可能删掉备份；可以用桶版本控制或对象锁保留被删版本作为缓解 | 生产机只能追加，删不掉历史；`forget --prune` 改在备份机上执行（生产端设 `JT_BACKUP_RESTIC_PRUNE=0`） |
| 成本 | 按容量和流量计费，通常很低 | 自有硬件或另一台 VPS |
| 合规 | 用户任务、收藏和账号数据含个人信息，建议选与生产服务器同一法域的地域 | 同左，取决于第二台机器在哪里 |

建议：已经有一台可靠的第二台机器（另一台云主机或 NAS）时选 B，抗勒索能力最强；否则选 A，并开启桶版本控制，至少保留 30 天被删除的版本。

凭据规则：

- `/etc/jt-backup/backup.env` 和 `/etc/jt-backup/restic-password` 都是 root:root、0600，**不进 Git**；仓库里只有占位符示例 `deploy/backup/backup.env.example`。
- restic 仓库密码必须**另外**保存在服务器之外（例如管理员的密码管理器）。服务器整机丢失时，没有这个密码，异地副本也无法解密。
- 脚本不打印环境变量、仓库地址、密码或 webhook URL；restic 的输出只写进 0600 的本地日志。

## 失败告警

- `jt-backup.service`、`jt-backup-drill.service` 和 `jt-backup-freshness.service` 失败时，都会通过 `OnFailure=` 触发 `jt-backup-alert@<单元>.service`。告警脚本发送主机、单元、时间、`status.json` 中安全的错误类别和排查命令，不包含任何密钥。
- 通道（可同时配置）：`JT_BACKUP_ALERT_WEBHOOK` 加 `JT_BACKUP_ALERT_FORMAT=wecom|dingtalk|feishu|generic`，即企业微信、钉钉、飞书群机器人或通用 JSON；本机装有 sendmail 时还可以用 `JT_BACKUP_ALERT_EMAIL` 发邮件。钉钉机器人启用“关键词”时，把关键词设为“JT 备份告警”。无论哪个通道成功，告警内容都会同时写进 journal。
- “备份根本没跑”的情况由两层覆盖：`jt-backup-freshness.timer` 每 6 小时检查一次最近成功是否超过 30 小时；`JT_BACKUP_HEARTBEAT_URL` 可接 healthchecks.io 一类的外部死信开关，成功时 ping，失败时 ping `/fail`。整台服务器宕机时只有外部心跳能发现，推荐配置。
- 离线核对的入口：`cat /var/backups/jt/status.json`、`journalctl -u jt-backup -n 100`、`systemctl list-timers 'jt-backup*'`。

## 恢复演练

`deploy/backup/jt_restore_drill.py` 只在新建的 `tempfile.mkdtemp` 临时目录里工作，结束后删除（`--keep` 可保留下来检查）。它不写源快照，拒绝读取 `/home/admin/comfy-panel`、`/opt/jt-identity`、名为 `panel_data` 或带 `-wal` 的活动目录，以及环境变量 `PANEL_DIR` 指向的目录，代码里也没有任何上传路径。

检查项：manifest 中记录的每个文件的 sha256；会员库和身份库的 `integrity_check` 和 `foreign_key_check`；会员库 `user_version`（应为 2）和各表行数；每个 JSON 账本可解析且根类型正确；`media_library/*/index.json` 可解析；跨账本核对，即“进行中的额度预占却没有任务”、“任务属于不存在的用户”、“标记已完成的收藏缺少文件”三项计数。有错误时退出码非 0，警告不导致失败。报告只有计数和检查结果。

```bash
python3 deploy/backup/jt_restore_drill.py --snapshot-dir /var/backups/jt/snapshots/<时间戳>
```

```bash
python3 deploy/backup/jt_restore_drill.py --restic latest --report drill-report.json
```

在管理员自己的电脑上从异地仓库演练时，先在当前终端里设置 `RESTIC_REPOSITORY`、`RESTIC_PASSWORD_FILE`、`JT_BACKUP_HOST_TAG`（以及选项 A 的访问密钥），再运行第二条命令。数据只解密到本机临时目录，用完即删；**不要**把解出的数据复制进本机的 `panel_data`，也不要把本机的 `panel_data` 上传到服务器。服务器上的 `jt-backup-drill.timer` 每月 8 日从异地仓库做一次同样的演练，运行在 systemd 的私有 `/tmp` 中，看不到生产目录，报告写到 `/var/backups/jt/drill-report.json`。

## 真正恢复生产数据时

这一步与演练不同，属于高风险操作，每次都要单独批准。要点沿用 [membership-operations.md](membership-operations.md) 的“备份、原站主迁移与回滚”一节：

1. 先对目标快照跑一次演练，确认通过，并确认它的时间点与要恢复的业务时间一致。
2. 暂停公开写入，按回滚流程处理正在运行的任务，然后停止 `comfy-panel.service`。
3. 先把**当前**生产数据完整另存一份（执行一次 `systemctl start jt-backup.service`，或在停服状态下手动整体复制），不要覆盖任何恢复点。
4. 把快照中的 `panel_data/` 这一份账本和数据库作为一个整体放回，`chown -R jt-panel:jt-panel`；不要只恢复其中一个文件，否则会与其他账本错位。
5. 恢复点之后产生的新用户、续费和任务会丢失，必须事先评估并记录；不能为了恢复而丢弃真实权益。
6. 启动后按 `membership-operations.md` 的发布前验证核对登录、用户隔离和额度；恢复期间不重提任何付费生成任务。

## 文件清单

| 仓库文件 | 安装位置 |
| --- | --- |
| `deploy/backup/jt_backup.py`、`jt_backup_alert.py`、`jt_restore_drill.py` | `/usr/local/libexec/jt-backup/`（root:root 0755） |
| `deploy/backup/jt-backup.service`、`.timer` | `/etc/systemd/system/`，每天 03:20（Asia/Shanghai）加最多 15 分钟随机延迟 |
| `deploy/backup/jt-backup-alert@.service` | `/etc/systemd/system/` |
| `deploy/backup/jt-backup-freshness.service`、`.timer` | `/etc/systemd/system/`，每 6 小时 |
| `deploy/backup/jt-backup-drill.service`、`.timer` | `/etc/systemd/system/`，每月 8 日 05:10 |
| `deploy/backup/backup.env.example` | 作为 `/etc/jt-backup/backup.env` 的模板，真实值只在服务器上填写 |
| `tests/test_backup_scripts.py` | 本地离线测试，不需要服务器 |

单元中的路径按 `harden_host.py` 的现状编写：代码在 `/home/admin/comfy-panel`，服务账户 `jt-panel`。如果服务器上的实际路径不同，安装前要同时修改 `backup.env` 和单元的 `ReadWritePaths=`。

## 需要用户批准后才能在服务器上执行的步骤

以下每一步都要在用户明确批准后才在生产服务器上执行，并记录执行时间和结果。各步之间相互独立，可以在任一步停下。任何一步都不重提付费生成任务，不打印密钥，不用本机数据覆盖生产数据。

1. **只读核对现状**：`crontab -l`、`ls /etc/cron.*`、`systemctl list-timers --all`，确认没有已有的备份任务会冲突；`df -h /var/backups`、`du -sh /home/admin/comfy-panel/panel_data /opt/jt-identity/data`，估算空间；`python3 --version`（需要 3.8 及以上）、`systemctl --version`（freeze 需要 246 及以上）、`systemctl show comfy-panel -p User,ReadWritePaths`，核对服务账户和数据路径。
2. **选定异地目标**（A 或 B）并在服务器之外准备好：建桶和只限这个桶的密钥，或在第二台机器上部署 `rest-server --append-only`。生成 restic 仓库密码，先存进管理员的密码管理器。
3. **安装 restic**：`apt-get install restic`（或从官方发布页校验签名后安装固定版本），然后 `restic version`。
4. **写入私有配置**：创建 `/etc/jt-backup/`（0700），按 `backup.env.example` 填写 `backup.env`，写入 `restic-password`，两个文件都是 root:root、0600。期间不在终端回显、不贴到聊天或工单里。
5. **初始化异地仓库**：`set -a; . /etc/jt-backup/backup.env; set +a; restic init`。只创建空仓库，不涉及生产数据。
6. **安装脚本和单元**：把 `deploy/backup/` 中的三个脚本复制到 `/usr/local/libexec/jt-backup/`，七个单元文件复制到 `/etc/systemd/system/`；运行 `systemd-analyze verify /etc/systemd/system/jt-backup*.service`，然后 `systemctl daemon-reload`。这一步不启用定时器。
7. **首次手动备份**：`systemctl start jt-backup.service`，然后查看 `journalctl -u jt-backup -n 50` 和 `status.json`。核对 `consistency` 为 `point-in-time`；`ls -l` 确认 `panel_data/membership.sqlite3-wal` 和 `-shm` 的属主仍是 `jt-panel`；面板 `/api/health` 正常。首次运行会完整复制媒体并上传，耗时较长。
8. **首次恢复演练**：先运行 `python3 /usr/local/libexec/jt-backup/jt_restore_drill.py --snapshot-dir /var/backups/jt/snapshots/<时间戳>`，再运行 `systemctl start jt-backup-drill.service`（从异地仓库恢复），两份报告都应为 `"ok": true`。
9. **告警测试**：配置 webhook、邮件或心跳之后，执行 `systemctl start jt-backup-alert@test.service`，确认告警送达且内容不含任何 URL 或密钥。
10. **决定是否启用冻结兜底**：保留 `JT_BACKUP_FREEZE_UNIT=comfy-panel.service`（推荐），或者删掉这一行，只依靠重试，失败时接受 crash-consistent。
11. **启用定时器**：`systemctl enable --now jt-backup.timer jt-backup-freshness.timer jt-backup-drill.timer`，然后用 `systemctl list-timers 'jt-backup*'` 核对下一次运行时间。
12. **一周后复查**：本地快照数量和占用、restic `snapshots` 列表、`restic check --read-data-subset=5%`，以及告警和心跳没有误报或漏报。
