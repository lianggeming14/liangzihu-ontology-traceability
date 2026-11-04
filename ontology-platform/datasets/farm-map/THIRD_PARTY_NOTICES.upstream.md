# 第三方来源与许可

本发布保留每项来源原有条款，不为整个合并工程擅自添加统一开源许可证。

- **Three.js**：MIT；原文见 `licenses/three-MIT.txt`。依赖版本由 `package-lock.json` 固定。
- **Poly Haven PBR / Tree Small 02 枝叶纹理**：CC0；素材作者、下载链接、文件哈希与使用范围见 `public/focus/ASSET-SOURCES.md`、`public/focus/textures/foliage/source-manifest.json`。
- **本体与语义样例**：锁定上游提交 `5776ba8d656139d3fb8dfabd137d83dd6dbba11c` 的有限本体、SHACL、profile 和 fixtures，保留 `backend/ontology` 与 `deliverables/liangzihu-samples` 的来源记录及原有许可文件。适配后端为本项目实现，没有引入上游前端。上游未见独立项目级许可证的部分不被重新标注为 MIT；具体范围见 `docs/audit/ontology-audit.md`。
- **Qwen3 GGUF 与 llama.cpp**：Apache-2.0 / MIT；发布包不包含模型权重和运行时二进制，下载脚本保留固定版本、校验及许可说明，见 `docs/audit/local-model-assets.json`。
- **现场图纸、台账、照片和卫星截图**：保留用户提供的原始文件及来源哈希；它们不因本次发布而自动获得第三方素材的 CC0/MIT 授权。

其他 Python / Node 依赖按 `requirements.txt`、`package-lock.json` 安装，各自许可证随相应发行包提供。
