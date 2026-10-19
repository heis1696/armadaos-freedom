# Y700 无极：从原厂锁定状态选择验证路线

查询日期：2026-10-19。用户已确认设备为 TB324ZC、原厂、Bootloader 未解锁、无 root；
完整 ZUXOS 版本和内核版本尚未提供。本文件是研究结论，不是刷写操作指南。

## 建议

先用[只读采集工具](y700-wuji-readonly-check.md)确认型号、系统完整版本、内核 build
和系统报告的启动状态。保留原生 ArmadaOS 为项目目标；将 Android 容器路线作为
另一种验证环境单独评估。当前没有证据支持在这台原厂锁定设备上直接使用现成
ArmadaOS 或第三方 boot 镜像。

| 路线 | 当前设备能否直接进入 | 必须先解决的条件 | 能验证什么 |
| --- | --- | --- | --- |
| 原厂 Android + 只读 ADB | 可以准备；需电脑已有 adb、USB 调试授权 | 采集准确固件和内核版本 | 为后续方案选基线，不改变启动链 |
| Termux/PRoot 用户态 | 项目设计上不要求 root；本机尚未运行验证 | 安装普通 Android 应用并验证用户态工具 | Linux 命令行/部分应用；不能验证 bootc 系统、原生内核和完整服务栈 |
| Android GKI + Droidspaces | 不满足现有前提 | root、符合要求的内核配置、原厂模块 KMI、可验证的 boot 修改与恢复路径 | Android 内核上的 Linux 容器，图形、音频、输入仍需分别验证 |
| 原生 Linux + Armada 用户空间 | 不满足现有前提 | 本机允许启动自定义内核的机制、wuji DT/驱动、启动镜像和诊断通道 | 最接近项目目标，但移植工作最多 |

PRoot 明确使用 `ptrace`，不提供真正的内核 root、完整 init、cgroup 或 namespace
隔离；因此不能以“PRoot 启动了 Fedora 用户态”作为 ArmadaOS 整机兼容证据。[4]

## 启动入口的证据

### 官方解锁

本次能读取 ZUI 官方解锁页面，页面有邮箱申请表单和 `sn.img` 通用说明。[1]
这只能证明入口存在：未提交用户申请、未确认 TB324ZC 的当前资格，也未验证该用户
固件能否使用页面给出的命令。不能将其他 Y700 代际的解锁经验移植为本机结论。

### LTBox / GBL

核读 LTBox `df92912da8aa8df5205395eb633406b3cb9d90b2`：

- `crates/ltbox-core/src/model/capabilities.rs` 的 TB324ZC 配置为
  `root_uses_gbl: true`、`requires_sahara_manifest: true`、`dual_usb: true`、
  `prc_only: true`，并关闭 `rescue` 和区域 AVB 转换。
- 该提交继承 `GENERIC.gki_root=true`，其测试明确断言 TB324ZC 的 `gki_root` 为真；
  `crates/ltbox-gui/src/workers/root.rs:65` 起的检查实际读取该能力位。
- **同一提交的 README 却仍写 TB323FU/TB324ZC 的 GKI rooting 不可用。**
  这是文档与代码的差异，不能选一边当作已验证支持。需进一步核对具体发布版本、
  固件条件及本机恢复能力。

这些证据表明工具存在相关路径，不表明原厂机已经解锁、能启动主线 Linux，或具有可靠
自动救砖能力。社区所提 ABL 165/187 条件也没有通过本机确认。没有这些确认时，不选择
“先刷一个试试”作为研究步骤。[2]

### kShimC

上游 `82ce6eaa10c36e64cfd3f16799172d854f9a955b` 将自身定义为 in-kernel bootloader，
依赖 MultiBootKernelPatcher 的 shim 协议。[6] 它提供内核内的菜单与交接机制，
不能据此视作绕过原厂启动验证的通用解锁器。本仓库的 boot 配方仍显式面向 TB323FU，
并要求设备自己的原厂 boot、内核与 DTB 输入；wuji 需要独立核对这些契约。

## Droidspaces 候选为什么不能直接套用

无极专用项目 `4eabc39d5ae1d28828859fb3fadf39d0dfde06a1` 声明：[3]

- 原厂内核为 `6.12.38-android16-5-g74ad46052215-ab14494108-4k`，基于 Google
  GKI build `14494108`，源码 tag 为 `android16-6.12-2025-09_r15`。
- 它对 namespace/SYSVIPC 等配置做 KMI 保持处理，并比较原厂模块符号 CRC、结构布局
  和版本字符串。不能只看内核大版本同为 6.12 就认为兼容。
- README 提到面向 `2.0.10.223` / `2.0.10.262` 原厂槽位输入的预打包产物。
  A/B 槽是作者当时的输入条件，不是所有用户设备的固定版本映射。
- 作者记录 v1 的 AVB footer 处理造成反复启动失败；v2 改用保留原厂签名元数据的方式。
  此处只记录作者经验，没有在用户设备重现或验收。
- README 建议的临时启动测试有其启动权限前提；不能假定原厂锁定 TB324ZC 的
  `fastboot boot` 一定可用，也不能把它与相关 TB323FU 的命令能力混用。

Droidspaces 上游 `8b625e110270e2f0d32004f740b1e9a71b1f540c` 明确要求 root，
并指出许多原厂内核缺少所需配置。其 GKI 文档同样提醒某些 cgroup 选项会破坏 ABI，
不能为了“配置齐全”随意打开。[5] 当前原厂无 root 状态尚不满足该路线条件。

## 取得只读报告后的判定

| 报告/证据情况 | 处理 |
| --- | --- |
| 型号不匹配或字段未知 | 停止推导适配结论，先纠正设备选择或补充可读信息 |
| GKI 字符串与 build 14494108 完整匹配 | 可以进一步审计该候选的 KMI 和固件输入；仍不能直接选镜像 |
| 仅 ZUXOS 名称相近，或 GKI build 不同 | 按新的原厂基线重新评估，不以降级匹配现成镜像为默认方案 |
| 系统报告 locked/green | 作为原厂状态线索；不能仅凭这些属性证明某种修改已成功或不存在 |
| 找不到匹配启动入口和可验证恢复路径 | 继续离线源码研究，设备保持原状 |

## 来源

1. [ZUI 官方解锁入口](https://m.zui.com/iunlock)，2026-10-19 只读访问，未提交申请。
2. [LTBox 固定提交](https://github.com/miner7222/LTBox/tree/df92912da8aa8df5205395eb633406b3cb9d90b2)：README、能力表与 root worker；上述文件在同一提交核对。
3. [无极 Droidspaces GKI README](https://github.com/yu1101610062/y700-wuji-droidspaces-kernel/blob/4eabc39d5ae1d28828859fb3fadf39d0dfde06a1/README.md)：兼容范围、KMI 验证与 AVB 历史。
4. [PRoot-Distro 固定 README](https://github.com/termux/proot-distro/blob/5a427a1f924550c176ab34197e9fcf5d010fdbd9/README.md#limitations)：无 root 用户态能力及限制。
5. [Droidspaces 要求](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/README.md#requirements)、[内核配置](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/Documentation/Kernel-Configuration.md)。
6. [kShimC 定义](https://github.com/sunflower2333/kShimC/blob/82ce6eaa10c36e64cfd3f16799172d854f9a955b/README.md)；本仓库 `devices/lenovo-tb323fu/boot/star-chart-build/README.md`。
