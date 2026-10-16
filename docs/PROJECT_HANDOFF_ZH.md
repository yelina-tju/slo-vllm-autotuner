# vLLM 项目技术说明

更新日期：2026-10-16。本文汇总项目实现、实验设计、结果、局限与证据位置。

## 1. 目录关系

源码为本文件上两级的仓库根目录；原始证据在仓库同级的work目录。学习资料位于本机桌面的vllm目录。本机绝对路径见该学习目录的“vLLM项目_转接说明.md”。保留仓库与work的同级结构。

以上为本地完整归档结构。公开源码只包含代码、文档、配置、测试和小型汇总；不包含
work 或原始运行目录。CPU 检查可独立运行，完整原始证据复核需要本地归档。
分发范围见 [PUBLICATION.md](PUBLICATION.md)。

## 2. 当前状态与定位

项目：SLO-Aware vLLM Serving Autotuner，面向单GPU的SLO感知推理服务评测、外部控制与执行系统。

V1与独立在线准入扩展的既定实现和验证均已完成。当前没有本项目必须继续执行的GPU任务。后续主要可以进行本地代码阅读、离线复核与技术讨论；额外性能实验属于新的研究范围。

没有训练模型权重、修改vLLM核心调度器或实现CUDA kernel；没有生产上线、跨GPU或跨架构模型验证。尚未确认公开GitHub发布及许可证选择。

## 3. 研究问题与指标

外部请求速率、输入/输出长度和混合比例改变时，固定服务器配置与固定准入可能失效。检测、确认、暂停、排空、重启和保守恢复自身也损失服务能力。需要同时评价有效吞吐、迟到、拒绝、恢复速度和故障暴露。

请求级goodput：成功且TTFT、E2E同时不超过所属类别阈值的请求数，除以该实验规定的计分时长。HTTP 200不等于SLO达标；窗口每类P99约束与请求级计数也不等价。

离线选取是有限候选配置与实测速率网格上的经验容量选择，通常要求预定重复全部通过，并满足该轮的完整性/错误/样本规则。3/3通过不是生产可靠性证明，也不是连续空间全局最优。

## 4. V1实现与源码入口

| 模块 | 相对仓库路径 | 负责什么 |
|---|---|---|
| 控制器 | src/slo_autotuner/controller.py | 策略目录、滚动画像、距离、确认/滞回/冷却、兼容恢复、Canary、新证据回滚 |
| 执行器 | src/slo_autotuner/executor.py | 令牌桶、在途请求、暂停/排空、生命周期与目标失败恢复 |
| 网关 | src/slo_autotuner/gateway.py | HTTP/SSE代理、增量事件解析、请求形状与延迟观测、决策执行和审计 |
| 公平比较 | scripts/compare_policies.py | 物化Poisson日程/payload、共享trace、多策略矩阵与逐请求输出 |
| 故障验证 | scripts/run_7b_fault_pairs.py | 经故障代理转发真实7B SSE并注入首token延迟 |
| 执行器探针 | scripts/run_7b_restart_probe.py | 真实重启、在途排空、目标启动失败与源服务恢复 |
| 现有证据复核 | scripts/verify_release_evidence.py | 核对封存归档并复核8次安全运行契约 |

V1检测器在60秒滚动窗口中按log长度距离映射请求形状，再以TV distance匹配画像。确认、滞回和冷却限制误切；兼容准入恢复采用风险非对称的较快路径。

Canary是同一后端上的分级准入恢复，不是第二副本分流；成功晋级和违规回滚要求新的请求ID证据。V1的rate-only变更仍暂停并排空，所以模型零重启不代表零503。

需重启时：暂停 → 排空 → 停源/启目标 → 健康 → 预热 → 恢复准入。目标失败则清理并恢复源；不能确认可用时保持暂停。控制器决策不等于执行成功，应检查live gate与真实进程。

## 5. V1环境、实验与主要结论

历史GPU环境：单4090D 24GB、Ubuntu22.04、Python3.12、vLLM0.19.1、PyTorch2.10.0+cu128。模型Qwen2.5-1.5B-Instruct和Qwen2.5-7B-Instruct，FP16。历史依赖见environment/requirements.lock；独立CPU验证依赖不能替代GPU环境。

- 001–002：初测发现prefix cache与重复prompt混杂，改为显式关闭缓存、预热和开放环。001并发容量只保留探索地位。
- 003–005：比较token预算、请求形状与80/20长短混合，建立每类SLO和目录；不支持的partial-prefill候选保留为兼容性失败。
- 006–009：从CPU重放到真实网关/单卡执行，修正性能预热、重叠ID重复确认及多余恢复重启。
- 010：Oracle和消融区分执行与检测成本；未触发的cooldown/rollback不能按性能差归因。Oracle仅预知边界，仍受目录和执行器限制。
- 011–012：兼容方向非对称恢复，011三个配对seed较旧对称规则goodput平均+1.075req/s（约13.3%）、恢复早28.15秒；后续反转顺序与重复变化进一步检查机制。
- 013–014：加入last-safe回滚、容量上调阻断、分级Canary；真实HTTP/SSE集成发现并修复controller已晋级而gate未更新的问题。
- 015：1.5B五seed×五策略，共25次最终正常对照。
- 017：7B单独校准SLO/选容量，再四seed×四策略，共16次最终正常对照。
- 018：8次成功7B安全运行：健康2、两个持续延迟seed×两策略4、重启成功1、目标启动失败恢复1。另保留一次报告序列化失败尝试。

V1两个最终对照合计41次，不包含前期探索、容量和故障；没有Experiment016，不补造缺失阶段。

| 结果 | 数值 | 必须保留的边界 |
|---|---|---|
| 1.5B正常Canary−binary | goodput −0.549req/s，95%配对t区间[−0.802,−0.295]；满容量恢复+39.80s | 健康保护成本；tail-area区间跨零 |
| 7B正常Canary−binary | −0.174471req/s，区间[−0.273191,−0.075752]；恢复多约41.96s | 同系列规模验证，非所有模型泛化 |
| 7B持续延迟暴露 | binary229/242 → Canary186/186，减少18.78%/23.14% | 全故障过程包含后续配置回退和暂停，非第一阶Canary单独效应或生产故障率 |
| 真实7B重启 | 71.681s，后置推理与清理通过 | 单次功能证据，非恢复SLA |
| 目标启动失败恢复 | 242.069s，含180s目标健康超时 | 清理目标并恢复源、预热与真实推理通过 |

7B正常策略共享mbt1024，准入12/3，Canary3→6→9→12。持续外部故障时先降准入，再因新违规执行mbt1024→2048配置回退；外部注入按时结束，不能说改token预算治好外部故障。第二阶9→6 GPU未覆盖，仅有CPU契约。

static aggressive在最终正常轨迹中goodput高于受约束Oracle，同时承担更多迟到/尾部风险；本项目没有证明自适应普遍胜过固定策略。

## 6. 独立在线准入扩展

目录：extensions/online_admission/。固定后端，根据SLO反馈热调准入，没有替换V1全部公共网关/生命周期，也没有把新扩展在7B上验证。

关键文件：feedback.py、hot_gate.py、cohorts.py、deadline_cohorts.py、transport.py、run_pilot.py；最终协议guarded_recovery_plan.py，执行run_guarded_recovery.py，分析guarded_recovery_analysis.py，独立审计audit_guarded_recovery.py。

机制：
1. 有界AIMD：各要求类别P99 TTFT/E2E归一化压力取最大。有证据的失守/失败按0.7降速，timeout独立提供降速证据。样本够、无失败、压力<0.8、需求>=当前rate的0.9、连续两次才+1。最终bounds1/48、initial48、样本门槛30、settling20秒；源码默认值与最终配置要区分。
2. Proposal/ACK：成功才更新已应用rate/revision，pending禁止重复动作。成功或失败后重新等待稳定并重建证据epoch。
3. 热令牌桶：先按旧速率结算时间，再改rate/capacity并裁剪余额；升容不直接填满桶。与生命周期锁串行，暂停/过期/状态不匹配时关闭更新。
4. 两本账：全量请求保留计分；新epoch仅接纳稳定截止后且版本匹配的新到达。退休控制证据不删除主账本；timeout只最终化一次，迟到成功不改写已封账结果。
5. 截止锚定：按实际settling截止点开始证据窗口，避免全局网格多等近20秒。早期开发GPU配对第二次升速提前19.554–19.771秒，描述性goodput+6.5195%；不是最终约19%的独立因果组成。
6. 取消证据：原聚合abort-counter协议失败保留；新唯一请求ID+精确abort日志+资源空闲/token平台期/恢复的两次单请求探针通过。聚合counter仍0，未证明任意并发取消或隔离控制开销。

## 7. 扩展的失败、修订与最终结果

先后证据不能合并为相同设计的独立重复：
- 309/310开发：240s、LOW24/HIGH48/adaptive48；第一批端口预检中断，保留两个有效对照，后续四case明确续接。TIME_WAIT独立复现支持预检修复，但不声称证明了故障瞬间确因TIME_WAIT。
- 401/402：六轮完整，原始审计通过，但初始窗口中的请求跨40s突增边界完成，判inconclusive_baseline；请求不删除、不挪组、阈值不放宽。
- 403/404：新冻结260s协议。初始0–40、正常guard40–60、72RPS高负载60–220、6RPS低负载220–260；guard完整计分。两个新seed×三策略六轮，LOW/HIGH及恢复均通过独立审计。

最终模型Qwen2.5-1.5B、单4090D、固定256输入/64输出，TTFT100ms、E2E400ms。每seed各策略共享trace。

| Seed | 固定24 | 固定48 | Adaptive | 相对固定24增益 | Adaptive/LOW服务违约 |
|---|---:|---:|---:|---:|---:|
|403|17.0808|2.7154|20.3692|19.25%|978/0|
|404|17.2154|3.0423|20.4769|18.95%|986/0|

goodput为全260秒scheduled compliant req/s，包含dispatch lag；服务违约采用service dispatch口径，不是前者分子的补集。比LOW少拒绝1837/1836，比HIGH少服务违约6594/6531。固定24是保守锚点，不是best-static oracle；不是所有指标全面更优。

两个adaptive都基于[60,80)完整高负载到达证据，于80.511/80.529秒应用48→33.6，100.511/100.529结束稳定期，140.931/140.943确认恢复，早于220秒降载。从突增到确认约80.94秒；约5ms的提案到ACK间隔不是恢复耗时或隔离开销。

整段高负载仍约17%成功请求违反服务SLO，P99仍失守；“恢复”仅指后续状态，不是全程SLO保证。404 guard的一次违约保留在986总数内。

审计重建72,822条请求、核对88个执行源码哈希及前序链。仅两个新seed、一个模型/形状/硬件，支持受限复现，不能宣称大样本显著性、跨模型或生产可靠性。

## 8. 优先阅读与证据入口

以下相对仓库根目录：
- docs/RESULTS_INDEX.md：全实验索引。
- docs/experiment-015.md、results/final_benchmark_analysis.json：1.5B最终。
- docs/experiment-017-final-review.md、results/generalization_7b_capacity_audit.json、results/generalization_7b_final_analysis.json：7B容量和最终。
- docs/experiment-018-7b-fault-validation.md：7B故障与执行器。
- extensions/online_admission/GUARDED_RESULTS.md：扩展最终报告。
- extensions/online_admission/HELDOUT_RESULTS.md：保留的失败前提及边界解释。
- ../work/guarded-sep22-audit.json：最终独立审计。
- ../work/guarded-sep22-evidence/online-admission-pilot-results/guarded403-404-attempt1/：六case原始记录。
- 上述目录的seed403-adaptive/adaptive_deadline/：requests.jsonl、control.jsonl、run_metadata.json。
- docs/REPRODUCIBILITY.md、docs/RELEASE_REVIEW.md：工程复现与范围。

学习目录保留技术notebook、HTML和技术复盘；个人与职业材料已清理。清理未改实验原始记录、冻结快照、统计数字和失败判定。

## 9. 离线检查与接续方式

在源码仓库根目录、Python3.11+环境中，以下两个入口不启动GPU/网络：
    python scripts/verify_release_evidence.py --archives ../work
    python extensions/online_admission/recheck_guarded_evidence.py

完整测试需要相应项目依赖。历史V1有102项回归与12项CPU控制契约；扩展214项执行快照CPU/HTTP测试与99项后续相关回归有重叠，不能相加或当GPU轮次。

阅读结果时需区分 V1 与独立扩展、正常与故障、开发与最终协议。既定实验已完成；
需要新的性能结论时，应先定义独立范围与验证协议。

未验证事项：多GPU、跨架构/多模型扩展、混合长度扩展控制、隔离控制开销、大样本或生产业务验证、全局最优/形式化安全证明。它们属于未来方向，不改写当前已完成范围。

