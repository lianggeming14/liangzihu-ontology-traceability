# SSH 连接排查与 HTTPS 公网入口详解

更新：2026-11-19。状态：只读检查及方案说明，**尚未安装 SSH 服务或开放任何入口**。关联[总体方案](../superpowers/specs/2026-11-19-public-access-design.md)、[本机预检](public-access-preflight-20261119.md)。

## 1. SSH 方式存在，但当前缺少接收连接的服务

[使用指南](使用指南.md)里的 `ssh -N -L ...` 是端口转发方法，以目标已经具备 SSH 服务、账号和网络为前提。它不会替目标电脑安装 SSH，也不会移动数据库。

本次 2026-11-19 17:51（UTC+8）新增只读检查：

| 检查 | 实测结果 | 判断 |
|---|---|---|
| SSH 客户端 | 标准位置的 `ssh.exe` 存在 | 能发起 SSH 命令 |
| SSH 服务 | `sc.exe query sshd` 返回 1060；独立进程接口也确认不存在 | 没有注册的 `sshd` 服务 |
| SSH 服务程序 | Windows OpenSSH 和 Program Files/OpenSSH 标准位置均未见 `sshd.exe` | 当前标准服务端部署未准备好；未全盘查找便携软件 |
| 默认服务器配置 | `%ProgramData%\ssh\sshd_config` 不存在 | 没有可修改的现成默认服务配置 |
| SSH 监听 | TCP 监听列表无 22；`127.0.0.1:22` 连接返回 10061 | 本机默认 SSH 入口拒绝连接，尚未到认证阶段 |
| 已运行 SSH 程序 | 未见 ssh/sshd/plink/putty 进程 | 检查时没有由这些程序维持的隧道 |
| 本体 HTTP | `127.0.0.1:8792` 建连成功，监听仅回环 | 数据服务存在，SSH 接入缺口与数据库服务分开 |
| 默认用户认证文件 | 项目所属用户默认 `.ssh/config`、`.ssh/authorized_keys` 和系统管理员 authorized_keys 均未见 | 这些标准位置尚无配置；不排除其它用户、服务端另配 AuthorizedKeysFile 或密码认证 |

**如果你从另一台电脑连接当前电脑，已定位到的首个阻断是 SSH 服务端没有部署和监听。** 此时改数据库密码、应用 Host，或启动 `ssh-agent` 都不能代替 `sshd`。

**如果你从当前电脑连接另一台服务器，本机缺少 sshd 并不是原因**；应检查那台目标服务器。尚未取得实际失败命令、错误文字及目标方向，因此没有把本机检查推断成所有远端连接失败的结论。没有尝试登录未知服务器，也未读取私钥内容。

本机已有 Tailscale 网络连接，并不自动提供 Windows SSH 服务。Tailscale SSH 服务端当前支持 Linux、运行开源 CLI 的 macOS；Windows 可另外安装 OpenSSH Server，再使用 Tailscale 网络访问。[Tailscale 官方支持范围](https://tailscale.com/docs/features/tailscale-ssh)、[Microsoft OpenSSH 安装说明](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse)。

## 2. SSH 隧道到底连接哪里

假设这台有数据库的电脑为“服务器”，另一台是“访问电脑”：

```text
访问电脑浏览器 http://127.0.0.1:8792
  → 访问电脑上的 ssh 客户端监听 8792
  → 加密 SSH 连接到服务器的 SSH 端口
  → 服务器上的 sshd 连接该服务器自己的 127.0.0.1:8792
  → 本体网页/API → 原数据库
```

在**访问电脑**运行以下模板；账号和服务器地址必须替换，前提是服务端已安装、授权且可达：

```powershell
ssh -N -T -o ExitOnForwardFailure=yes -o ConnectTimeout=10 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 127.0.0.1:8792:127.0.0.1:8792 用户名@服务器地址
```

如果采用现有 Tailscale 网络，服务器地址填写目标电脑的 Tailscale 地址或可解析名称；两端必须获得网络策略授权。公网直接 SSH 则还需要可达的公网入站地址与网络策略，不能拿局域网地址直接用于异地连接。

这里两个 `127.0.0.1` 属于不同机器：第一个是访问端的监听地址，第二个从 SSH 服务器一侧访问。如果 sshd 在虚拟机或容器里，第二个回环也属于那个环境。`-N` 表示不启动远程命令，连接后终端保持运行是正常现象，关闭它就断开隧道。[OpenSSH 端口转发说明](https://man.openbsd.org/ssh.1)。

页面使用 HTTP 回环地址，跨机器部分仍由 SSH 加密。数据库不搬走，PostgreSQL/Fuseki 不需要开放远程端口。首次连接应通过可信渠道核对服务器指纹；不要用关闭主机校验来“修复”认证。

### 当前电脑当客户端时的端口冲突

当前电脑的 8792 已被本体服务占用。如果在它上面运行同样的 `-L ...:8792:...` 去连接另一台服务器，会发生本地监听冲突。可改为：

```powershell
ssh -N -T -o ExitOnForwardFailure=yes -o ConnectTimeout=10 -L 127.0.0.1:18792:127.0.0.1:8792 用户名@目标服务器地址
```

随后浏览器访问 `http://127.0.0.1:18792/`。**目标服务器**的本体配置还需要允许 `127.0.0.1:18792`；如使用 localhost，则另加 `localhost:18792`，保留原 8792 两项。否则 SSH 已经接通，HTTP 仍会返回 `HOST_REJECTED`。这是[当前配置](../../local_server/config.py)及[请求边界](../../local_server/http.py)的具体要求，SSH 不会重写浏览器的 Host。

正常使用相同的本地 8792 端口时，SSH 方式可保留当前 HTTP 同源规则；上一份报告指出的 HTTPS Origin 问题主要针对 HTTPS 代理入口，不能用来解释尚未连上的 SSH 端口。

## 3. SSH 修复顺序与权限检查

以下为待实施步骤，不是已完成配置。若目标就是当前 Windows 电脑，建议采用“现有 Tailscale 网络 + OpenSSH Server + 本地端口转发”：

1. 在目标准备 Windows OpenSSH Server，检查其配置语法、服务状态和监听。安装和服务注册需要相应系统权限；日常登录使用专用普通账户。
2. 两端加入获准的 Tailscale 网络，明确允许的访问设备/用户。Windows 防火墙只放行所需接口或来源的 SSH 入站；安装器可能生成的通用 SSH 规则也须核对，不能只追加窄规则却保留另一条全开放规则。
3. 在目标为实际登录用户安装公钥并检查 ACL。普通用户与 Administrators 组账户的默认 authorized_keys 位置不同；还需核对自定义授权路径及实际启用的认证方式，不能仅凭缺少某个默认文件断言账号错误。客户端 `-i` 只是选择私钥，不能代替服务端对相应公钥的授权；密码登录也要由目标服务实际允许。[Windows SSH 配置与 ACL](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-server-configuration)。
4. 验证用户的有效转发权限：`AllowTcpForwarding local` 或 `yes`，不可被 `DisableForwarding yes` 覆盖；若限制 `PermitOpen`，应含 `127.0.0.1:8792`。还需核对 Match 段与公钥上的转发限制。这种 `-L` 不要求打开 `GatewayPorts` 或 `PermitTunnel`。具体参数以目标 Windows OpenSSH 的语法/有效配置检查为准。[OpenSSH 服务配置](https://man.openbsd.org/sshd_config.5)。
5. 从真实访问电脑逐层测试：网络到 SSH 端口 → SSH 身份认证 → 本地转发监听 → HTTP 健康检查 → 页面查询/导出/授权写入。`ExitOnForwardFailure` 不替代 HTTP 后端验收。
6. 最后才配置持续运行和断线恢复。客户端的 keepalive 会检测断线，不会自动重连；SSH、本体服务和 Tailscale 各自的重启恢复都需要验证。

| 报错或现象 | 对应层次 | 下一步 |
|---|---|---|
| Connection refused / 本次 10061 | TCP 已被拒绝 | 先看目标是否有 SSH 监听；本机已确认默认入口不存在 |
| Connection timed out | 网络未建立 | 查地址、路由、Tailscale 对端与策略、防火墙；不能直接归为密码错误 |
| Permission denied (publickey/password) | 已到 SSH 认证 | 查目标用户、公钥、认证方式、ACL 与服务日志 |
| Address already in use | 客户端本地绑定 | 换空闲端口，同时处理应用 Host 白名单 |
| administratively prohibited | SSH 转发限制 | 查有效配置、Match 和公钥限制 |
| channel ... connect failed | 服务器一侧回源 | 查目标服务器自己的 127.0.0.1:8792 是否运行 |
| HTTP 403 HOST/ORIGIN | 已到本体应用 | 查浏览器 URL、Host、Origin，不改 SSH 密钥 |
| HTTP 401 上传失败 | 应用写凭据 | 查本体写 token；SSH 登录成功不赋予应用写权限 |

## 4. 第二种方式：浏览器登录公网 HTTPS 地址

第二种方案是“固定域名 + Cloudflare Access + Cloudflare Tunnel”。它为现有本体网页提供受控入口，访问者不用打开 SSH 终端，也不用安装 Tailscale 客户端。

连接建立方向和用户请求方向要分开理解：

```text
建立连接：本机 cloudflared ──主动出站──→ Cloudflare

使用网页：外地浏览器
  → https://ontology.example.com（示意域名）
  → Access 检查登录与访问名单
  → 沿已建立的隧道把请求送到本机 cloudflared
  → http://127.0.0.1:8792
  → 本体网页/API/数据库处理，再沿原路返回结果
```

本机主动连接公网入口，因此通常不要求家中/单位路由器做端口映射，也不要求本机有固定公网 IP。`cloudflared` 需要能出站连接规定的 7844 TCP/UDP；TCP 对应 HTTP/2，UDP 对应 QUIC。本次只测通了当前路由下的 TCP，不能声称真实隧道或 QUIC 已通过。本方案还启用 Access token 校验，因此连接器需要能访问对应 `<team-name>.cloudflareaccess.com` 的 TCP 443，并完成实际 HTTPS 校验；目前没有该账户域名，尚未测试。已经测通 `api.cloudflare.com:443` 不能替代这个检查。[Cloudflare 网络要求](https://developers.cloudflare.com/tunnel/configuration/)。

### 每项需要配置什么

| 组件 | 要做的配置 | 在哪里 |
|---|---|---|
| 域名 | 用户可管理的域名，规划独立子域名，保留已有 DNS 记录 | 域名/DNS 管理端 |
| Access | 先创建应用、指定允许的人和登录方式，覆盖整个域名网站及 API | Cloudflare 管理端 |
| Tunnel | 创建固定命名隧道及最小必要的连接凭据 | Cloudflare 管理端 |
| cloudflared | 在本体服务器安装连接器并用私有凭据连接；回源为 `http://127.0.0.1:8792` | 这台服务器 |
| 域名路由 | 将所选子域名关联到隧道，启用 Access token 校验，其他路由不放行 | Cloudflare / 连接器配置 |
| 应用边界 | 允许正式 Host，增加精确 HTTPS Origin，同时保留本机地址 | 本体应用配置及少量代码 |
| 持续运行 | 连接器和本体服务开机启动、失败恢复、有限日志及健康检查 | Windows 服务/任务配置 |

需要用户拥有可管理的域名和相应 Cloudflare 权限。正式固定入口不采用临时测试网址；不在未核对账户计划和使用要求前承诺免费额度或可用性。官方流程支持全 DNS 托管，也描述了部分 CNAME 接入；实际选择前检查账户支持条件。[域名、Access 和入口校验说明](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)。

Access 保护的是“谁可以进入网页和 API”；本体写 token 继续控制“谁能上传”。首次阶段登录人员中的指定管理员另持写 token。自动化客户端需要入口服务身份和应用写凭据两层授权；二者不是同一个 token。

### 本项目仍要处理的兼容问题

- 回源协议是本机 HTTP，不要把服务地址误填成 `https://127.0.0.1:8792`；当前应用没有监听 TLS。
- 不能仅添加公网域名或重写 Host：当前 Origin 规则固定为 `http://`，真实 HTTPS 页面提交仍会 403。需要精确配置可信 HTTPS Origin，不接受通配 Origin 或任意转发头。
- 保持页面和 `/api/v1/...` 同域名根路径，现有前端不适合直接挂到任意子目录。
- 上传需要 `Content-Length`，当前拒绝 `Transfer-Encoding`；实际代理需保证兼容。单次上传上限目前 64 MiB，大型整库备份走专用管理传输路径。
- 入口保护全站，API 和认证数据不缓存；连接器凭据保留本机私有存储，不进入 GitHub。[回源 Host、传输及 Access 参数](https://developers.cloudflare.com/tunnel/reference/origin-parameters/)。

数据库仍在原电脑。网页响应会经过入口传输，但这不等于把数据库完整迁到 Cloudflare。原电脑关机、断网、服务停止，网页就无法继续提供数据。以后真迁到另一台服务器，可在完成完整备份恢复和验收后切换隧道入口，访问者继续用同一个网址。

## 5. 两种入口如何选择

域名取得、DNS 接入、OTP/IdP、Access、Tunnel token、team/AUD、证书及 Windows 服务权限的完整操作顺序，见[固定 HTTPS 域名手册](https-domain-setup.md)。最新认证检查与尚未完成的权限项见[连接复核](connection-auth-audit-20261124.md)。

| 事项 | SSH + Tailscale 网络 | HTTPS + Tunnel + Access |
|---|---|---|
| 访问端 | Tailscale 客户端、SSH 连接和浏览器 | 浏览器和登录身份 |
| 服务端新增 | OpenSSH Server 和账号/公钥配置 | cloudflared、域名和 Access 配置 |
| 本体应用改动 | 同端口回环访问一般可保留；换端口要改 Host 白名单 | 必须补 HTTPS Origin 与公网 Host 兼容 |
| 授权 | tailnet 网络策略 + SSH 账号 + 应用写 token | 入口用户身份 + 应用写 token |
| 适合 | 少数管理者、个人电脑间访问和维护 | 多人日常使用、希望直接点网址 |
| 是否需要重建数据库 | 不需要 | 不需要 |
| 原电脑能否关闭 | 不能，除非另做真实服务器迁移 | 不能，除非另做真实服务器迁移 |

当前优先排查 SSH 有明确落点：若当前电脑是被访问端，先补 OpenSSH Server；若它是访问端，则需要实际目标与失败信息，且要避免本机已占用的 8792。本轮只确认现状和补充方案，未执行安装、账号变更、端口开放或公网发布。
