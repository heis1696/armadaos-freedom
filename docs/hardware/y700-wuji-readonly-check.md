# 无极原厂状态的只读信息采集

适用于手上的 TB324ZC：原厂、未解锁、无 root。首要问题是完整 ZUXOS 版本和原厂
内核 build 是否与公开候选相符；仅凭“第五代骁龙”或“内核6.12”不够。

## 准备

- 电脑安装 Python 3.9+，准备 Google 的 [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools)。脚本不安装工具。
- 若愿意采集，在平板开发者选项启用 USB 调试，连接电脑，并在平板上确认授权。
  不需要打开 OEM 解锁，不需要 root，也不需要进入 fastboot。
- 默认只连接这一台 Android 设备。多设备、未授权或离线时脚本会停止。

## Windows 运行

在本仓库根目录打开 PowerShell，按实际位置替换 adb 路径：

```powershell
python tools/diagnostics/collect_android_identity.py --adb "C:\Android\platform-tools\adb.exe"
```

默认在电脑临时目录新建 `wuji-identity-*/identity.json`，成功后输出文件位置。
也可以指定仓库外的新文件：

```powershell
python tools/diagnostics/collect_android_identity.py --adb "C:\Android\platform-tools\adb.exe" --output "$env:USERPROFILE\Desktop\wuji-identity.json"
```

已有同名文件会被拒绝覆盖。高级用法可用 `--serial` 选择连接；连接标识只用于内存中的
ADB 目标选择，不进入报告。无需把该参数或 `adb devices` 的原始输出发给别人。

如果暂不使用 USB 调试，可以先手动提供“设置 → 关于平板”中的型号和完整 ZUXOS 版本，
内核版本若能看到也一起记录。

## 报告含义

| 字段 | 用途 |
| --- | --- |
| `ro.product.model/device/board` | 产品身份与板级线索 |
| `ro.build.display.id`、`ro.build.version.incremental`、`ro.build.fingerprint` | 系统构建版本；这些是软件版本标识 |
| `kernel_release` | 核对原厂 GKI 的完整版本字符串与 build |
| `ro.bootloader` | 系统可读到的 bootloader 版本线索；为空则未知 |
| `ro.boot.flash.locked`、`ro.boot.vbmeta.device_state`、`ro.boot.verifiedbootstate` | Android 报告的启动状态，不能单独证明解锁或修改情况 |
| `ro.boot.slot_suffix` | 系统报告的当前槽位，不能据此推断另一个槽位的版本 |
| `target_match` | 仅检查产品属性里是否有准确 TB324ZC 标识，不表示已支持 Linux |

字段状态 `unknown` 表示空值、权限限制、超时或查询失败，不猜测缺失数据。
`not_matched` 或 `unknown` 的设备身份应先人工核对，不据此选择镜像。

建议先反馈 `ro.build.version.incremental`、`ro.build.display.id`、`kernel_release`
及三个启动状态字段的值/未知状态即可，无需发送整个报告。

## 行为范围与验证

工具只执行 `adb devices`、选定设备上的白名单 `getprop <单个属性>` 和 `uname -r`。
它不运行 `su`、重启、刷写、APK 安装、设置变更或全量信息转储；不收集序列号、IMEI、
MAC、账号。连接标识只作内存中的设备选择；原始 ADB 错误输出不写入报告或日志，
如果属性异常回显连接标识也会替换为 `[redacted]`。报告只写电脑，工具不上传数据。

测试使用 fake adb，覆盖未授权、离线、多设备、超时、错误脱敏、型号边界和文件防覆盖：

```powershell
python -B tests/android-identity-test.py
```

本次没有连接或采集用户的真实设备。脚本测试通过不代表已核对本机固件，更不代表完成
Linux 启动验证。后续判断见[启动路线](y700-wuji-boot-options.md)和[原生适配方案](y700-wuji-native-linux-plan.md)。
