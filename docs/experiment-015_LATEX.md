# Experiment 015：五 seed 最终基准与安全—性能边界

## 1. 研究问题

Experiment 014 用两个 paired seed 初步测量了 canary 的正常路径代价，并用受控慢后端测量了故障暴露。Experiment 015 不继续调 `8/16` 或窗口数，而是冻结代码和配置，用五个新 seed 回答：

1. binary、canary 与已知 phase boundary 的 oracle 相差多少？
2. canary 的正常路径成本在不同 seed 上是否稳定？
3. static aggressive 与 static conservative 两个极端分别隐藏了什么代价？
4. 减少故障半径是否以可量化的 goodput 和恢复时间为价格？

控制目标不是最大化 HTTP 200 数量。对策略 \(\pi\)，SLO goodput 定义为：

$$
G(\pi)=\frac{1}{T}\sum_{r=1}^{N}
\mathbf{1}\!\left[
H_r=200\ \land\
L^{\mathrm{TTFT}}_r\le S^{\mathrm{TTFT}}_{c(r)}\ \land\
L^{\mathrm{E2E}}_r\le S^{\mathrm{E2E}}_{c(r)}
\right].
$$

因此，返回 429 的请求和虽然返回 200 但超过任一类别 SLO 的请求都不计入 \(G\)。

## 2. 冻结实验设计

使用 seed 88–92。每个 seed 生成一条 330 秒开放环 Poisson 轨迹：

| Phase | 时间 | 到达率 | long 占比 |
|---|---:|---:|---:|
| balanced-before | 0–60 s | 16 req/s | 0% |
| mixed-shift | 60–210 s | 6 req/s | 20% |
| balanced-return | 210–330 s | 16 req/s | 0% |

五种模式为：

- `static_aggressive`：始终使用 balanced 24 req/s policy；
- `binary_recovery`：mixed 后从 3 直接恢复到 24 req/s；
- `canary_recovery`：mixed 后按 3 → 8 → 16 → 24 req/s 恢复；
- `oracle_boundary`：提前知道 60 s 和 210 s 两个 phase boundary，但使用相同单卡执行器和 policy catalog；
- `static_conservative`：始终使用 mixed 3 req/s policy。

五个 seed 使用循环顺序，使每个模式恰好在第 1–5 个执行位置各出现一次。每个 seed 内，所有模式复用相同的 request schedule、类别、token payload hash 与 SLO。最终校验结果为：

| 完整性条件 | 结果 |
|---|:---:|
| 完整结果 | 25/25 |
| 同 seed request schedule 与 payload 一致 | 通过 |
| run key 一致 | 通过 |
| 循环执行位置平衡 | 通过 |
| control error | 0 |
| backend/transport error | 0 |
| 终态健康且准入重新开放 | 通过 |

## 3. 五 seed 聚合结果

表中 `±` 是 seed 间样本标准差，不是置信区间。

| 策略 | SLO goodput (req/s) | 合规请求 | HTTP 429 | HTTP 503 | completed-but-late | tail area |
|---|---:|---:|---:|---:|---:|---:|
| Static aggressive | 11.234 ± 0.228 | 3710.2 | 0 | 0 | 70.2 | 22.415 |
| Oracle boundary | 9.581 ± 0.160 | 3164.4 | 310.0 | 303.6 | 2.4 | 0.136 |
| Binary recovery | 9.227 ± 0.270 | 3047.6 | 372.4 | 325.4 | 35.0 | 9.607 |
| Canary recovery | 8.679 ± 0.358 | 2866.4 | 536.4 | 339.6 | 38.0 | 9.279 |
| Static conservative | 2.989 ± 0.007 | 986.6 | 2793.0 | 0 | 0.8 | 0 |

`static_aggressive` 的 HTTP 请求全部成功，但平均仍有 70.2 个 completed-but-late 请求，并产生最高 tail-violation area。它是“不做保护”的吞吐/风险基线，不是满足 SLO 约束的 oracle。

`static_conservative` 的 tail area 为零，但平均拒绝 2793 个请求。它证明只靠永久限流可以保护成功请求的尾延迟，却无法获得高 SLO goodput。

`oracle_boundary` 预知 workload 变化，但仍必须在单卡上排空、重启和健康检查。因此它是受相同执行器约束的控制 oracle，而不是零成本理论上界。

## 4. 配对差与不确定性

对每个 seed 定义配对差：

$$
d_s=M_{s,\mathrm{canary}}-M_{s,\mathrm{binary}},
\qquad
\bar d=\frac{1}{5}\sum_{s=1}^{5}d_s.
$$

由于只有五个 seed，使用自由度为 4 的双侧 Student-t 区间：

$$
\mathrm{CI}_{95\%}(\bar d)
=\bar d\pm t_{0.975,4}\frac{s_d}{\sqrt{5}},
\qquad t_{0.975,4}=2.776.
$$

| Canary − Binary 指标 | 平均差 | 95% t 区间 |
|---|---:|---:|
| 整体 SLO goodput | **−0.549 req/s** | **[−0.802, −0.295]** |
| SLO 合规请求 | **−181.2** | **[−265.0, −97.4]** |
| HTTP 429 | **+164.0** | **[+92.7, +235.3]** |
| HTTP 503 | +14.2 | [−10.7, +39.1] |
| tail-violation area | −0.328 | [−1.871, +1.216] |
| 首次 balanced 恢复延迟 | −0.604 s | [−5.16, +3.95] |
| 满容量恢复延迟 | **+39.800 s** | **[+35.28, +44.32]** |
| 模型重启次数 | 0 | [0, 0] |

在这五个 seed 上，可以稳定观察到 canary 的正常路径代价：它等待两级新鲜 SLO 证据，因而多返回 429，满容量恢复晚约 40 秒，goodput 下降约 0.55 req/s。

不能从这组数据声称 canary 改善了正常路径尾延迟。其 tail-area 配对区间跨过零；HTTP 503 和首次恢复延迟的区间也跨过零。两种 adaptive 策略都只因进入 mixed policy 重启一次，canary 升容本身没有增加模型重启。

Binary 相对 oracle 的 goodput 差为 −0.354 req/s，95% 区间为 [−0.516, −0.192]。其 mixed 检测加确认使切换完成平均比 oracle 晚约 74.9 秒；但延迟切换期间继续接收请求，也会让 mixed 阶段的表面 goodput 高于 oracle。该差值不能被解释为 detector 免费创造了容量。

## 5. 安全收益与综合结论

真实 GPU 的健康路径无法直接观察“如果目标 policy 其实故障”的反事实，因此安全收益沿用 Experiment 014 的受控 HTTP/SSE 慢后端注入：

$$
E_{\mathrm{binary}}=48,
\qquad
E_{\mathrm{canary}}=16,
\qquad
\frac{E_{\mathrm{binary}}-E_{\mathrm{canary}}}
{E_{\mathrm{binary}}}=66.7\%.
$$

因此本项目得到的是一条可复现的风险—性能边界：

$$
\text{支付 }0.549\ \mathrm{req/s}\text{ 的平均 goodput}
+39.8\ \mathrm{s}\text{ 的满容量恢复时间，}
$$

$$
\text{换取受控故障中 }66.7\%\text{ 的首轮暴露缩减。}
$$

这不是“canary 总是更优”，也不是“binary 应被删除”。若服务的错误升容成本很高，canary 提供了明确的保护；若目标是健康恢复时尽快恢复吞吐，binary 更合适。系统应依据风险预算选择恢复策略，而不是只看单一 goodput 排名。

## 6. 运行与证据

本轮主要操作为：

1. 为 seed 88–92 生成五种模式的循环执行顺序；
2. 在每个 seed 中物化一条开放环轨迹，并为每个请求记录 payload SHA-256；
3. 每种模式使用独立 gateway/backend，但复用同 seed 的完整轨迹；
4. 每次结束后验证服务健康、准入未暂停、无 control error；
5. 自动跳过已有且 run key、请求数和 payload 均有效的完整模式，使长实验可恢复；
6. 运行 25 个真实 RTX 4090 D 模式，随后确认 vLLM 进程退出和 GPU 释放；
7. 将约 149MB 原始证据压缩为 27MB 归档，并在云端与本地比对 SHA-256：`6e8909de210ffe4ef74ff08878af853aee0c46730cad8c3766b2df7bf0abafb1`；
8. 在本地独立重跑汇总与完整性校验；
9. 为所有 paired delta 增加五 seed 小样本 t 区间。

关键产物：

- `scripts/prepare_experiment015.py`
- `scripts/run_experiment015.sh`
- `scripts/summarize_final_benchmark.py`
- `configs/final_benchmark_seed88.json` 至 `seed92.json`
- `results/final_benchmark_seed88/` 至 `seed92/`
- `results/final_benchmark_analysis.json`
- `results/final_benchmark_rows.csv`
- `logs/experiment015.log`

云端实验启动前运行 69 项回归测试，全部通过；本地新增置信区间和 7B SLO 冻结测试后，相关 9 项测试全部通过。

## 7. 证据边界与下一阶段

- 五个 seed 足以展示当前工作负载下的重复性，但仍不是生产流量总体；
- 循环顺序平衡执行位置，不能消除所有温度、宿主机与共享资源漂移；
- 当前模型只有 Qwen2.5-1.5B，不能据此声明模型规模或架构泛化；
- 故障半径来自可控 HTTP/SSE 故障注入，应与真实 GPU 性能结果分开报告；
- 下一阶段按预注册协议迁移到 Qwen2.5-7B：先做独立低负载 SLO 校准，再做容量搜索，最后用未参与选择的 seed 评估，不复用 1.5B 的绝对 SLO 和 canary 容量。
