# 本地复核与 GPU 复现

## 不占 GPU 的证据复核

Python 3.11+，只使用标准库。在仓库根目录运行：

```bash
python scripts/verify_release_evidence.py --archives ../work
```

需要四份已封存归档：`experiment017-final-evidence.tar.gz`、`fault7b-healthy-evidence.tar.gz`、`fault7b-delay-evidence.tar.gz`、`fault7b-restart-evidence.tar.gz`。脚本先验证固定 SHA-256，再在临时目录读取 JSON，复核八个安全运行的现有契约。不会启动模型、连接服务器或执行归档里的代码。缺少文件、哈希不符或契约失败均以非零状态退出。禁止 `python -O`，因为旧审计器使用 assert。

可加 `--output <新报告.json>`；已有报告不会被覆盖。归档目前为本地交付，尚无公开下载地址；单独克隆源码不等于获得完整原始证据。此入口对 017 只验证归档完整性，完整统计重算用已有 `scripts/summarize_experiment017_final.py`，需在独立副本中放好四个 final seed 目录后运行，避免覆盖保存的汇总。

## 代码检查

公开仓库包含 V1 和独立扩展的代码、测试及小型策略输入。Linux 使用 Python 3.12，
Windows 原生 CPU 检查使用 Python 3.13，
先创建并激活独立虚拟环境，再在仓库根目录运行：

```bash
python -m pip install -c environment/release-cpu-constraints.txt .
python -m unittest discover -s tests -q
python scripts/check_7b_fault_contract.py
python -m unittest discover -s extensions/online_admission -p "test_*.py" -q
python extensions/online_admission/replay.py
```

上述 constraints 是 Python 3.12 独立 CPU 验证版本，不能用来替换历史 vLLM 环境。发行 ZIP 解包后可运行 `python scripts/validate_source_release.py --root . --output <新报告.json>` 检查清单、测试、依赖和 Bash 语法。

同一组约束也用于本次 Windows/Python 3.13 CPU 检查。Windows/Python 3.12 的
`monotonic` 时钟在本机分辨率为 15.625ms，会影响 5–40ms 的 HTTP 测试夹具；
不能据此解释 Linux 上的 GPU 性能。原生 Windows 不用于本项目的 GPU 生命周期复现。

Windows 若没有把 Bash 加入 PATH，可加 `--bash "C:/Program Files/Git/bin/bash.exe"`
（以实际 Git for Windows 安装位置为准）。缺少工具或命令超时会记录为失败，保留其他检查结果。

单元/本地 HTTP 测试和确定性 replay 不需要 GPU、模型或 `../work`。
完整原始证据复核需要本地归档，不能把单元测试通过解释为重新测得 GPU 性能。
扩展原始证据复核入口为：

```bash
python extensions/online_admission/recheck_guarded_evidence.py --work ../work
```

该入口需要扩展的五份归档、两份冻结协议及对应解包目录，具体文件名与哈希在
脚本的 `ARCHIVES` 中。当前公开源码不包含它们，也没有公开下载地址。

## GPU 复现顺序

真实运行需要 Linux、支持当前 vLLM 构建的 NVIDIA 驱动、足够显存与本地模型。已验证设备为单张 24GB 4090D；不保证其它组合直接兼容。

1. 按 `environment/` 和 `scripts/serve.sh` 核对运行环境与模型路径。
2. 阅读 017 预注册协议、容量扩展说明；依次执行 calibration、capacity、capacity extension、final 对应脚本。种子分组和 SLO 冻结规则见原协议。
3. 审查 final 结果后再执行 `run_7b_fault_pairs.py` 健康 seed130、故障 seed131/132。
4. GPU 空闲时依次运行 `run_7b_restart_probe.py` 和 `--fail-target`，然后用 `audit_7b_restart_probe.py` 审查。

驱动从脚本位置确定仓库根目录；通过以下环境变量指定机器环境：

```bash
export MODEL_PATH=/path/to/Qwen2.5-7B-Instruct
export VLLM_BIN=/path/to/vllm-env/bin/vllm
export PYTHON_BIN=/path/to/vllm-env/bin/python
```

1.5B 实验需将 MODEL_PATH 改为对应模型。Python 故障驱动提前验证模型目录和 vLLM 可执行文件；模型下载器可使用 `--destination` 或 MODEL_PATH。使用独立仓库副本与全新输出目录，保留原始结果、失败尝试和代码版本。只读离线审计可重复执行，GPU 驱动不要无检查重复运行。

## 公开仓库交付边界

运行 `python scripts/check_publication.py` 检查 Git 的待发布文件范围、大小和敏感信息标记；
运行 `python scripts/build_source_release.py <新的发行包.zip>` 生成当前源码评审包。
包含 V1、独立在线准入扩展、测试、配置、实验文档及公式资源、环境记录、汇总结果和小型策略输入，
不包含模型、SSH 密钥、运行日志或原始请求。SOURCE_MANIFEST.json 记录包内文件哈希。
实验文档仍含原始运行路径以便溯源。当前未执行 GitHub 发布或许可证选择；完整原始证据归档独立保存。
详见 [PUBLICATION.md](PUBLICATION.md)。
