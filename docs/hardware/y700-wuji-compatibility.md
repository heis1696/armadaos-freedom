# 联想拯救者 Y700 无极（TB324ZC）Linux/ArmadaOS 兼容性调研（返修）

> 目标机型：**Lenovo Legion Y700 无极 / Y700 Infinite / Legion Y700 AI Infinite 5G，型号 TB324ZC**（中国版 ZUXOS）。
> 基线：本仓库 `devices/lenovo-tb323fu/` 的 TB323FU（Y700 五代，SM8850P，board `baldur`）。
> 调研日期：**2026-10-19**。本文是只读调研：不新增设备支持、不移植设备树、不提供刷写步骤。
> 返修说明：在提交 `11f88bf` 基础上修正口径。原稿把固定快照的 164 Hz/90 Hz 当成项目现状，把快照的 s2idle/充电/吞吐当成已验收，并称官方手册未找到；本稿改为“固定快照 / 本分支当前状态 / 目标机证据”三层，补入手册核读结果，删除无来源的硬性验收承诺。

## 摘要

TB324ZC 是 2026 年的 Y700 无极：8.4 英寸 2560×1600 165 Hz OLED、第五代骁龙 8“至尊领先版”（官方最高 4.74 GHz，Geekbench 报 QTI SM8850）、5G、双 Type-C。它与 TB323FU 同属 SM8850 家族，但板级几乎全换：下游 DT 的 `compatible` 是 `lenovo,wuji`/`qcom,canoe`，面板节点为天马 RM693A0（下游证据，实机批次待核），触控/音频/电源/5G 都需要新板级数据；本仓库的 TB323FU 镜像、DTB、GBL、面板时序不能直接套用。

必须区分三个对象。**固定上游快照** `11a25bf8` 的 `0109` 加的是 90/164 Hz，`docs/hardware-status.md` 的 90Hz/164Hz/PD/PPS/s2idle 9/9/Wi-Fi soak 都是 TB323FU 快照记录，不是本分支或 TB324ZC 的验收结果。**本分支当前状态**用 `runtime-fixes/0109` 替换为 90/165 Hz；`165hz.md` 说明 165 Hz 候选保留 120 Hz 水平时序、Htotal 2244、Vtotal 3120、像素时钟 1155211 kHz（约 164.99997 Hz），补丁头明确写“165 candidate untested”；`README.md` 仍把“90 Hz 偶发物理花屏”列为未解决。因此不能把“项目改用 164 Hz、90 Hz 可用”写成当前状态，也不能说 165 Hz 已验收。

官方资料已找到并核读：`iknow` 页面 442112 的接口返回《联想AI平板 拯救者Y700无极（TB324ZC）用户指南》V1.0，并给出 PDF；本次已下载并抽取正文（47 页）。手册第 38 页（印刷页 33）只写“USB-C1/C2 接口”，没有逐口 USB 版本/DP/PD 说明。故双口存在有官方手册支持，逐口能力仍未证实。

双 Type-C 原结论保留：官方规格/手册、LTBox `b4dd78f` 修正、下游单 `dwc3` 均支持“双口”；但“两口都支持 USB3/DP/PD”没有证据。公开 Linux 侧仍无 wuji 主线 DTB、补丁或 TB324ZC 启动证据；LTBox/GBL 是伪解锁与刷机工具，不等于原生 Linux。建议按“Android 只读采集 → 最小 DT/initramfs → 显示/触控 → USB/音频/电源 → Wi-Fi/5G”推进；未决项集中在面板批次、触控/功放型号、逐口 USB、电池参数、modem 固件与解锁路径。

## 0. 口径：先分清三个对象

| 代号 | 对象 | 范围与证据 | 能否当作“本项目/本机已验收” |
|---|---|---|---|
| **A** | 固定上游快照 | `devices/lenovo-tb323fu/kernel/tb323fu-linux-11a25bf8/tb323fu-linux-11a25bf89b65fff48112a91a0b25bc247e7736d8/`（vendor tree，commit `11a25bf8`）；组件来源见 `devices/lenovo-tb323fu/docs/SOURCES.md`；状态见其 `docs/hardware-status.md`（2026-10-04） | **否**。只代表 TB323FU 固定快照当时的记录 |
| **B** | 本分支当前状态 | `devices/lenovo-tb323fu/kernel/runtime-fixes/`（替换 `0109`、`165hz.md`）；`devices/lenovo-tb323fu/README.md` | 只能代表分支代码/文档声明；README 明列未解决项 |
| **C** | 目标机 TB324ZC | 官方手册/规格 + Lenovo-SM8850 Android 下游树/固件清单 + 社区报告 | **否**。没有 Linux 启动或整机验收证据 |

证据级别：**官方**（手册/规格页）/ **公开代码**（可查提交或文件）/ **社区报告**（论坛，未独立复核）/ **未找到**。所有“未找到”仅指本文检索范围与日期，不等于绝对不存在。

## 1. 官方资料：手册已找到并读取

- 详情页：<https://iknow.lenovo.com.cn/detail/442112>（SPA；正文可由接口 `https://iknow.lenovo.com.cn/api/knowledge/knowledgeDetails?knowledgeNo=442112` 读取）。
- 接口返回（读取成功）：标题“联想AI平板 拯救者Y700无极（TB324ZC）用户指南”，版本 **V1.0**，`createTime 2026-09-01`，并给出用户手册 PDF 链接；与领队提取结果一致。
- PDF：<https://chinakb.lenovo.com.cn/chinakb/prod-api/file/downloadFile?key=uniko%2FFILE%2Ff20b8dab31ac68386a5d348de6ecb147-1788224895457.pdf>。本次已成功下载并抽取文本：47 页，`CreationDate 2026-08-31`。
- **接口说明核读结果**：手册没有逐口接口规格。唯一直接提到口的是第 38 页（印刷页 33）“将充电仓连接至平板的 **USB-C1/C2** 接口”；安全页只写“USB 2.0 及以上”的通用充电说明，不能据此推断任一数据口的 USB 版本。
- 结论：**双口存在有官方手册支持；“哪个口是 USB3/DP、各自 PD/PPS/OTG 能力”仍无官方逐口说明。**

### 1.1 规格与来源

| 项目 | 内容 | 证据/口径 |
|---|---|---|
| 型号 | 拯救者 Y700 无极；TB324ZC | 官方手册 V1.0；官方商城 |
| SoC | 第五代骁龙 8 至尊领先版，最高 4.74 GHz；Geekbench 报 QTI SM8850、`wuji_prc_consumer_5G` | 官方规格；Geekbench；实际 SKU/频率待实机 |
| 屏幕 | 8.4" 2560×1600 165 Hz OLED | 官方规格；面板型号见 §2，属下游证据，实机批次待核 |
| 内存/存储 | 24 GB / 1 TB（**一种 SKU**） | XDA 标题；官方配置表未见；Geekbench 仅给型号/SoC；其他容量组合不作保证 |
| 电池/充电 | 7470 mAh 典型值；充电功率官方未给，零售页称 68 W（非官方，未核验） | 官方规格/零售页；不作验收指标 |
| 接口 | 双 Type-C（手册称 USB-C1/C2） | 官方手册/规格；逐口能力未证实 |
| 网络 | 5G 全网通；手册提到 SIM 卡 | 官方规格/手册；双卡、频段、VoLTE 待核 |
| 系统 | Android 16 / ZUXOS | 官方页面/固件；具体版本待核 |

> SKU 口径：24 GB/1 TB 只是当前公开材料中出现的一种配置，不代表全批次；内存大小会影响 DT 的 memory 节点，实机必须另核。

## 2. 与 TB323FU 的差异

| 维度 | A：TB323FU 固定快照 | C：TB324ZC 证据（来源） | 对 wuji 移植的含义 |
|---|---|---|---|
| SoC/板级 | SM8850P，`kaanapali`，board `baldur` | 官方“领先版”4.74 GHz；下游 `wuji-canoe-base.dts`：`compatible = "lenovo,wuji", "qcom,canoe"`、`msm-id 0x294` | SoC 级可复用；OPP、固件路径、板级数据不可套用；`canoe` 与 `kaanapali` 不是可互换 compatible |
| 显示 | CSOT NT36523/36536 TDDI，1904×3040，双 DSI，DSC；快照 90/164 Hz | 下游 `wuji-canoe-overlay-display.dtsi`：`wuji_rm693a0_tianma_dvt2_cmd` / `wuji_rm693a0_tianma_dsc_cmd`，面板名 `rm693a0 ... tianma ... DSC 10bit`，宽 `0x640`=1600；timing 为 120/165/144/60/30 Hz；vendor 有对应校准文件 | 下游节点只能证明该 Android 配置用过 RM693A0；**实机面板型号/批次待核，不写成全批次保证**；主线无 RM693A0 驱动 |
| 触控 | Novatek NT36536 TDDI，SPI19，带笔 | 下游 input overlay 在 `qupv3_se19_spi` 下有 `touch@0`；vendor 清单含 `goodix_config.bin`、`goodix_firmware.bin`、`vendor.lenovo.hardware.touchscreen-service` | 可能是 Goodix 独立触控；控制器型号、固件版本、笔协议未公开，需实机确认 |
| 音频 | 2× AW882xx（I2C `0x34`/`0x37`）+ WCD9395 | 下游 audio overlay：`aw882xx_smartpa@34`/`@37`，同时存在 WCD939x/9378/937x 节点（可能为模板）；vendor 清单含 `aw882xx_cali`/`aw882xx_acf.bin` | 功放系列有证据；具体 chip ID、地址、复位/供电、Codec 实际装配待核 |
| 电源 | pmic-glink、PMIH0108、PMK8850 等 | 下游 PMK8850、PMIH010x、PMH0101/0110/0104；电池 7470 mAh | 驱动框架可复用；电池曲线、充电/旁路阈值、热区、fuel gauge 全重做 |
| USB | 单个 dwc3 + QMP combo；口0 USB3.2+DP，口1 USB2.0 | 官方双 Type-C；下游 `canoe-usb.dtsi` 只有 1 个 `ssusb@a600000` + `qcom,canoe-qmp-usb3-dp-phy` | 拓扑可能同源；逐口映射、SS/DP 所在侧、PD/PPS、mux/repeater 待测 |
| Wi-Fi/BT | WCN7860 “peach” `17cb:110e`，PCIe0，ath12k | 下游 `compatible = "qcom,cnss-peach"` 与 `qcom,peach-bt` | 同芯片家族；板级 BDF/校准、PCIe/PERST/CLKREQ/WAKE、BT_EN 重取 |
| 5G/基带 | MPSS 能启动，但 rmtfs/tqftpserv 默认 mask；无蜂窝、无可用 GNSS | 官方 5G；下游 `canoe-ipa.dtsi` + `lenovo,cellular-hardware-info` | Linux 无公开证据，最高风险；不稳时保持 mask |
| 启动/解锁 | LTBox EDL 写 `efisp` 的 GBL、ABL 内存补丁、kShimC 菜单；伪解锁仍报 `locked/green` | LTBox 支持 TB324ZC；社区报告 ABL 165/187、官方 `sn.img` 邮件不到；无真解锁/Linux 启动证据 | 工具思路可复用；GBL/boot/vbmeta/分区必须按 wuji 重验，不能使用 baldur 镜像 |

## 3. 刷新率口径：164/165/90 Hz 必须分开写

| 记录 | 文件/位置 | 内容 | 边界 |
|---|---|---|---|
| A-补丁 | `.../tb323fu-linux-11a25bf8.../kernel/patches/0109-drm-panel-nt36523-baldur-add-90-Hz-and-164-Hz-modes.patch` | 加 90 Hz（vendor `dtiming@5`）和 164 Hz；头注：90 Hz 实测 90 Hz、0 underrun、触控正常；164 Hz 实测 163 Hz、0 underrun、25 s 无 DSI/DPU/touch 错误；vendor 165/144 每帧 underrun | 固定快照补丁；短测；**不覆盖本分支 165 候选** |
| A-状态 | `.../docs/hardware-status.md`（2026-10-04） | 90 Hz ✅、164 Hz ✅、vendor 165 ❌、144 ❌；164 长会话未观察 | TB323FU 快照记录，**不是本分支/本机验收** |
| B-补丁 | `devices/lenovo-tb323fu/kernel/runtime-fixes/165hz.md` + `0109-drm-panel-nt36523-baldur-add-90-Hz-and-165-Hz-modes.patch` | 替换快照 `0109`；加 90 Hz 和 165 Hz；165 保留 120 Hz 水平时序，Htotal 2244、Vtotal 3120、像素时钟 1155211 kHz ≈ 164.99997 Hz；补丁头明确“165 candidate untested”，164 的 25 s 测试不适用 | **本分支代码记录**；不是验收报告 |
| B-文档 | `devices/lenovo-tb323fu/README.md` | 当前列 30/60/90/120/165，称“真实 165 Hz 面板时序”，旧内核可回退 164 Hz；已知限制写“90 Hz 偶发物理花屏……未完全解决” | 本分支文档声明，仍列未解决项 |

由此得到三条明确结论：

1. “项目改用 164 Hz（120 Hz 水平时序）、90 Hz 可用”只对应 **A 的快照 0109 与短测**，不能写成 B 的当前状态，更不能写成 TB324ZC 的结果。
2. “本分支有 165 Hz 替换补丁”为真；但“165 Hz 已验收”没有仓库证据，补丁头自己写明该候选未测。
3. B 仍把“90 Hz 偶发物理花屏”列为未解决，因此“90 Hz 可用”只能作为 A 的短测记录，不能作为 B 的验收结论。对 TB324ZC，下游 DT 列了 120/165/144/60/30，但那是 Android 面板节点，没有 Linux 下 RM693A0 的 mode set/underrun 记录。

## 4. 双 Type-C：结论保留，能力仍待测

**结论：TB324ZC 是双 Type-C；“single USB-C”是 LTBox 的旧错误，已被其上游修正。领队已核验 `b4dd78f`，本稿保留该结论。**

1. 官方手册 V1.0 第 38 页写“USB-C1/C2 接口”；官方规格页写“双 Type-C”。
2. LTBox `2002864b`（2026-09-09）首次加入 TB324ZC 时写 “exposes a single USB-C port”，`dual_usb` 未置位。
3. LTBox `b4dd78f`（2026-09-10，标题 “TB324ZC has two USB-C ports, not one”）把 `dual_usb` 改为 `true`，测试改为 `assert!(tb324zc.dual_usb && tb323fu.dual_usb)`。
4. 当前 `capabilities.rs`（`9ac1ad2`，2026-10-05）仍为 `dual_usb: true`；注释写明 shares TB323FU's efisp/GBL route, multi-image Sahara manifest and dual USB-C ports。
5. 下游 `canoe-usb.dtsi` 只有一个 `dwc3`，与 TB323FU 的“单 dwc3 + 双口复用”同构；这支持“双口”，但不决定口间能力。

可以说：**双 Type-C 已确认**。不可以说：**两个口都支持 USB3/DP/PD**。需要实机确认：口间映射、SS/DP 所在侧、PD/PPS、OTG、eUSB2 repeater 与 mux GPIO。

## 5. 可复用、必须重做与首版路线

| 子系统 | 可复用（证据） | 必须重做 | 首版路线（不预设硬指标） |
|---|---|---|---|
| 启动 | LTBox 的 EDL/GBL/Sahara 模型、kShimC 菜单、init_boot KernelSU 方式 | wuji 的 ABL/efisp/GBL、boot 布局、AVB/vbmeta、回滚、分区备份 | 先只读采集 `getvar`/ABL/分区；写入另评审，本文不提供步骤 |
| 内核/DT | 主线 kaanapali SoC、TB323FU 的 SoC 级补丁、config 片段 | 新增 `lenovo,wuji` 板级 DT；内存/存储/固件路径；`canoe`→`kaanapali` 映射 | 最小 DT → initramfs → 串口/显示；`make dtbs` 与 dtc 警告作为门禁 |
| 显示/触控 | DRM/MSM、DSI/DPU/DSC、双 DSI、panel 框架；Goodix 主线驱动可能性 | RM693A0 驱动/时序、DSI PHY/clock/lane、背光/reset/TE、Goodix 型号/固件/笔 | 先移植 vendor 初始化序列与 timing，再逐模式记录 underrun；触控先 probe |
| GPU | Adreno 840 的 msm/freedreno/turnip、GPU SMMU/GPUCC | wuji 的 zap shader、OPP、热/功耗、冷却图 | 保守频率起步，逐档验证；不要复用 baldur 的 zap |
| USB | dwc3、QMP combo、eUSB2、UCSI/pmic-glink、Type-C/PD/DP 框架 | 口间 mux、PD/PPS、repeater/redriver、DP lane、唤醒 | 先单口 host/gadget，再第二口；记录 `typec` 角色 |
| 音频 | AW882xx 驱动、I2S、扬声器保护/UCM 思路 | 功放地址/复位/供电/校准、Codec 型号、麦克风/耳机路由、UCM | 先读下游节点并 probe 功放，再逐路调通；不假设 Codec |
| 电源 | qcom_battmgr、pmic-glink、充电/热框架、旁路 helper 思路 | 电池曲线/容量、充电/旁路阈值、PMIC GPIO、热区/冷却图 | 先只读电量/温度，再开充电与旁路；参数按实机重标 |
| Wi-Fi/BT | ath12k、btqca、WCN7860 相关补丁、固件提取流程 | 板级 BDF/校准、PCIe/PERST/CLKREQ/WAKE、稳压器、BT_EN | 先 2.4/5 GHz，再评估 6 GHz；记录 firmware crash |
| 5G/基带 | q6v5/remoteproc、rmtfs、tqftpserver、QRTR、IPA、ModemManager | modem 固件/mcfg、IPA/SMEM/GLINK、SIM、IMS/VoLTE | 先做到“枚举且不复位”，再做 SIM/数据；不稳则保持 mask |

## 6. Android 当前可采集 vs Linux 启动后

| 阶段 | 可采集/验证 | 能说明什么 |
|---|---|---|
| **Android（root，只读）** | `/proc/device-tree/compatible`、`qcom,msm-id`、`qcom,board-id`；`getprop`；`fastboot getvar`；`/sys/class/typec` 角色；`lsusb -t`/`lspci -nn`；`dmesg` 的 panel/dsi/goodix/aw882/wcd；`/sys/bus/i2c/devices`；`power_supply` uevent；WCN PCI ID；`mmcli`/`mhi`/`qrtr`/`rmtfs` 日志；`lsblk`/GPT；机身标签与口位照片 | 这些都是硬件配置、固件与厂商实现的证据；**不能证明 Linux 驱动可用** |
| **Linux 启动后（项目）** | DRM panel probe/mode set/underrun；触控与笔；音频路由；USB 角色/DP/PD；充电/旁路/s2idle；Wi-Fi soak；modem/SIM/数据 | TB324ZC 目前无公开 Linux 启动证据；上述全部属于待做项，不是已验收项 |

## 7. 未决项

1. **面板批次**：实机是否确为 RM693A0/天马？与下游 `dvt2`/`dsc` 哪个节点对应？——用实机 panel ID、vendor 校准文件、开机 dmesg 关闭。
2. **触控/笔**：Goodix 控制器型号、固件版本、笔协议与中断/reset GPIO。——用 SPI/I2C 枚举、`dmesg`、笔事件关闭；主线 `goodix` 是否匹配尚不知。
3. **音频**：AW882xx 的 chip ID/地址/复位/供电，Codec 实际是 WCD9395 还是 9378/937x。——用 i2c 扫描、`/proc/asound/cards`、dmesg 关闭。
4. **USB 逐口能力**：C1/C2 谁是 SS+DP、谁是 USB2；PD/PPS/OTG；mux/repeater。——用两口分别插充电器、Hub、U 盘、DP 转换器的矩阵测试关闭；不预设分辨率/功率档位。
5. **电源**：电池设计容量/曲线、充电与旁路阈值、热区；零售页 68 W 是否真实。——用 `power_supply` uevent 与充电实测关闭，不作硬性承诺。
6. **5G**：modem 固件/mcfg、IPA/SMEM、SIM 槽、IMS；初始化卡住是否会复位整机。——用 `mmcli`、qrtr/mhi 日志与持续观察关闭；不可控就保持 mask，与 TB323FU 现状一致。
7. **启动/解锁**：ABL 版本、GBL/efisp 条件、AVB/vbmeta 行为、回滚路径；官方 `sn.img` 是否恢复。——用 `getvar`、ABL 版本、EDL 备份可恢复性关闭；伪解锁与真解锁分开记录。
8. **刷新率**：本分支的 90/165 Hz 需要在本分支上重跑并记录 mode/underrun/肉眼结果，不能引用 A 的 25 s 164 Hz 记录；90 Hz 花屏是否可复现、与面板时序还是其他链路相关。——用同一台 TB323FU 的模式列表、underrun 计数、长时间观察关闭。
9. **SKU**：实机是 24 GB/1 TB 还是其他组合；内存大小影响 DT memory 节点。——用 `getprop`/`/proc/meminfo`/分区表关闭。
10. **官方手册缺口**：手册只给 USB-C1/C2 名称，没有逐口能力表；是否需要向官方索取快速入门/规格页。——目前只能按“未证实”记录。

## 8. 证据链接与日期口径

| 来源 | 用途 | 日期/说明 |
|---|---|---|
| <https://iknow.lenovo.com.cn/detail/442112> | 官方手册详情页（SPA） | 接口 `createTime 2026-09-01` |
| <https://iknow.lenovo.com.cn/api/knowledge/knowledgeDetails?knowledgeNo=442112> | 手册正文/版本/PDF 入口 | 本次读取成功 |
| <https://chinakb.lenovo.com.cn/chinakb/prod-api/file/downloadFile?key=uniko%2FFILE%2Ff20b8dab31ac68386a5d348de6ecb147-1788224895457.pdf> | 官方用户指南 V1.0 PDF | 47 页；`CreationDate 2026-08-31`；第 38 页 USB-C1/C2 |
| <https://www.lenovo.com.cn/wiki/product-1056713.html> | 官方规格（屏幕/电池/双 Type-C 等） | 页面 2026-10-18；访问 2026-10-19 |
| <https://item.lenovo.com.cn/product/1056713.html> | 官方商城规格表 | meta 2026-10-08；访问 2026-10-19 |
| <https://browser.geekbench.com/v7/cpu/126667> | TB324ZC / `wuji_prc_consumer_5G` / QTI SM8850 | 上传 2026-08-13 |
| <https://xdaforums.com/t/tb324zc-lenovo-y700-infinite-5g-no-volte-voice-calls-in-europe-bootloader-unlock-email-issue.4801455/> | 解锁邮件、GBL、ABL 165/187、VoLTE | 2026-09-13，社区报告 |
| <https://xdaforums.com/t/lenovotab-legion-y700-wuji-model-tb324zc-24-gb-ram-1-tb-nyc-user-tips-unlock-root.4802670/> | 24 GB/1 TB SKU、ZUXOS、root 讨论 | 2026-09-24，社区报告 |
| <https://mirrors.lolinet.com/firmware/lenowow/2026/Legion_Y700_5G/TB324ZC_CN/> | 固件目录 | 访问 2026-10-19；不含 Linux |
| <https://github.com/Lenovo-SM8850/android_kernel_lenovo_sm8850-devicetrees/commit/5c08d1c398baca77151fb5c355e799049fa1244d> | wuji Android DT | **author 2026-10-08T18:17:25Z；committer 2026-10-17T03:35:04Z** |
| <https://github.com/Lenovo-SM8850/android_kernel_lenovo_sm8850-devicetrees/blob/lineage-24.0/lenovo/wuji-canoe-base.dts> | `lenovo,wuji`/`qcom,canoe`、msm-id 0x294 | 2026-10-19 读取 |
| <https://github.com/Lenovo-SM8850/android_kernel_lenovo_sm8850-devicetrees/blob/lineage-24.0/lenovo/wuji-canoe-overlay-display.dtsi> | RM693A0 面板节点、120/165/144/60/30 timing | 2026-10-19 读取 |
| <https://github.com/Lenovo-SM8850/android_kernel_lenovo_sm8850-devicetrees/blob/lineage-24.0/lenovo/wuji-canoe-overlay-audio.dtsi> | `aw882xx_smartpa@34/@37`、WCD 节点 | 2026-10-19 读取 |
| <https://github.com/Lenovo-SM8850/android_kernel_lenovo_sm8850-devicetrees/blob/lineage-24.0/lenovo/wuji-canoe-overlay-input-sensors.dtsi> | `touch@0`（`qupv3_se19_spi`） | 2026-10-19 读取 |
| <https://github.com/Lenovo-SM8850/android_kernel_lenovo_sm8850-devicetrees/blob/lineage-24.0/qcom/canoe-usb.dtsi> | 单个 `ssusb@a600000` + QMP USB3/DP PHY | 2026-10-19 读取 |
| <https://github.com/Lenovo-SM8850/android_device_lenovo_wuji/blob/cnb/proprietary-files.txt> | Goodix 触控固件/服务、AW882xx 校准文件 | 2026-10-19 读取 |
| <https://github.com/miner7222/LTBox/commit/b4dd78f4f62d935ef398cbe213c43baf3de9809> | 单口→双口修正 | 2026-09-10；领队已核验 |
| <https://github.com/miner7222/LTBox/commit/2002864b0211ccfb8667f30a67d8c2560ca7eca8> | 首次加入 TB324ZC | 2026-09-09 |
| <https://github.com/miner7222/LTBox/blob/9ac1ad2ca2cb48edffeb3f52aa424a5a5aa2f642/crates/ltbox-core/src/model/capabilities.rs#L130-L142> | TB324ZC 能力表（双口） | 2026-10-05 |
| <https://github.com/yu1101610062/y700-wuji-droidspaces-kernel> | 原厂 GKI 6.12.38 重编译，非原生 Linux | 2026-10-05 |
| <https://github.com/yapixel/wuji_ksu_workflow> | KernelSU/SuSFS AnyKernel3 | 2026-10-09 |
| <https://github.com/YuKongA/ghostlock-app/commit/dfb0e841c7c6739f901372d58027ab66cf59d15e> | CVE-2026-43499 root（非解锁） | 2026-09-13 |
| <https://github.com/torvalds/linux/blob/master/Documentation/devicetree/bindings/arm/qcom.yaml> | 主线只有 `qcom,kaanapali-mtp`/`qrd`，无 `wuji`/`baldur` | 2026-10-19 读取 |
| <https://github.com/torvalds/linux/tree/master/drivers/gpu/drm/panel> | 主线无 RM693A0（有 RM69380） | 2026-10-19 读取 |
| <https://patchwork.kernel.org/project/linux-arm-msm/list/> | 原检索无 TB324ZC/baldur 补丁；本次未通过 bot 防护复核 | 2026-10-19 原检索 |
| <https://wiki.postmarketos.org/wiki/Lenovo_Legion_Y700> | 原检索为 2022 年 SM8250 机型，不是 TB324ZC | 2026-10-19 原检索；本次未复核 |

**日期口径**：`5c08d1c` 的 author date 是 **2026-10-08**、committer date 是 **2026-10-17**（GitHub API 原始值分别为 `2026-10-08T18:17:25Z` / `2026-10-17T03:35:04Z`），相差约 9 天。本文涉及该提交时一律取 author date，并在此注明 committer date；不把两者混为同一天。

**仓库内证据**：`devices/lenovo-tb323fu/README.md`（当前分支声明与已知限制）、`devices/lenovo-tb323fu/kernel/runtime-fixes/165hz.md`（165 Hz 替换说明）、`devices/lenovo-tb323fu/kernel/runtime-fixes/0109-drm-panel-nt36523-baldur-add-90-Hz-and-165-Hz-modes.patch`（替换补丁）、`devices/lenovo-tb323fu/kernel/tb323fu-linux-11a25bf8/.../kernel/patches/0109-...-90-Hz-and-164-Hz-modes.patch`（快照补丁）、`.../docs/hardware-status.md`（快照状态，2026-10-04）、`devices/lenovo-tb323fu/docs/SOURCES.md`（固定版本）。

## 9. 边界

- 本文**不新增设备支持**：不修改 `devices/`、不新增 `lenovo-tb324zc` 目录、不改构建脚本/白名单、不引入依赖。
- 本文**不移植设备树**、**不提供刷写步骤**；LTBox/EDL/fastboot/GBL/`sn.img` 的实机写入需单独评审。
- **LTBox 支持 ≠ 解锁成功 ≠ 原生 Linux**；伪解锁/AVB 处理不当会导致回滚或变砖。
- **面板/触控/音频结论是下游证据，不是全批次保证**；实机型号/批次/装配必须另核。
- **快照记录 ≠ 本分支验收 ≠ TB324ZC 成绩**；三者引用时必须带对象名与日期。
