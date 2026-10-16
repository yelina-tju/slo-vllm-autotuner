# Experiment 017 预注册：Qwen2.5-7B 模型规模泛化

## 1. 目标与声明边界

本实验检验在 Qwen2.5-1.5B 上建立的 SLO-aware serving 方法，经过模型专属校准后，能否迁移到 Qwen2.5-7B-Instruct。

允许的结论是“跨 1.5B 到 7B 参数规模的机制泛化”；由于两个模型属于同一系列，本实验不用于宣称跨模型架构泛化。

预先固定以下原则：

1. 不把 1.5B 的毫秒 SLO 和 24/3 req/s 容量直接复制给 7B；
2. calibration seed 与 final evaluation seed 完全分离；
3. 最终 seed 开始后不再修改 SLO、容量、canary 阶段或控制器参数；
4. 无论结果是否提升 goodput，都保留完整结果并报告失败模式；
5. 模型身份、配置文件哈希、权重文件名和总字节数写入 trace manifest。

## 2. 硬件与模型

- GPU：单张 RTX 4090 D 24GB；
- 推理框架：与主实验相同的 vLLM 环境；
- 模型：`Qwen/Qwen2.5-7B-Instruct`；
- 精度：FP16；
- 最大上下文：4096；
- prefix cache：关闭；
- workload shape：256/64 short 与 2048/64 long。

如果 7B FP16 在既定显存上无法以相同上下文稳定启动，则记录不可行证据，不静默切换量化版本。量化模型只能作为独立的后续实验条件。

## 3. 模型专属 SLO 校准

在低负载 1 req/s 下，用三个 calibration seed 分别测量 short 与 long 类的 P99 TTFT 和 P99 E2E。令低负载第 \(s\) 个 seed 的分位数为 \(Q^{m}_{0,c,s}\)，其中 \(m\in\{\mathrm{TTFT},\mathrm{E2E}\}\)。

SLO 在看到容量搜索结果前固定为：

$$
S_c^{\mathrm{TTFT}}
=3.0\max_s Q^{\mathrm{TTFT}}_{0,c,s},
\qquad
S_c^{\mathrm{E2E}}
=1.4\max_s Q^{\mathrm{E2E}}_{0,c,s}.
$$

系数 3.0 与 1.4 近似复现 1.5B 首轮实验中 `100/31.33` 和 `400/288.50` 的归一化服务余量；它们在观察 7B 容量结果前冻结。

## 4. 容量与 policy catalog 校准

候选服务器环境为 `mbt1024/seq256/FCFS` 与 `mbt2048/seq256/FCFS`。对 balanced 与 mixed workload 在预定 rate grid 上运行三个 calibration seed。

设 \(I_{w,e,r,s}=1\) 表示 workload \(w\)、环境 \(e\)、速率 \(r\)、seed \(s\) 同时满足所有类别 SLO。稳健容量定义为：

$$
C_{w,e}
=\max\left\{
r:\sum_{s=1}^{3}I_{w,e,r,s}=3
\right\}.
$$

先比较稳健容量，再以最差归一化 E2E headroom 打破平局。若没有候选在最低 rate 上通过，则停止 adaptive benchmark，不人为放宽 SLO。

若候选在基础网格最高点仍为 3/3 通过，则该点只构成容量下界，不把网格上界误写成精确容量。此时按[容量搜索右删失修正](experiment-017-capacity-extension.md)执行预注册扩展：只扩展右删失候选，并使用与基础搜索、最终评估均不重叠的新 seed。

## 5. Canary 阶段迁移

令校准得到的 mixed 安全容量为 \(C_L\)，兼容 balanced 高容量为 \(C_H\)。7B canary 不复用 1.5B 的绝对 `8/16`，而按容量区间生成：

$$
C_1=C_L+\frac{C_H-C_L}{3},
\qquad
C_2=C_L+\frac{2(C_H-C_L)}{3}.
$$

阶段值按 0.5 req/s 网格向下取整，并要求：

$$
C_L<C_1<C_2<C_H.
$$

每级仍需两个包含新成功请求 ID 的 SLO-pass 窗口；两个带新违规 ID 的窗口回退到上一个已验证阶段。

## 6. 最终 evaluation

使用未参与任何选择的四个 final seed。四种模式采用循环执行顺序，使每种模式恰好在第 1–4 位运行一次：

1. `static_aggressive`；
2. `oracle_boundary`；
3. `binary_recovery`；
4. `canary_recovery`。

balanced 到达率设为其稳健容量的约三分之二；mixed 到达率设为 mixed 安全容量的两倍，沿用主实验的相对压力结构。每个 seed 内四种模式复用完全相同的开放环 trace。

主要指标：SLO goodput、合规请求数、HTTP 429/503、completed-but-late、tail-violation area、模型重启次数、mixed 检测延迟、首次 balanced 恢复延迟和满容量恢复延迟。

## 7. 泛化成功标准

本实验不要求 7B 上 canary 的 goodput 必然高于 binary。满足以下条件即可支持机制泛化：

- 每个 seed 的四种模式请求轨迹与 payload hash 完全一致；
- adaptive 模式没有 control error，终态服务可恢复；
- binary 与 canary 均能完成 workload shift、重启和 compatible recovery；
- canary 恢复不增加模型重启次数；
- canary 的正常路径恢复成本和受控故障暴露均可被请求级证据量化；
- 结果对负面结论同样保留，不因未提升 goodput 而修改协议。

## 8. 预计资源

模型下载预计占用约 15–16GB 数据盘。低负载校准、容量搜索、四 seed 最终 benchmark 与故障验证预计合计需要约 2.5–4 个 GPU 小时；下载时间另计。实验拆成“下载与校准”和“冻结策略后的 final evaluation”两次云端操作，以便在中间审查证据后安全关机。
