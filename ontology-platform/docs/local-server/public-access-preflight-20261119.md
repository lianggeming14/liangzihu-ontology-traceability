# 公网访问本机预检记录（2026-11-19）

关联：[公网访问与迁移方案](../superpowers/specs/2026-11-19-public-access-design.md)。本记录为脱敏公开摘要，省略真实设备名、账号、网络地址、私有目录与凭据。只读诊断没有改变监听、防火墙、身份认证或业务数据。

结论：**现有服务可作为隧道后端；当前配置尚不能直接完成受保护的公网 HTTPS 访问。** 已确认 Host/Origin 兼容性、读权限和启动恢复方面需要补齐；不能只通过改端口或提升管理员权限解决。

## 1. 本机应用与网络实测

本机应用及出站 TCP 复核时间：2026-11-19 15:09（UTC+8）。本机查询使用真实运行服务，但不是整库完整性检查。

| 检查 | 结果 | 证据和解释 |
|---|---|---|
| 配置加载 | 通过 | 正式部署配置能够加载；写 token 已配置，只检查是否存在，未输出值 |
| 进程归属与状态 | 通过 | supervisor、HTTP、worker 均存活；受管 PostgreSQL/Fuseki 状态 running |
| HTTP 存活 | 通过 | `GET /health` → 200 `alive` |
| 发布就绪 | 通过（有限范围） | `GET /ready` → 200 `ready`；不代表 SQL/RDF/文件全量一致性已重新验收 |
| 状态 API | 通过 | `GET /api/v1/status` → 200 |
| 当前发布 | 已确认 | `16c6ce16-e28c-5e9c-a766-874fca309c5f` |
| HTTP 绑定 | 已确认 | `127.0.0.1:8792`；适合同机代理，不能直接从另一台电脑用主机 IP 访问 |
| SQL/Fuseki 配置目标 | 已确认 | 本机回环目标，端口分别 25459/23059；没有因本次检查开放它们 |
| 公网 Host 兼容性 | 未满足 | 本机实发 `Host: ontology.example.com` → 403 `HOST_REJECTED`；这是占位测试域名，未创建公网 DNS |
| 自动启动 | 未满足 | 生命周期状态返回 `automatic_boot=not-installed`，没有通过重启恢复验收 |
| Tunnel 区域 1 TCP 7844 | 通过 TCP 建连 | `region1.v2.argotunnel.com`，约 218 ms |
| Tunnel 区域 2 TCP 7844 | 通过 TCP 建连 | `region2.v2.argotunnel.com`，约 218 ms |
| Cloudflare API TCP 443 | 通过 TCP 建连 | `api.cloudflare.com`，约 828 ms |
| GitHub TCP 443 | 通过 TCP 建连 | `github.com`，约 1968 ms |

出站探测只建立 TCP 连接后关闭，没有发送业务数据。上述延迟是单次连接测量，包含解析及连接开销，不是稳定 RTT、吞吐或服务 SLA。没有完成 Cloudflare Tunnel 的 TLS/HTTP2/QUIC 会话、账户授权或公网入口访问。后续确认本机选用了 Tailscale exit node，故上述结果仅代表当前路由条件，不证明关闭该出口后的物理网络仍可连通。

同样的出站命令在工具沙箱内第一次均返回 `PermissionError / WinError 10013`，申请沙箱外只读执行后成功。这证明首次失败受到执行环境限制，不能据此认定主机没有公网或防火墙必须关闭。DNS/端口连通也不等于登录授权通过。

## 2. 应用边界核查

证据为当前 [HTTP 源码](../../local_server/http.py) 和配置源码，以及从现有 `boundary()` 提取并执行的 **8 组合成内存请求**。没有向数据库写入；合成 token 不是真实凭据。这些结果不替代浏览器及真实隧道验收。

| 合成场景 | 当前结果 |
|---|---|
| 默认配置，公网 Host | 403 `HOST_REJECTED` |
| 将公网 Host 加入合成配置，GET 无 Origin | 通过请求边界 |
| 已允许公网 Host，HTTPS Origin 的 POST | 403 `ORIGIN_REJECTED` |
| 仅将 Host 重写成本机地址，仍有 HTTPS Origin | 403 `ORIGIN_REJECTED` |
| 额外加入 `X-Forwarded-Proto: https` | 仍为 403 `ORIGIN_REJECTED` |
| HTTP 同源 + 正确的合成写 token | 通过请求边界 |
| 无写 token | 401 `UNAUTHORIZED` |
| 无 Origin + 正确的合成写 token | 通过请求边界 |

`local_server/http.py:96–110` 精确校验 Host、Origin 和写凭据；`do_GET` 不要求读认证，`do_POST` 上传要求 Bearer。当前应用本身不终止 TLS，不读取代理转发头。前端绝对路径和无 CORS 放行决定了优先采用独立域名、页面与 API 同源。

需要补齐的内容：明确公网 Host 与 HTTPS Origin 配置、入口全站身份认证、代理上传长度兼容、限流及持续运行。本机健康检查仍需要原本机 Host，不能只留下公网域名。

上传当前为 64 MiB 上限，必须提供 `Content-Length`，拒绝 `Transfer-Encoding`，读取 socket 超时默认 15 秒。网页导出只覆盖公开标准化数据，不包含完整私有备份。

## 3. Windows 与连接软件检查

| 检查 | 已取得结果 | 对方案的影响 |
|---|---|---|
| 系统 | Windows 11 专业版 25H2，64 位 | 已有本机组件运行基础；跨系统另验 |
| 当前执行权限 | 沙箱内执行令牌非提升；未单独测沙箱外令牌 | 普通只读检查可进行；安装服务等操作需相应系统权限 |
| 磁盘 | C 盘总量约 636.8 GiB，可用约 63.1 GiB | 仍需按完整数据、备份和 staging 实际占用预算；不能仅凭余量保证恢复足够 |
| OpenSSH | 客户端 9.5p2 在 PATH；未发现 sshd 服务或标准路径中的服务器程序 | 本机可主动连接，但不能因此接收外部 SSH 登录 |
| SSH 相关服务 | `ssh-agent` 停止且 Disabled | 不等于所有 SSH 公钥连接都会失败；显式指定私钥仍需实际目标验证 |
| Tailscale | 客户端 1.104.6，服务 Running / Automatic，有启动项；BackendState Running，SelfOnline true | 已连接，可优先考虑复用；真实应用访问与策略仍需验收 |
| Tailscale 对端与健康 | 状态中 5 个 peer，1 个在线；Health 消息 0 | 不公布设备信息；在线不等于授权访问本体网页，也未验证该对端是目标使用设备 |
| Tailscale 出口 | `ExitNodeStatus` 非空，已选用出口节点 | 影响网络探测路径；没有关闭出口或更改路由 |
| Tailscale 默认转发 | `serve status --json`、`funnel status --json` 均为空 | 默认节点级入口没有已声明的转发；没有设置本体网页的 Serve/Funnel 规则；未另行盘点 Tailscale Services 的独立配置 |
| 其它命令 | PATH 与服务列表未检出 `cloudflared`、`frpc`、`frps`、`docker`；标准位置未见 Cloudflared/Docker Desktop | 不能直接照抄依赖这些命令的部署步骤；未做全盘便携软件盘点 |
| 网络接口 | 已见私网 IPv4、共享地址段和 ULA IPv6 接口；未见 Preferred 状态公网地址 | 不等于证实上游 CGNAT；无法由此确认运营商入站条件或 exit node 状态 |
| Windows 防火墙 | BFE、mpssvc 运行；Domain/Private/Public 均启用 | 读取层默认动作显示 NotConfigured；未验证有效规则，不能断言某端口被系统封禁 |
| 代理 | 用户代理关闭，无 PAC；WinHTTP 直接访问；常见代理环境变量未设置 | 本次 TCP 探测不依赖已配置的 HTTP 代理 |
| 启动任务筛查 | 相关任务/动作关键词未命中；相关启动命令只命中 Tailscale | 与应用 not-installed 状态一致，但不排除间接调用的通用启动器 |
| 交流电源 | 睡眠、休眠计时均为 0（从不） | 有利于持续运行，不能替代注销、重启和断电测试 |
| 电池电源 | 睡眠计时 600 秒 | 若设备实际进入电池供电，需要纳入持续服务策略 |

CIM 网络、防火墙与计划任务查询首次遇到受限环境拒绝 `0x80041003`，沙箱外只读重试取得了上述摘要。没有修改电源方案、防火墙或系统服务。内存余量、数据库实时文件总尺寸和有效防火墙规则未完成测量，不能据此给出云主机规格或全链路通行结论。

Tailscale 的 `status --json` 首次因沙箱无法访问本地管理管道而失败；沙箱外只读复核取得了上述状态。只输出状态和数量，未披露真实账号、设备名、地址或配置原文。没有运行会改变状态的 `up`、`serve <target>`、`funnel <target>` 或登录命令。tailnet 策略权限、客户端之间的实际连通和网页授权仍未验证。

## 4. 仍然没有验收的条件

| 条件 | 状态 | 原因或下一步 |
|---|---|---|
| 用户之前的失败过程 | 待提供 | 尚无失败命令、时间及错误文字；不能将当前障碍等同于全部历史根因 |
| 域名、入口账户及访问名单 | 待确认 | 未创建 DNS/Tunnel/Access；不假设拥有云端管理权限 |
| Windows 服务安装权限 | 未执行安装 | 此轮为只读检查；实际服务账户与私有目录 ACL 需在实施时验证 |
| Cloudflare TLS/HTTP2/QUIC | 跳过 | 无连接器会话及账户授权；TCP 7844 成功只通过网络前置条件 |
| 真实外网浏览器 | 跳过 | 尚无公布的入口和受测外网客户端 |
| 外网授权/未授权读写 | 跳过 | 本轮没有创建公开入口或写入业务数据 |
| 上传代理与大文件 | 跳过 | 未建立代理；需要小型合成批次、长度与慢连接验收 |
| 注销、重启、断网恢复 | 跳过 | 没有改变或重启现有服务 |
| 新主机恢复与切换 | 跳过 | 未选定目标；不能以历史同机恢复或 SQLite 测试替代 |
| 本轮完整备份 | 未执行 | 未停止写入或生成新备份；实际迁移前必须包含最新 CAD/GIS 与完整资产 |

本机基础条件与公网最终可用性应分别判断。最终仍需要用户明确访问方式及目标资源，再依方案逐阶段实施和验收。
