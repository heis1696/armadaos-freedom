# Fork 更新运行时约定

本文说明本 fork 的更新目标如何从 `system_files/usr/share/armada/release.json`
（安装后为 `/usr/share/armada/release.json`）解析。发布 workflow、容器签名策略和
`release.json` 字段不在本文范围内；签名/安装保护见
[fork 维护约定](fork-maintenance.md)。

## 配置读取

`system_files/usr/lib/armada/release_config.py` 是唯一的读取与校验入口，
`update-lib` 通过 `python3` 调用它，不 `source`、不 `eval` JSON。校验内容包括：

- `schema_version` 必须是整数 `1`；缺字段、未知字段或重复字段均拒绝。
- `image_repository` 必须是不带 tag、digest、transport 的小写
  `registry/namespace/name`。
- `channels` 必须是非空、无重复、仅含 Steam 可映射 token 的列表
  （`stable`、`beta`、`testing`）。
- `public_key_path` 必须是绝对且不含 `.`/`..` 组件的路径。

配置路径和 helper 路径是普通 shell 变量，生产代码不接受环境变量来替换仓库身份或
密钥；测试可在 source 后显式改写，或直接调用
`release_config.load_release_config(path)` 和临时副本。

## 更新目标

`armada_update_target` 从已启动镜像的 container-image-reference 解析：

| 启动来源 | 目标仓库 | 频道/标签 |
| --- | --- | --- |
| 配置中的 fork 仓库 | 配置的 `image_repository` | 配置 `channels` 中的已选频道；显式非频道 tag 原样保留 |
| `ghcr.io/armada-os/armada` | 原仓库 | 原有 `stable`/`beta`/`testing` 行为 |
| `ghcr.io/virtudude/armada` | 原仓库 | 原有 `stable`/`beta`/`testing` 行为 |
| 其他网络仓库 | 原仓库 | 仅保留显式 tag，不参与 Steam 频道选择 |

规则细节：

- `containers-storage:`、`oci:`、`dir:`、`docker-archive:` 等本地或非网络 transport
  直接拒绝，不会回退到上游或 fork。
- 无法解析的来源、空引用、以及缺少已启动 tag 的外部来源都报错。
- 只有已确认可信的仓库（fork、上游、旧上游）才接受 digest 来源；且必须有已选频道
  或已启动 tag 才可确定目标。外部仓库的 digest 一律拒绝。
- 频道状态文件只接受该仓库允许列表中的精确匹配值；损坏的多词值不会被当成 tag。
- 发布元数据缺失、损坏或 schema 不合法时更新目标解析失败（fail closed），不静默
  使用 `ghcr.io/armada-os/armada`。

`armada-select-branch` 的 `-l`/`-c`/选择路径使用同一份仓库与频道列表；fork 只列出
配置声明的频道。`armada_os.py` 从同一个加载函数取得 UI 频道，映射为
`stable`/`beta`/`preview`。

## 验证边界

已覆盖的回归：

- `tests/release-config-test.py`：配置缺失、损坏、重复/未知字段、schema、仓库、
  频道和公钥路径校验，以及 helper CLI 输出。
- `tests/update-migration-test.sh`：fork 频道、上游/旧上游兼容、外部显式 tag、
  可信/不可信 digest、本地与非法来源、缺失/损坏配置。
- `tests/desktop-update-test.py`：Steam 频道选择与 fork 频道列表。
- `tests/armada-os-test.py`：UI 侧 fork 频道列表来自配置。

这些测试在 Ubuntu WSL 中执行，不依赖真实镜像仓库或签名密钥。以下范围未验证：
真实 GHCR 拉取/切换、Cosign 验签、fork 公钥在 `policy.json` 中的策略接入、以及
实机升级。特别是本单未修改 `policy.json`/sigstore 配置，`bootc switch
--enforce-container-sigpolicy` 指向 fork 仓库前仍需另一项签名策略工作。
