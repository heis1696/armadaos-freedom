# Fork 维护约定

本 fork 使用 `ghcr.io/heis1696/armadaos-freedom` 作为系统镜像身份，继续沿用
Fedora bootc、现有容器软件包和 Cosign 发布流程。以下是更新与安装保护的实现约定，
不是已完成发布或设备验收的声明。

## 发布配置

唯一的 fork 发布元数据位于 `system_files/usr/share/armada/release.json`，安装后为
`/usr/share/armada/release.json`。字段约定：

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 当前为整数 `1` |
| `image_repository` | 不带 tag/digest/transport 的完整镜像仓库名 |
| `channels` | 当前为 `stable`、`beta`、`testing`，不把未知 tag 自动改成其中之一 |
| `public_key_path` | 镜像内的公钥文件路径，当前为 `/etc/pki/containers/freedom.pub` |

配置必须作为数据解析，不能作为 shell 脚本执行。运行时不接受普通用户环境变量来替换
仓库身份或信任密钥；测试使用临时配置和进程隔离。

## 更新来源

从已启动镜像的准确仓库身份决定更新目标。配置中的 fork 仓库支持 Steam 频道选择；
上游和旧上游的已有兼容行为分别保留，不能将它们悄悄切换到 fork。
外部仓库的显式开发 tag 可保持原仓库与 tag；无法解析的、本地存储等来源不能自动
回退到上游或 fork。仅有 digest 而没有可确定频道的来源应明确报错。

## 签名

fork 的发布、晋级与客户端策略使用相同的仓库身份和公钥。上游公钥只用于上游，
不能用来验证本 fork 的自有签名。缺少 fork 公钥时，对该仓库的客户端策略应明确拒绝；
生产发布须在构建和推送前检查配置及公钥，不因 `repository.fork` 而跳过签名自验。

真实签名私钥由维护者管理，沿用 GitHub `SIGNING_SECRET` 的配置渠道；本轮不生成
生产私钥、不设置远端 secrets、不发布系统镜像。公钥可以作为公开文件提交到
`system_files/etc/pki/containers/freedom.pub`。测试用临时密钥不能进入产品镜像。
本地开发构建和无密钥的 PR 测试应可运行，但不能伪装成可发布且已验签的镜像。

## 平板安装保护

当前 TB323FU 和 TB324ZC 都没有通过通用安装器的整机安装验收。先依据真实 device tree
的型号和板级 compatible 拒绝这两个已知不兼容目标，在磁盘探测、分区、格式化或
引导文件写入前返回可理解的错误。GUI 与直接后端调用都需检查；`--device`、`-y`
和 `ARMADA_MODEL` 等环境变量不能绕过。

这是一项针对已知不支持平板的保护，不是全设备支持白名单。完整的
“设备—源镜像—分区布局—启动格式”契约仍需逐机型证据；本次不据此新增任何机型支持。

## 验证与待配置事项

- 更新测试覆盖 fork 频道、上游兼容、外部开发 tag、digest 来源和非法/本地来源。
- 安装拒绝路径覆盖 GUI、直接后端、显式设备和无人值守参数；断言写盘与启动文件写入零调用。
- 发布检查覆盖缺公钥、配置与仓库不一致、验证失败，保留正确签名/错钥/错身份的实际验证边界。
- 真实公钥、GitHub 发布 secret、GHCR/R2 发布目标和实机验收另行配置；没有这些证据时不报告发布成功。
