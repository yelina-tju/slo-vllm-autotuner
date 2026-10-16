# Experiment 014：兼容恢复的 canary 分级升容

## 1. 研究问题

Experiment 013 已经让兼容升容具备 SLO 失守回滚能力，但恢复动作仍是二值跳转：

$$
3\ \mathrm{req/s}\longrightarrow24\ \mathrm{req/s}.
$$

如果 workload 检测器误把异常流量判断为 balanced，控制器会在得到第一批在线延迟证据以前把全部 24 req/s 暴露给可疑策略。虽然两个新鲜违规窗口最终能把准入退回 3 req/s，但回滚之前的故障半径仍然偏大。

本轮把兼容恢复改成：

$$
3\longrightarrow8\longrightarrow16\longrightarrow24\ \mathrm{req/s},
$$

并回答两个不同问题：

1. 慢后端故障发生时，分级升容能减少多少被暴露的请求？
2. 后端健康时，逐级收集证据会付出多少恢复吞吐和恢复时间？

## 2. 目标与约束

设准入级别为

$$
C_0=3,\qquad C_1=8,\qquad C_2=16,\qquad C_3=24.
$$

对第 \(j\) 个窗口和请求类别 \(c\)，SLO pass 定义为：

$$
P_j=\bigwedge_c\left(
\mathrm{failed}_{c,j}=0
\land \mathrm{P99\_TTFT}_{c,j}\le S_c^{\mathrm{TTFT}}
\land \mathrm{P99\_E2E}_{c,j}\le S_c^{\mathrm{E2E}}
\right).
$$

令 \(A_j\) 是窗口中的成功请求 ID 集合。重叠窗口不能重复使用同一批请求作为晋级证据，因此还要求：

$$
A_j\setminus\bigcup_{i<j}A_i\ne\varnothing.
$$

当前配置令 \(K=2\)。只有连续两个 SLO-pass 窗口都含有新的成功请求，才从阶段 \(m\) 晋升到 \(m+1\)：

$$
P_{j-1}\land P_j
\land \mathrm{fresh}(A_{j-1})
\land \mathrm{fresh}(A_j)
\Rightarrow C_m\to C_{m+1}.
$$

若出现待确认的 workload change，则暂停 canary 晋级。若两个含新违规请求的窗口确认 SLO 失守，则退回上一个已验证阶段，而不是一律跌回 3 req/s：

$$
V_{j-1}\land V_j\Rightarrow C_m\to C_{m-1}.
$$

所有 canary policy 与最终目标共享同一 vLLM server environment，因而：

$$
E(C_0)=E(C_1)=E(C_2)=E(C_3)
\Rightarrow R(C_m,C_{m+1})=0,
$$

其中 \(R\) 是模型重启次数。它们只改变网关 token-bucket 的准入上限。

从设计上，本轮是在求一个风险—性能折中，而不是盲目调参：

$$
\max_{\pi}\quad
\mathbb{E}[G(\pi)]-\lambda\,\mathbb{E}[N_{\mathrm{fault}}(\pi)]
$$

$$
\mathrm{s.t.}\quad
\mathrm{P99\_TTFT}_c\le S_c^{\mathrm{TTFT}},\quad
\mathrm{P99\_E2E}_c\le S_c^{\mathrm{E2E}},\quad
C_t\in\{3,8,16,24\},\quad
R_{\mathrm{compatible}}=0.
$$

这里 \(G\) 是 SLO goodput，\(N_{\mathrm{fault}}\) 是错误升容后、回滚前暴露给故障策略的请求数，\(\lambda\) 表示对故障半径的风险偏好。当前控制器没有在线求解该优化式；它实现的是带证据门槛的离散策略 \(\pi\)，实验负责测量该策略的两个目标。

## 3. 实现

控制器新增：

- `compatible_recovery_canary_admission_limits_rps: [8, 16]`；
- `compatible_recovery_canary_pass_windows: 2`；
- `canary_target_policy`：最终的 24 req/s 目标；
- `canary_pass_count`：当前阶段已确认的 pass 窗口数；
- `seen_canary_pass_request_ids`：防止重叠窗口重复记票的新鲜证据集合；
- 自动派生的 `:canary-8rps` 与 `:canary-16rps` policy。

每次阶段切换都会把当前阶段记录为新的 recovery safe point。因此在 16 req/s 失守时回退到已经验证过的 8 req/s；回退、晋级均使用现有 admission-only executor，不停止 vLLM。

实现过程中，真实事件流发现了一个集成缺口：控制器在 SLO pass 后正确产生了 `switch`，但网关旧逻辑只执行 workload detector 产生的 switch 和 SLO 产生的 rollback，导致控制器状态升到 16 而 token bucket 仍停在 8。`run_control_once` 现已同时执行 SLO 路径产生的 `switch` 与 `rollback`，并新增网关集成测试直接检查 live admission gate。

## 4. 机制验证：真实 HTTP/SSE 事件流

`run_live_canary_scenarios.py` 使用真实 HTTP client、token bucket、gateway、SSE 响应解析、SLO collector、controller 与 executor，只把后端替换为可控的本地 aiohttp 服务。

健康路径的准入时间线为：

```text
3 -> 8 -> 8 -> 16 -> 16 -> 24 req/s
     pass1  pass2   pass1   pass2
```

复用旧请求 ID 的 pass 窗口不会晋级；每次第二个含新成功 ID 的 pass 窗口才执行下一次 switch。三次升容的生命周期调用数均为 0。

故障路径使用相同的慢 HTTP/SSE 响应。其 TTFT 与 E2E 被设计为超过 balanced SLO：

| 模式 | 准入时间线 | 回滚前慢请求暴露数 | 最终准入 | vLLM 重启 |
|---|---|---:|---:|---:|
| Canary | 3 → 8 → 8 → 3 → 3 | **16** | 3 req/s | 0 |
| Binary | 3 → 24 → 24 → 3 → 3 | **48** | 3 req/s | 0 |

因此在这个受控反事实中：

$$
\Delta N_{\mathrm{fault}}=48-16=32,
\qquad
\frac{48-16}{48}=66.7\%.
$$

它证明 canary 机制缩小了错误升容的第一轮暴露面；它不表示真实 GPU 故障概率降低了 66.7%。

## 5. 真实 RTX 4090 D 配对实验

为测量健康恢复的代价，seed 86–87 各自生成一条 330 秒开放环轨迹，并在 binary 与 canary 间复用。轨迹为：balanced 0–60 秒、mixed 60–210 秒、balanced return 210–330 秒。seed 86 按 `binary → canary` 运行，seed 87 反转为 `canary → binary`，减少固定顺序混杂。

| Seed | 模式 | 整体 goodput | SLO 合规请求 | HTTP 429 | HTTP 503 | return goodput | 重启 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 86 | Binary | 9.365 | 3093 | 396 | 271 | 13.550 | 1 |
| 86 | Canary | 8.938 | 2952 | 549 | 257 | 12.350 | 1 |
| 87 | Binary | 9.606 | 3171 | 309 | 298 | 13.450 | 1 |
| 87 | Canary | 8.873 | 2929 | 533 | 318 | 11.492 | 1 |

Canary 减 Binary 的两 seed 平均差为：

| 指标 | 平均差 |
|---|---:|
| 整体 goodput | **−0.580 req/s** |
| SLO 合规请求 | **−191.5** |
| HTTP 429 | **+188.5** |
| HTTP 503 | +3.0 |
| balanced-return goodput | **−1.579 req/s** |
| 首次恢复延迟 | +0.512 s |
| 到达 24 req/s 的延迟 | **+40.923 s** |
| 模型重启次数 | **0** |

这里的 `restart_count = 0` 是组间差：binary 和 canary 每次运行都因进入 mixed 各重启一次，分级恢复没有增加模型重载。HTTP 503 的平均差只有 3 个且两 seed 符号不同；它发生在两组共同的重启区间，不能归因于 admission-only canary。可明确归因的正常路径代价主要是：等待两级在线证据期间多返回 429，使 24 req/s 满容量平均晚约 40.9 秒。

## 6. 结论与证据边界

本轮把“回滚后能止损”推进为“升容时先控制暴露”：

$$
\text{detect}\to C_1
\xrightarrow{2\ \mathrm{fresh\ pass}}C_2
\xrightarrow{2\ \mathrm{fresh\ pass}}C_3,
$$

并在任一阶段保留上一个已验证阶段作为回滚点。

结论是一个清楚的工程交换，而不是 canary 全面优于 binary：

- 受控慢后端中，回滚前暴露从 48 降到 16，减少 66.7%；
- 健康 RTX 4090 D 配对运行中，满容量恢复平均延后 40.9 秒，整体 goodput 平均减少 0.580 req/s；
- 两种恢复都不额外重启模型；
- 两个 paired seeds 是 trade-off pilot，不是总体均值估计；
- 阶段 `8/16` 与 `K=2` 仍是工程配置，下一阶段可根据风险预算或置信界自适应选择，而不是继续手工穷举组合。

## 7. 测试、运行操作与产物

本阶段主要操作为：

1. 审查 Experiment 013 的 `3 → 24` 风险窗口，并创建云端 `run/pre014-code-backup.tar.gz`；
2. 扩展 SLO collector，使 pass 窗口携带成功请求 ID；
3. 实现动态 canary policy、逐级晋升、新鲜证据、pending-shift 暂停和逐级回滚；
4. 为旧实验脚本显式关闭 canary，保证历史反事实语义不被默认值改变；
5. 运行控制器与执行器单元测试；
6. 用真实 HTTP/SSE 场景发现并修复 SLO-switch 未更新 live token bucket 的集成缺口；
7. 完成健康与慢后端机制验证；
8. 在 RTX 4090 D 上完成两个 seed、反转顺序的 binary/canary 配对矩阵；
9. 自动校验同 seed trace hash、策略序列、重启次数并生成聚合结果；
10. 实验结束后停止 gateway/vLLM，确认 8000/8080 端口关闭且 GPU 无计算进程。

完整回归测试由 62 项增加到 65 项，全部通过。

关键产物：

- `src/slo_autotuner/controller.py`
- `src/slo_autotuner/gateway.py`
- `configs/controller.json`
- `configs/canary_tradeoff_seed86.json`
- `configs/canary_tradeoff_seed87.json`
- `scripts/run_live_canary_scenarios.py`
- `scripts/prepare_experiment014.py`
- `scripts/run_experiment014.sh`
- `scripts/summarize_canary_tradeoff.py`
- `results/live_canary_scenarios.json`
- `results/canary_tradeoff_analysis.json`
- `results/canary_tradeoff_seed86/`
- `results/canary_tradeoff_seed87/`
- `logs/experiment014.log`

