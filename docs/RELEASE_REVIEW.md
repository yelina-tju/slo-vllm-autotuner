# 工程交付审查

## 2026-10-16 公开仓库准备

README 已改为问题、实现、主要结果和复现入口；收益与代价同时列出。
Git 范围与源码包统一包含 V1、独立在线准入扩展、公式资源和小型结果汇总，
排除原始请求、模型、日志、密钥及本地操作指令。原始结果与封存归档保留。

独立源码副本在 Windows / Python 3.13.13 的全新虚拟环境中通过 22 组命令检查：
105 项 V1/发布回归、217 项扩展测试（2 项平台相关跳过）、12 项 7B 控制契约、
确定性扩展 replay、两项 GPU 驱动的 help、pip check 和 15 个 Shell 语法检查。
逐文件 SHA-256、Python/JSON 语法、公开文档的相对链接也已核对。
本地验证报告为仓库同级 `work/github-publication-validation-2026-10-16.json`，
其中测试日志是合成 CPU/回环 HTTP 测试，不是新的 GPU 测量。

本次修复了旧 V1 replay 未传入新请求 ID、默认覆盖旧输出的问题；
新增回归验证 `switch -> rollback -> switch` 以及拒绝覆盖已有结果。
Windows 测试改用本机路径表示，并增加一个 80ms HTTP 夹具的末尾余量；
实验控制器、真实 GPU 运行协议、阈值和保存的统计均未改变。
Windows/Python 3.12 的粗粒度时钟不适用于这些毫秒级 HTTP 测试，
原生 Windows CPU 检查使用 Python 3.13，Linux CI 使用 Python 3.12。

GitHub Actions 工作流已准备但尚未在 GitHub 执行；未创建远程仓库或推送。
公开原始证据下载和许可证选择仍未执行。以下保留此前工程交付记录。

## 历史 V1 交付检查

本轮完成结果索引、README 状态同步、标准库离线验证入口和复现说明。没有占用云端 GPU。

验证结果：四份封存归档 SHA-256 一致；八次安全运行的现有契约全部通过；12 项 CPU 控制器契约通过；缺失归档与 `python -O` 均正确非零退出。生成的本地报告为仓库外 `../work/release-evidence-review.json`。

此前本机完整 unittest 因未安装项目和缺少 aiohttp 出现 4 个导入错误。现已在云端新建不继承 GPU 环境包的 Python 3.12 venv，完成普通 wheel 安装；独立发行副本的 102 项测试、12 项 CPU 契约、pip check、两种探针 help 和全部 Shell 语法检查通过。依赖版本保存在 environment/release-cpu-constraints.txt，与历史 GPU requirements.lock 分开。

GPU 驱动已移除 AutoDL 固定路径，支持 MODEL_PATH、VLLM_BIN、PYTHON_BIN；新增路径校验覆盖缺失模型、空格路径和无效执行文件。源码发行包按显式规则纳入代码、测试、配置、文档、环境和小型策略，不带原始请求、SSH 目录和模型。逐文件 SHA-256 清单已在独立副本验证。第一次打包自检误判造成的残缺 v1 保留但不交付；完整版本通过验证。

本轮工程收尾已完成；没有重新运行 GPU 性能实验。当前 CPU 验证依赖不是历史 GPU 性能环境，不能据此宣称重新测得相同性能。GitHub 发布和许可证选择尚未执行；交付为可审查源码包，原始证据归档独立保留。
