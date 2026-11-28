# 系统截图与录屏复采

`capture.py` 从 C01 鱼群详情逐次点击到 OCC000001 在塘记录、P01 塘口和 O1_010_06 水质记录，保存十幅对象页截图与两段无声 MP4。它调用 `capture_sphere.py` 拍摄三幅关系球界面，并从工程档案复制两幅历史版本和导出界面。`capture_support.py` 负责驱动浏览器和编码视频。每次采集会生成一份含 SHA-256 的 `取证清单.json`。

在工程根目录运行下列 PowerShell 命令。Python 环境需要能导入 `ontology-platform` 的本地服务依赖，以及 `websocket-client` 和 `imageio-ffmpeg`。浏览器使用支持 Chrome DevTools Protocol 的 Chrome 或 Chromium。

```powershell
python '交付文档/武昌鱼项目展示/制作文件/系统截图/capture.py' `
  --project 'ontology-platform' `
  --releases '<两个发布快照的上级目录>' `
  --source-zip '<固定66表合成数据ZIP的路径>' `
  --browser '<Chrome可执行文件的路径>' `
  --output '<新建采集目录的路径>'
```

`--releases` 下需要分别以 `d96f7ebf-c709-4ec0-a598-13927ef2b54e` 和 `16c6ce16-e28c-5e9c-a766-874fca309c5f` 命名的原发布目录，并保留各自的 `data/` 子目录。脚本校验源 ZIP 的 SHA-256，并以隔离的临时浏览器配置访问本机只读服务。原始输入保存在相应工程与数据归档中。重新采集时，浏览器版本和帧采样时刻可能改变新截图与视频的散列值。

逐图采集性质、源行及冻结工程链接见[截图来源与复现](../../系统截图/截图来源与复现.md)。
