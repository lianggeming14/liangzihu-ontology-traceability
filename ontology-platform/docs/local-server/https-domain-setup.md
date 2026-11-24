# 固定 HTTPS 域名、登录与 Tunnel 配置手册

更新：2026-11-23。**状态：待实施操作手册；未购买域名、修改 DNS、创建云端配置、安装连接器或发布公网入口。** 本文核对了 Cloudflare 官方流程，但没有检查用户真实 Cloudflare 账户、域名、登录身份或远端设备。

本项目的公网 Host 与精确 HTTPS Origin 兼容仍需实现并验证。当前不能只按本手册填好云端设置，就宣称已经得到可用且通过验收的网址。2026-11-19 的检查属于历史证据，不表示今天服务、网络或权限仍相同。背景见[已有 SSH 与 HTTPS 说明](ssh-and-https-access.md)和[总体设计](../superpowers/specs/2026-11-19-public-access-design.md)。

以下顺序是：确定域名和权限 → 完成 DNS 接入 → 准备登录方式及 Access → 准备本机应用和连接器 → 发布受保护路由 → 验证证书和外网访问 → 验证持续运行。没有通过前一步时，应记录阻断及责任人，不把后续项目记为通过。

## 1. 先填输入，分清网址和凭据

这里使用 `example.com`、`ontology.example.com` 和 `TEAM` 作为占位，不是项目已创建的域名或账号。正式实施时替换成已核实的值。

| 要填写的输入 | 从哪里获得 | 用途与边界 |
|---|---|---|
| 根域名、注册商、现有 DNS 提供商、域名管理人 | 域名持有人或管理后台 | 判断是否能接入 Cloudflare，以及谁能处理 NS/DNSSEC |
| 正式 hostname，例如 `ontology.example.com` | 在自有域名下选择未使用的一级子域名 | 用户最终访问 `https://ontology.example.com/`；不增加 `:8792` 或 `/project/` |
| Cloudflare 账户、目标 zone、套餐与操作成员 | 用户已登录的正确账户及管理员 | 核对资源归属和权限；不需要提供密码 |
| 允许访问的邮箱或组织组、使用哪种 IdP/OTP、谁能上传 | 项目负责人和身份管理员 | Access 控制进入网站；上传另受本体写凭据控制 |
| Zero Trust team name、team domain | Zero Trust 的 Team name and domain 设置 | 例如 `TEAM` 与 `TEAM.cloudflareaccess.com`，不是业务网站域名 |
| Access 应用的 AUD、Tunnel 名称/ID | 对应 Access 应用和 Tunnel 控制台 | 记录资源对应关系；AUD 不是 Tunnel ID |
| 运行主机、Windows 服务账号、维护/重启窗口、外网验收设备 | 本机及网络管理员、验收人员 | 核对程序、私有凭据、日志 ACL 和持续运行 |

| 登录或凭据 | 谁使用、验证什么 | 不可混用的事项 |
|---|---|---|
| Cloudflare 管理账号密码/MFA | 管理员登录控制台、修改云端资源 | 不是网站访问者的共享密码，不发给网站用户 |
| 网站 IdP 登录或邮箱一次性验证码 | 被 Access 策略允许的网站访问者 | OTP 发到对应邮箱；不需要把邮箱密码交给本项目 |
| Tunnel token | 本机 `cloudflared` 连接指定 Tunnel | 不是网站登录口令；持有者可运行该 Tunnel，必须私有保存 |
| Access JWT / Access service token | 浏览器会话或获准自动化客户端的入口身份 | 不是 Tunnel token，也不代替应用写凭据 |
| 本体上传 Bearer 凭据 | 已获准上传的管理者或程序 | 登录 Access 不自动获得上传权限 |
| SSH 用户、公钥与私钥 | 备用 SSH 通道 | 与 Cloudflare 登录及数据库密码相互独立 |
| PostgreSQL 等服务凭据 | 本机受控服务进程 | 不分发给普通网页访问者；网页 403 不应通过改数据库密码处理 |

密码、私钥、Tunnel token、JWT、会话 cookie、service-token secret 和应用写凭据不得进入本文、截图、公开日志或 GitHub。用户只需提供资源名称、非秘密标识和负责人；真实秘密通过获准的本机私有存储配置。不得把带 token 的控制台安装命令粘贴进交付报告。

## 2. 域名准备：按现有条件选择分支

### 2.1 没有域名

| 项目 | 操作与判断 |
|---|---|
| 输入 | 用户决定使用新注册域名，或取得单位已有域名下一个子域名的管理授权 |
| 操作位置 | 域名注册商或现有域名管理员；本手册不执行购买、套餐升级或 DNS 变更 |
| 可见通过证据 | 域名确已注册，持有人及 DNS/NS 管理人明确；选定 hostname 不与已有业务冲突 |
| 失败定位 | 只有想用的名称、尚未注册，或只能改某条 DNS 记录但不能完成所选接入方案，均记为资源未准备好 |

Cloudflare 注册商购买的域名自动使用 Cloudflare 权威 DNS；其他注册商域名需按后续分支接入。不把价格、免费额度或采购当成已确认条件。[官方域名前置条件](https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/)。

域名未准备好时，少数管理者可继续采用[SSH + 已获准 Tailscale 网络](ssh-and-https-access.md)，先完成目标 Windows OpenSSH Server、用户公钥、转发权限与跨机验收。无域名不是 SSH 已可用的证据。Quick Tunnel 虽可生成临时 URL，且当前支持邮箱验证，但地址会变化、无可用性保证，不能作为固定网站交付。[官方 Quick Tunnel 范围](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)。

### 2.2 已有域名，已在正确 Cloudflare 账户且 Active

| 项目 | 操作与判断 |
|---|---|
| 输入 | 根域名、目标账户、已选 hostname、现有 DNS 清单 |
| 操作位置 | `Domains → 对应域名 → DNS → Records`，以及域名 Overview |
| 可见通过证据 | 目标 zone 为 Active；hostname 没有被已有 A/AAAA/CNAME 或其他业务占用；管理成员拥有对应权限 |
| 失败定位 | 选错账户、zone 仍 Pending、hostname 已占用时，先处理归属或另选名称，不删旧记录强行继续 |

不需要为了增加一个子域名重新迁移整个域名，也不修改与本项目无关的邮件、网站和验证记录。

### 2.3 已有域名，但仍在其他 DNS 提供商

| 项目 | Full setup：迁移权威 DNS 的准备流程 |
|---|---|
| 输入 | 注册商/NS 管理权限、完整原 DNS 清单、DNSSEC/DS 状态、现有业务维护窗口 |
| 操作位置 | Cloudflare `Domains → Onboard a domain` 添加根域名；原 DNS 后台核对记录；注册商后台处理 NS/DNSSEC |
| 操作顺序 | 先完整核对导入记录，再由负责管理员按获准变更计划处理 DNSSEC 和替换 NS；激活后按计划恢复 DNSSEC。此文只描述步骤，不执行切换 |
| 可见通过证据 | Cloudflare zone 为 Active；公共 NS 查询与本 zone 分配的 NS 一致；原网站、邮件及第三方域名验证仍正常 |
| 失败定位 | Pending 查注册商或父区的真实委派；SERVFAIL 查 DNSSEC/DS；漏记录查原 DNS 清单；无法获准改 NS 则不要继续此分支 |

自动扫描不保证找齐 DNS 记录。逐项保存并核对原 A/AAAA/CNAME、MX、TXT（含 SPF、DKIM、DMARC）、CAA、其他验证记录与代理状态。不要只记录本项目子域名，就切换整个根域名的 NS。旧 DNSSEC 对应的 DS 未按迁移方案处理，可能使整个域名无法解析。[官方 Full setup 与验证步骤](https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/)。

Windows 只读查询模板如下；执行前将 `example.com` 换成真实根域名。公共递归缓存可能暂时滞后，单个查询不是唯一验收证据。

```powershell
nslookup -type=ns example.com 1.1.1.1
nslookup -type=ns example.com 8.8.8.8
```

如需保留外部权威 DNS，可评估 **Partial/CNAME setup**，但该接入仅适用于 Business 或 Enterprise，并非 Free/Pro 的默认能力；不得直接升级套餐。需核对 zone 验证和证书验证步骤，发布路由后按官方要求由外部 DNS 管理员配置 `<hostname>.cdn.cloudflare.net` 的 CNAME。不能把 Full setup 的 Tunnel CNAME 写法机械套用到外部 DNS。[Partial setup 条件](https://developers.cloudflare.com/dns/zone-setups/partial-setup/)、[Access/Tunnel 的 Partial DNS 操作](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/#partial-cname-setup)。

## 3. 核对独立的管理权限

| 输入 | 操作位置 | 可见通过证据 | 失败定位 |
|---|---|---|---|
| Cloudflare 操作成员及目标账户 | `Manage Account → Members` | 具备 Access/IdP/Tunnel 所需编辑或创建能力，并具备目标 zone DNS 编辑能力 | 只读角色、错误账户或资源范围不匹配由账户管理员处理 |
| 域名管理员 | 注册商/权威 DNS 后台 | 能执行所选接入方案需要的 NS、DNSSEC、DNS 记录变更 | Cloudflare 权限不等于注册商权限；不能登录注册商时不要假定可迁移 NS |
| IdP 管理员或允许邮箱名单 | 组织 IdP 与 Zero Trust | IdP 已配置，或已批准 OTP 登录人员 | IdP 权限和 Cloudflare 角色分别核对 |
| Windows 管理员与实际运行账号 | Windows 服务及目录 ACL | 安装者可注册服务；运行账号能读程序和私有凭据、写指定日志 | 管理终端能运行不代表服务账号能运行，不给 Everyone 全权限来解决 |

常用角色组合是账户级 `Cloudflare Access`（可编辑 Access 与 Tunnel）加目标域名 `Domain DNS`；实际还需核对 IdP 与创建资源权限。`Cloudflare Zero Trust` 范围更广，不应仅为本项目默认授予。`Domain Administrator` 的账户级 Access 权限是只读，不能据角色名称误判。已有资源可采用资源范围角色，但不能假定“能编辑一个已有 Tunnel”就能创建新 Tunnel。成员授权由有相应权限的 Super Administrator 处理。[官方角色](https://developers.cloudflare.com/fundamentals/manage-members/roles/)、[成员管理](https://developers.cloudflare.com/fundamentals/manage-members/manage/)、[Tunnel 资源范围授权](https://developers.cloudflare.com/cloudflare-one/networks/connectors/granular-permissions/)。

## 4. 配好登录方式，先创建 Access 应用

| 项目 | 操作与判断 |
|---|---|
| 输入 | 正式 hostname、获准邮箱/组织组、选定 IdP 或 OTP、会话时长 |
| 操作位置 | `Zero Trust → Integrations → Identity providers`，随后 `Access controls → Applications` |
| 操作顺序 | 配置并测试 IdP；若用邮箱验证码，主动添加 `One-time PIN`。创建 `Self-hosted and private` 应用，选择 `Add public hostname`，填正式主机；不设局部路径例外，覆盖网站和 API；添加明确的 Allow 条件，选择批准的登录方式并保存 |
| 可见通过证据 | 应用、hostname、登录方式和 Allow 条件能在后台核对；未设置意外的 Bypass、Everyone 或 API 豁免；记录一名允许用户和一名不允许用户供后续验收 |
| 失败定位 | 找不到域名先查账户和 zone Active；登录失败查实际启用的 IdP、人员条件和登录日志；不要先发布无保护路由来试网页 |

新 Zero Trust 组织当前默认使用 Cloudflare 身份提供商，**OTP 不再自动加入**。若希望网站访问者使用自己的邮箱验证码，应显式添加 OTP 并在该应用启用；不要为此把网站访问者全加入 Cloudflare 管理员名单。已有组织的登录方式以后台为准。[IdP 官方说明](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/)。

OTP 只向策略允许的邮箱发送；页面显示“已发送”不能证明实际投递。失败时先检查邮箱与 Allow 条件，再检查垃圾箱或邮件网关；验证码单次使用，重新请求会令旧码失效。邮箱密码无需交给本项目。若策略依赖组织组，不要随意启用 OTP 作为替代，因为 OTP 登录不会提供该 IdP 的组成员信息。[OTP 设置与排错](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/)。

**Access 应用必须先于公网路由发布。** 未匹配 Allow 的访问默认拒绝；要核对已有更具体应用或路径例外，防止站点根路径受保护而 API 被漏掉。[官方发布顺序](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)。

## 5. 准备本机应用和网络，再创建远程管理 Tunnel

### 5.1 本项目待实现项

| 输入 | 操作位置 | 可见通过证据 | 失败定位 |
|---|---|---|---|
| 正式 hostname 和完整 `https://hostname` Origin | 本体应用配置及 HTTP 边界实现 | 精确允许公网 Host/Origin，同时保留 `127.0.0.1:8792`、`localhost:8792` 及原本机 HTTP Origin；恶意 Host/Origin 仍拒绝 | 当前仅增加 Host 无法解决固定 `http://` 的 Origin 规则；需要实现与测试，不能删校验或允许通配 Origin |
| 仍使用同机 `127.0.0.1:8792` | 本体服务器 | 当前 `/health`、`/ready`、状态接口和页面正常；数据库状态独立核对 | 先处理本机故障，再接公网；历史 200 不代表当前通过 |
| 合成上传数据与写权限 | 实际 HTTPS 代理路径 | Content-Length、大小限制、写 token 与回读正确 | 当前上传上限 64 MiB，拒绝 Transfer-Encoding；配置 `disableChunkedEncoding` 也不能代替真实上传验证 |

前端与 API 使用同域名根路径；不把网站随意挂在 `/project/`。保持 SQL、Fuseki 和应用监听边界，不能为了让隧道工作而改成全网监听。应用边界和上传约束见[既有设计](../superpowers/specs/2026-11-19-public-access-design.md)。

### 5.2 网络与 connector 身份

| 项目 | 操作与判断 |
|---|---|
| 输入 | 实际主机、当前网络路由/出口、team domain、已批准的 cloudflared 版本 |
| 操作位置 | 本体服务器和网络管理员；Cloudflare `Networking → Tunnels → Create a tunnel` |
| 操作顺序 | 检查 DNS 和官方要求的出站连接；创建命名 Tunnel，选择 Windows，使用该账户控制台生成的安装/运行指令。此手册采用 **remotely-managed Tunnel**，路由在云端维护 |
| 可见通过证据 | 本机 cloudflared 已运行；控制台出现本主机 connector，Tunnel 为 Healthy；本机回源单独通过 |
| 失败定位 | Inactive 查是否运行过 connector；Down 查服务/主机/出口；Degraded 查具体连接日志；不能把受限工具的权限错误直接判定为单位防火墙封禁 |

连接器向 Cloudflare 出站使用 7844：TCP 对应 HTTP/2，UDP 对应 QUIC。启用 Access JWT 校验还需要访问真实 `<team-name>.cloudflareaccess.com:443` 并成功完成 HTTPS 验证。`api.cloudflare.com:443` 通过不能替代该地址；TCP 探测通过也不证明 UDP、TLS、公钥获取或完整 Tunnel 通过。若采用 HTTP/2，记录实际协议；不得把仅 TCP 通过记作 QUIC 通过。[官方网络要求](https://developers.cloudflare.com/tunnel/configuration/)、[Tunnel 创建流程](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)。

远程管理 Tunnel 只需该 Tunnel 的 token 运行；不要套用 locally-managed 教程去复制账户 `cert.pem`、`<UUID>.json` 或个人目录 `config.yml`。token 泄露时应由管理员轮换并按官方流程清理既有连接，不能仅删除聊天文本就视为解决。[Tunnel token](https://developers.cloudflare.com/tunnel/reference/tunnel-tokens/)。

## 6. 添加受保护路由并校验 team/AUD

| 项目 | 操作与判断 |
|---|---|
| 输入 | 正式 hostname、已创建 Access 应用的 AUD、正确 team name、健康 Tunnel |
| 操作位置 | `Networking → Tunnels → 对应 Tunnel → Routes → Add route → Published application` |
| 路由值 | hostname 填正式子域名；Service URL 填 `http://127.0.0.1:8792`；覆盖根路径及所有 API；在 Additional application settings 开启 `Protect with Access` 并对应正确应用 |
| 可见通过证据 | 后台路由和 JWT 校验已保存并生效；Access 未授权访问无法取得业务页面/API；授权身份可继续到达应用 |
| 失败定位 | 502 查回源地址/协议/端口；登录后仍被 connector 拒绝，查 team、AUD、公钥 HTTPS 连接与系统时钟；不通过关闭 Protect with Access 来交付 |

参数来源须分开记录：

- **teamName**：Zero Trust 的 Team name and domain 设置中的名称，例如 `TEAM`，不带 `https://` 或 `.cloudflareaccess.com`。界面入口名称可能调整，以账户中的该设置为准。[team domain 说明](https://developers.cloudflare.com/cloudflare-one/faq/getting-started-faq/)。
- **AUD**：`Access controls → Applications → 对应应用 → Edit → Additional settings → Application Audience (AUD) Tag`。不是 Tunnel ID、应用 ID 或 Tunnel token；删除重建 Access 应用后要重新核对。[AUD 来源和 JWT 验证](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)。
- **Protect with Access**：要求 connector 验证 `Cf-Access-Jwt-Assertion`，配置概念为 `required=true`、正确 `teamName` 和该应用的 `audTag`。本流程在云端路由保存，不能只新建本地 YAML 就假定远程配置已更新。验证涉及签名、issuer、audience 与有效期，不是只看请求头是否存在。[Origin/Access 参数](https://developers.cloudflare.com/tunnel/reference/origin-parameters/)。

不要把回源填为 `https://127.0.0.1:8792`：现有应用没有在该端口提供 TLS。`127.0.0.1` 属于 connector 所在环境；若 connector 改放容器、虚拟机或另一台主机，应重新确定可达回源，不能照抄同机地址。HTTP Host Header 的改写仅影响 Host，不能替代本项目 HTTPS Origin 修复。

Full setup 添加路由通常会创建关联 DNS；仍要在 DNS 后台核对 hostname 对应正确 Tunnel 及代理状态。若已有同名记录，先确认业务归属，不能自动覆盖。代理 DNS 查询可能返回 Cloudflare A/AAAA，因此不把“公共查询必须看到 CNAME”当作唯一通过标准。

## 7. 验证边缘证书和真实浏览器访问

| 项目 | 操作与判断 |
|---|---|
| 输入 | 正式 hostname、Active zone、对应 Tunnel 路由、允许/拒绝测试身份、真实外网设备 |
| 操作位置 | 域名 `SSL/TLS → Edge Certificates`；外网设备的干净浏览器会话 |
| 可见通过证据 | 覆盖正式 hostname 的证书为 Active；浏览器 TLS 无错误；未登录出现认证或拒绝，允许身份能访问页面/API，拒绝身份读不到数据 |
| 失败定位 | DNS 错误先查 DNS；证书错误查激活/覆盖/代理；Access 拒绝查身份与策略；应用 403 查 Host/Origin，各层分别记录 |

Full setup 的 Universal SSL 默认覆盖根域名及一级子域名，激活可能需要 15 分钟至 24 小时。深层子域名不能假定被覆盖；不要未经确认购买高级证书。Partial setup 还需核对其域名控制验证。证书只在代理流量上呈现；DNS Active、证书 Active、Tunnel Healthy 是三个独立条件。[官方证书激活](https://developers.cloudflare.com/ssl/edge-certificates/universal-ssl/enable-universal-ssl/)、[覆盖限制](https://developers.cloudflare.com/ssl/edge-certificates/universal-ssl/limitations/)。

这里的 TLS 证书是浏览器到 Cloudflare 的 HTTPS；同机 connector 到 `127.0.0.1:8792` 使用 HTTP。不要为消除浏览器证书错误修改数据库密码、打开本机数据库公网端口，或关闭 TLS 校验。

## 8. Windows 服务权限与持续运行

| 项目 | 操作与判断 |
|---|---|
| 输入 | 已通过前台/连接验收的版本、实际 Windows 服务账号、私有凭据位置、日志目录、维护窗口 |
| 操作位置 | 管理员执行该 Tunnel 控制台给出的 Windows 服务安装指令；Windows 服务管理和目录 ACL |
| 可见通过证据 | cloudflared 服务 Running，启动方式和失败恢复明确；实际账号可读程序/凭据、写指定日志；注销、重启、断网恢复后重新通过远端测试 |
| 失败定位 | 终端可用但服务失败时查账号、ACL、绝对路径和网络差异；不要复制整个个人配置目录或授予 Everyone 全权限 |

安装服务需要相应系统权限，日常应用进程仍按既定最小权限运行。cloudflared 的身份和本体 API/worker 的身份分别核对。服务参数在 Windows 服务配置中生效；本地管理教程的 `config.yml` 不能作为远程管理路由已经配置的证据。[官方远程运行参数及 Windows 服务配置](https://developers.cloudflare.com/tunnel/reference/run-parameters/)。

只读核对服务身份时可使用以下命令，不打印含秘密的完整命令行：

```powershell
Get-CimInstance Win32_Service -Filter "Name='cloudflared'" |
    Select-Object Name, StartName, StartMode, State
```

不要把 `PathName`、注册表 `ImagePath`、`sc.exe qc` 或进程完整命令行原样放入日志/报告；控制台安装方法可能把 token 放进启动参数。如选用 `--token-file`，cloudflared 需为 2025.4.0 或更新版本，文件应在仓库之外的私有位置，且实际服务账号可读；采用前须核对该版本和服务启动参数。文件权限不能仅按当前交互用户测试。

日志需限定大小与保留周期，避免日常 debug 记录暴露请求资料；Windows 上不要假定 cloudflared 自带自动升级已经工作。连接器、本体服务、数据库各自的开机启动、失败恢复和健康检查须有独立证据。仅配置自动启动或看到服务 Running，不能代替真实重启验收。

## 9. 按错误发生层排查

| 可见现象 | 所在层及下一步 |
|---|---|
| NXDOMAIN、SERVFAIL、zone Pending | 查域名拼写、权威 NS、DNSSEC/DS、DNS 记录及缓存；尚未到网站登录层。[DNS 排错](https://developers.cloudflare.com/dns/troubleshooting/dns-issues/) |
| 浏览器证书错误、VERSION_OR_CIPHER_MISMATCH | 查边缘证书 Active、hostname 覆盖与代理状态，不忽略证书错误验收。[TLS 排错](https://developers.cloudflare.com/ssl/troubleshooting/version-cipher-mismatch/) |
| Access 拒绝、循环登录、收不到 OTP | 查实际 IdP/OTP、邮箱/组条件、应用范围和登录日志；注意提示已发码不等于投递成功 |
| 1033 | Cloudflare 找不到健康 connector；查 Windows 服务、网络及 DNS 是否指向正确 Tunnel。[1033](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1033/) |
| Tunnel 返回 502，提示 Unable to reach the origin service | Tunnel 已接入，但 connector 到回源异常；查 `http://127.0.0.1:8792`、本机监听、协议及 connector 所在环境。[Tunnel 排错](https://developers.cloudflare.com/tunnel/troubleshooting/) |
| 登录成功后仍被 connector 拒绝 | 查 Protect with Access、team/AUD、JWT 验证、公钥获取和时钟；区分于应用自身 403 |
| 应用 `403 HOST_REJECTED` 或 Origin 拒绝 | 已到本体 HTTP；查正式 Host 与精确 HTTPS Origin，不修改 SSH/数据库凭据 |
| 应用上传 401、长度/大小错误 | 分别查应用写 Bearer、Content-Length、Transfer-Encoding、64 MiB 限制，不通过放宽 Access 解决 |
| 页面正常但查询/任务失败，或 `/ready` 不通过 | 查本体 API、worker、PostgreSQL、Fuseki 和发布状态；Tunnel Healthy 不能证明后端健康 |

## 10. 交付时填写证据，不预填通过

当前以上云端配置、实际域名、Windows connector 和跨设备步骤均未由本文执行。实施者应逐项填写状态与可复核证据，保留未通过的原因。

| 验收项 | 状态填写要求 | 证据要求 |
|---|---|---|
| 域名、NS、原 DNS 业务 | 通过 / 失败 / 跳过及原因 | 实际 hostname、zone 状态、NS 查询、既有业务核对结果 |
| 权限与登录 | 通过 / 失败 / 跳过及原因 | 资源范围、允许/拒绝身份结果；秘密和人员信息按需脱敏 |
| DNS、TLS、Tunnel 与 JWT | 分别填写，不能合并成一个通过 | 证书覆盖/Active、Tunnel 状态、路由及入口拒绝结果 |
| Host/Origin、页面和 API | 通过 / 失败 / 跳过及原因 | 允许请求成功，恶意或未授权请求被拒绝，真实外网客户端验证 |
| 查询/导出/授权上传 | 分别填写 | 数据性质、合成批次标识、写入/任务/回读结果；不得污染业务数据 |
| 重启、注销、断网恢复 | 分别填写 | 时间、主机、服务账号与恢复后的真实访问结果 |

本地单元测试、合成请求、SQLite、真实 PostgreSQL、真实外网浏览器须明确区分。仅在相应步骤具备证据后，才把正式网址交付为“已验收可用”；如尚缺域名、账户权限、应用实现或现场测试，交付状态应明确写为待完成，不能用占位网址代替。
