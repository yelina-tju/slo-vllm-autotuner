# Experiment 010：Oracle 上界与控制器消融

本轮不再搜索新的 vLLM 参数，而是回答两个系统问题：如果提前知道 workload 何时变化，当前策略目录最多能做到什么；confirmation、距离滞回、cooldown 和 rollback 分别付出了多少代价。

## 实验口径

七组使用 seed=81 的同一条 3,796 请求、330 秒 short → mixed → short trace，payload 指纹与前两轮一致。所有真实组均经过相同 gateway、启动预热和单卡执行器。

- `oracle_boundary`：准确知道 60 秒和 210 秒边界，边界到达即切换；仍支付真实单卡重启、排空和预热成本。
- `full_controller`：完整滚动检测和安全机制。
- `no_confirmation`：`switch_confirmation_windows` 从 3 改为 1。
- `no_hysteresis`：移除 profile-distance margin 与最大距离门。
- `no_cooldown`：两个 cooldown 均设为 0。
- `no_rollback`：本次测量期间不允许 SLO rollback。
- `minimal_detector`：组合移除上述保护，只保留滚动窗口和 profile 匹配，用于测量剩余检测惯性；它不是单因素消融。

绝对 perfect-service 上界是 3,796/330 = 11.503 req/s。它假设全部请求都按时完成，只是数学上界。`oracle_boundary` 是当前策略目录与单卡执行约束下的可测 Oracle 参考，不是所有 serving 系统的全局最优。

## 总结果

| 组别 | 达标请求 | goodput | 429+503 | 成功但超时 | tail area | 无成功窗口 |
|---|---:|---:|---:|---:|---:|---:|
| Oracle boundary | 3,198 | 9.683 | 597 | 1 | 0.000 | 2 |
| 完整控制器 | 2,679 | 8.112 | 1,098 | 19 | 8.892 | 0 |
| 去 confirmation | 2,843 | 8.608 | 935 | 18 | 1.999 | 2 |
| 去距离滞回门 | 2,845 | 8.614 | 927 | 24 | 9.350 | 2 |
| 去 cooldown | 2,693 | 8.154 | 1,076 | 27 | 9.761 | 0 |
| 去 rollback | 2,609 | 7.900 | 1,166 | 21 | 9.116 | 2 |
| Minimal detector | 2,981 | 9.026 | 805 | 10 | 1.218 | 2 |

goodput 单位为 req/s。tail area 只对成功请求计算；没有成功样本的窗口另行计数。因此 Oracle 的 tail area=0 不能解释为无损服务，它恰好有两个被重启覆盖的无成功窗口。

## Oracle 告诉了我们什么

Oracle goodput 为 9.683 req/s，距离绝对上界还差 1.820 req/s，即 598 个请求：

- 311 个 HTTP 429：mixed 策略 3 req/s 的保守准入代价；
- 286 个 HTTP 503：单卡暂停、重启和短暂 admission-only 事务的代价；
- 1 个成功响应超过请求 SLO。

第一次边界切换实际耗时包含在 45.17 秒总事务时间中。换言之，即使检测器完全知道未来，当前单副本系统仍会因物理重启和保守 policy 损失 597 个到达请求；这部分不能靠缩短检测窗口解决。

完整控制器相对 Oracle 少 519 个达标请求，goodput 低 1.571 req/s，多 501 个拒绝。其进入 mixed 和恢复 balanced 的检测延迟分别为 75.27 秒、58.04 秒。延迟进入 mixed 暂时减少了保守限流，却产生更多尾延迟风险；延迟退出 mixed 则让已经恢复的短请求继续被 3 req/s 限流，是净损失的主要来源。

## 各安全机制的代价

| 组别 | 进入 mixed 延迟 | 恢复 balanced 延迟 | 相对完整组增加达标请求 | goodput 增量 |
|---|---:|---:|---:|---:|
| 去 confirmation | 55.24 s | 40.16 s | +164 | +0.497 |
| 去距离滞回门 | 75.24 s | 43.13 s | +166 | +0.503 |
| 去 cooldown | 75.25 s | 56.92 s | +14 | +0.042 |
| 去 rollback | 75.24 s | 62.01 s | -70 | -0.212 |
| Minimal detector | 55.25 s | 30.16 s | +302 | +0.915 |

### Confirmation

完整组记录了四次 `awaiting confirmation`，两个方向各两次。移除后进入 mixed 提前 20.03 秒，恢复 balanced 提前 17.89 秒。在这一条清晰、持续的 workload shift 上，三次确认没有遇到需要过滤的短暂假信号，观测代价为 164 个达标请求和 0.497 req/s goodput。

这不能推出应该永久删除 confirmation；还需要专门构造短脉冲和边界抖动 trace，测它避免了多少错误重启。

### 距离滞回门

完整组有一次候选 profile 被距离/滞回门挡住。移除后进入 mixed 时间基本不变，恢复 balanced 提前 14.91 秒；增加 166 个达标请求和 0.503 req/s goodput。tail area 比完整组高 0.458，但两组无成功窗口数量不同，且只有一个 seed，不能把差值解释成稳定性因果效应。

### Cooldown 与 rollback

完整组中 `restart cooldown is active` 为 0 次，rollback 为 0 次。因此它们在本 trace 上没有改变任何控制决策，控制路径成本为 0。去 cooldown 的 +0.042 goodput 与去 rollback 的 -0.212 goodput 都是在分支未触发情况下出现的串行运行差异，应视为环境噪声，不能归因于机制。

这也是消融实验的重要结论：没有被激活的机制，不能仅凭两次独立性能测量的差值评价好坏。要测试 cooldown 与 rollback，需要另外构造快速往返 workload 和持续 SLO 故障注入。

## 滚动检测器本身的代价

`minimal_detector` 已移除确认、距离门、cooldown 和 rollback，但仍在 mixed 边界后等待 55.25 秒、在 balanced 边界后等待 30.16 秒。原因是 60 秒滚动窗口仍包含旧分布，请求比例必须变化到另一个 prototype 成为最近者。

相对完整控制器，minimal detector 增加 302 个达标请求、goodput 提高 0.915 req/s、减少 293 个拒绝；相对 Oracle 仍少 217 个达标请求、goodput 低 0.657 req/s、多 208 个拒绝。这一剩余差距主要反映在线滚动证据积累与边界切换时序，而非 confirmation/cooldown/rollback。

## 结论

在这条明确的单次 0%→20%→0% 长请求变化上：

1. 最大固定成本是一次真实单卡重启：约 45 秒、286 个 503。
2. 60 秒滚动窗口是最大检测惯性：即使撤掉保护，仍延迟约 55/30 秒。
3. 三次 confirmation 额外增加约 20/18 秒；本 trace 上没有获得可观测防抖收益。
4. 距离滞回门主要拖慢回程约 15 秒；其稳定性价值尚未被本 trace 测到。
5. cooldown 与 rollback 本轮未触发，因果成本为 0；必须用针对性故障 trace 评价。

因此下一步不是简单把所有保护删掉，而是改成非对称控制：进入风险 workload 保留较强确认，恢复已知高容量兼容策略使用更短窗口或更快确认；同时为 cooldown/rollback 单独设计会触发它们的压力场景。

## 产物与复现

- 主实验（仅本地）：`results/oracle_ablation_seed81/`
- 组合消融（仅本地）：`results/minimal_detector_seed81/`
- 汇总 JSON（主实验本地目录内）：`ablation_analysis.json`
- 汇总 CSV（主实验本地目录内）：`ablation_summary.csv`
- 配置：[oracle_ablation.json](../configs/oracle_ablation.json) 与 [minimal_detector.json](../configs/minimal_detector.json)

所有组均完成 3,796 条请求记账，trace SHA-256 为 `84ba4fa6ab24a0c20802c1255f61f7f150cfdbb0ef3c9ea363f012aeb81e6c11`。本轮 54 项自动测试通过。实验结束后 gateway、vLLM 和压测脚本均已停止，GPU 显存为 0 MiB。

本轮仍只有一个 seed，且七组串行运行。精确切换时间与分支触发次数具有直接审计证据；小幅延迟差和未触发分支的性能差不具备统计显著性。
