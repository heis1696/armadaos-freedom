# Y700 无极原生 Linux：输入资料与最小验证方案

2026-10-19，基于本仓库 `13c9a77`。用户设备为原厂锁定、无 root 的 TB324ZC。
启动权限前提见[启动路线](y700-wuji-boot-options.md)；本方案没有新增设备支持，
没有生成、运行或发布可刷入镜像。

## 技术判断

保留本项目 bootc + FEX/Proton + Gamescope 的方向，先建立 wuji 的板级验证环境。
TB323FU 的固定主线补丁可作为 SoC 层参考，但不能直接把其 DTB、面板时序、
内存布局和 boot 产物换个名称给无极使用。第一份实验产物应以最小 initramfs、
明确的日志出口和可返回 Android 为目标；完整游戏会话排在内核与基础图形验证之后。

这轮取得两项比原调查更明确的数据：下游触控声明为 **`gt9976n_thp`**，并有
`thpd`/`libgdix_*` 用户态依赖；RM693A0 的面板高度表达式可还原为 **2560**，
不能把空字符串字面量误判为缺失参数。

## 已固定的源码输入

| 输入 | 固定版本 | 用途 |
| --- | --- | --- |
| 本仓库 TB323FU 板级快照 | `11a25bf89b65fff48112a91a0b25bc247e7736d8` | Linux 7.3-rc4 基线和 SoC 补丁参考；不是无极验收 |
| Lenovo-SM8850 Android DT | `5da14b86b423d4e25839e6c68da800bd6bb35ef2` | 已完整检出核读，wuji 板级引脚、供电、面板、触控参考 |
| Lenovo-SM8850 wuji Android 设备配置 | `a523431dc8dd57c05cffea1eba0710de01d6139f` | 软件依赖与固件清单，不等于主线驱动 |
| Linux 上游核查点 | `c03c1a14507dfaf8b856c2608f9ac216021fc222` | 检查 panel Makefile 与 Goodix Berlin SPI 匹配表；不作为未经评估的新内核基线 |
| 本仓库 Mesa | `packages/mesa/BASE.env` 的 26.2.4、固定 SHA-256 | 原生图形候选；仍需对实际 GPU ID 和驱动路径验证 |

## 必须区分 Android DT 与主线 DT

Android 树的 `lenovo/wuji-canoe-base.dts:25` 声明：
`compatible = "lenovo,wuji", "qcom,canoe"`，`msm-id=<0x294 0x20000>`。
overlay 另外带 QRD model/board-id，说明选择 base 与 overlay 的组合也是输入契约，
不能只复制一个文件。它依赖 QTI techpack，主线则使用 kaanapali 的绑定与驱动，
不能只替换 compatible 字符串而保留整套 Android 节点。

| 子系统 | 已找到的内容 | 仍需验证的工作 |
| --- | --- | --- |
| 最小启动 | base/overlay 身份、SM8850 家族信息 | 本机 boot 布局、页大小、DT 选择、reserved-memory、内存容量、PSCI、时钟/中断与固件接口 |
| 显示 | `wuji-canoe-overlay-display.dtsi:6591`、`:6833` 两个 RM693A0 节点，reset/TE、供电引用、DSC 和 DCS 命令 | 当前面板版本、完整供电顺序、主线 panel 驱动与双 DSI/DSC 绑定；首次只验证一个保守模式 |
| 触控 | `wuji-canoe-overlay-pmic-storage.dtsi:1894` 为 `gt9976n_thp`，SPI19、30 MHz、reset GPIO7、IRQ GPIO158、供电引用 | 驱动协议、固件、THP 用户态处理与输入事件；不能直接套主线 Berlin 驱动 |
| GPU | TB323FU 快照记载 Adreno840；共享 MSM/Freedreno/Turnip 方向 | 无极实际 GPU ID、匹配固件、IOMMU、OPP 与电源域；先 Vulkan 小例程后 Gamescope |
| USB | 板级双口/mux 线索，单个 dwc3 控制器 | 两口的连接器映射、供电、host/gadget 角色及可用诊断通道；不预设两口全功能 |
| 音频/电源 | AW882xx、PMIC/电池/热区的 Android 配置 | 按本机绑定与校准验证，不迁移 TB323FU 的增益/充电/热参数作为默认值 |
| Wi-Fi/BT | Peach 家族配置与已有 ath12k/btqca 路线 | 本机固件、BDF/校准、PCIe/供电及休眠恢复 |
| 5G | IPA、modem 与蜂窝硬件信息 | 独立验证 remoteproc/IPA/固件/用户态；不纳入首个原生版本的默认完成条件 |

### 面板字段不是“空值”

固定 Android DT 中 `qcom,mdss-dsi-panel-height = "", "", "\n";` 的三个
NUL 结尾字符串组成 `00 00 0a 00`，按 32 位大端读取为 `0xA00=2560`；
`panel-width=<0x640>` 为 1600。同类 `"", "", "d"` 则为 `00 00 64 00`，
不能靠字符串表面含义解释。这里做了字节级还原，没有编译整个 DT 树。

源码已有 on/off DCS 命令和多个模式，适合用于设计驱动；仍需跟踪其供电 phandle、
`lenovo,oled-power-sequence` 行为与实际面板选择。上游核查点的 panel Makefile
列有 RM69380，但未列 RM693A0；不同型号不能仅凭名称相近替换。

### 触控不是只需“打开 Goodix 配置”

`device.mk:181` 起包含 `thpd`、`libgdix_afe`、`libgdix_tsa`、`libgdix_tsc`、
`libgdix_tsd`；recovery 配置也引用 `thpd-goodix-recovery`。与
`gt9976n_thp` 节点组合后，应调查内核接口与用户态处理链。
上游核查点 `goodix_berlin_spi.c:175` 起匹配 GT9897、GT9916，没有这个 compatible。
这不证明协议完全不兼容，但足以否定“直接启用通用驱动即可”的结论。
早期原生验证可先使用已验证 USB 端口的键鼠/手柄，触控作为独立子任务。

## 图形与 Steam 的分层验收

本仓库 `packages/mesa-android/build.sh:87` 明确使用 `-Dfreedreno-kmds=msm`：
Android 构建产物也面向这里的 MSM 路径，不能据目录名就认为适配原厂 Android KGSL。
Droidspaces 的固定图形文档则要求容器取得 GPU 节点，并使用适合 Android 容器的
Mesa/Turnip，示例为 `MESA_LOADER_DRIVER_OVERRIDE=kgsl`。[4]

| 验证对象 | 通过标准 |
| --- | --- |
| 内核显示 | 正确模式点亮、framebuffer/DRM 状态与日志一致；先不追求165Hz |
| Vulkan/OpenGL | 确认硬件 GPU 与实际驱动，不把 llvmpipe 软件渲染当加速成功 |
| Gamescope | 分开记录原生会话与 Android/Wayland 下可能的嵌套实验，验证图形和输入权限 |
| FEX/Proton | 先独立验证 CPU 转译、来宾运行环境、图形与声音，再验证具体游戏 |
| Steam 会话 | 启动/退出、输入、模式切换与失败日志都可复现后，才算系统功能证据 |

Android 容器能显示桌面，不足以证明上述链路全部成立；相同 Adreno 型号也不足以
证明两个不同内核接口的 Mesa 二进制可以互换。

## 最小验证顺序

1. **身份与版本**：只读报告确认实际 SKU、固件、内核、槽位与报告的启动状态。
2. **启动输入契约**：匹配本机 boot/DT 组合与可用启动入口，先确认失败后能回到 Android。
   此条件未满足时，只做离线源码和构建研究。
3. **最小内核与 initramfs**：按主线绑定逐项建立 wuji 板级配置，选择能实际读取的日志出口。
   DT 编译通过不算启动通过；没有日志证据时不继续叠加完整发行版。
4. **基础交互与图形**：单一显示模式、可用 USB 输入、GPU 小例程；触控 THP 链单独验证。
5. **系统用户态**：Wi-Fi、电源/热管理、声音可验证后再接入 Armada 根文件系统和游戏会话。
6. **整机验收后发布**：冷启动、返回 Android、休眠、外设恢复、安装/更新/回退按实际设备记录。
   5G/VoLTE 作为独立能力说明，不能用原厂 Android 的5G成绩代替 Linux 验收。

## 可复核的来源

1. [固定 Android DT 树](https://github.com/Lenovo-SM8850/android_kernel_lenovo_sm8850-devicetrees/tree/5da14b86b423d4e25839e6c68da800bd6bb35ef2/lenovo)：base、overlay-display、overlay-pmic-storage、overlay-input-sensors。
2. [固定 Android device.mk](https://github.com/Lenovo-SM8850/android_device_lenovo_wuji/blob/a523431dc8dd57c05cffea1eba0710de01d6139f/device.mk#L181)。
3. [上游 panel 构建表](https://github.com/torvalds/linux/blob/c03c1a14507dfaf8b856c2608f9ac216021fc222/drivers/gpu/drm/panel/Makefile)、[Goodix Berlin SPI](https://github.com/torvalds/linux/blob/c03c1a14507dfaf8b856c2608f9ac216021fc222/drivers/input/touchscreen/goodix_berlin_spi.c#L175)。
4. [Droidspaces 图形配置](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/Documentation/Graphics-and-Audio.md#turnip)。
