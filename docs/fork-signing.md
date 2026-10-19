# Fork 签名闭环

本 fork 的发布、晋级与客户端信任使用同一仓库身份(`ghcr.io/heis1696/armadaos-freedom`)
和同一公钥。本文描述已实现的配置闭环与它的验证边界;`docs/fork-maintenance.md`
中的发布约定不变。

## 身份与信任配置

唯一的发布元数据是 `system_files/usr/share/armada/release.json`:

| 字段 | 当前值 | 被谁消费 |
| --- | --- | --- |
| `image_repository` | `ghcr.io/heis1696/armadaos-freedom` | 发布门检、`policy.json` 作用域、sigstore 附件配置 |
| `public_key_path` | `/etc/pki/containers/freedom.pub` | 客户端策略 `keyPaths`;源码对应 `system_files/etc/pki/containers/freedom.pub` |
| `channels` | `stable`、`beta`、`testing` | 门检按契约集合校验,改动视为身份契约变更 |
| `schema_version` | `1` | 门检经运行时 helper 校验(整数 `1`,拒绝重复字段) |

客户端配置(`system_files/etc/containers/`):

- `policy.json` 为 fork 仓库设精确作用域:`sigstoreSigned`,`keyPaths` 仅有
  `/etc/pki/containers/freedom.pub`,`signedIdentity` 为 `exactRepository` 精确等于
  fork 仓库。公钥文件缺失时,containers/image 读取 `keyPaths` 失败即拒绝镜像——
  缺钥即拒绝,不会落入 `insecureAcceptAnything` 兜底作用域。上游
  `ghcr.io/armada-os/armada` 与旧上游 `ghcr.io/virtudude/armada` 的原有规则原样保留,
  上游公钥不验证 fork 镜像。
- `registries.d/ghcr-armada.yaml` 为 fork 仓库开启 `use-sigstore-attachments`,
  使 cosign 签名随镜像一起被拉取。

## 发布前校验

`.github/scripts/verify-release-config.py` 是发布门检:

- `build.yml` 中它是一个独立的前置 job(`verify_release_config`);凡是能写
  GHCR 的任务——`packages`(推送构建包镜像)与 `build_push`——都以
  `needs` 依赖它,因此任何发布动作都只能在门检通过后开始。`build_push`
  内部在签名/推送前再跑一次同一门检,作为接线防退化。
- `promote.yml` 中它在任何 registry 动作(包括登录)之前执行。两处失败即终止。

门检内容:

- `release.json` 用与设备端相同的运行时 helper
  (`system_files/usr/lib/armada/release_config.py` 的 `load_release_config`)
  做 schema 校验——`schema_version` 必须是整数 `1`、重复字段/未知字段拒绝,
  与运行时行为一致;再叠加本 fork 契约:`ghcr.io/owner/name` 形态、频道恰为
  `stable`/`beta`/`testing`、公钥路径形态;
- `GITHUB_REPOSITORY`(Actions 注入)与 `image_repository` 一致,不得在他名下发布;
- fork 公钥存在于 `system_files` 下对应路径,且被 openssl 证明可解析为 PEM 公钥;
  出现 `PRIVATE KEY`/`ENCRYPTED` 标记直接拒绝;生产模式缺 openssl 直接失败,
  不降级为"仅检查 PEM 外观";
- `policy.json`、`registries.d` 与上述身份、公钥互相一致,上游作用域未被删改。

受保护的 fork、上游和旧上游仓库不允许额外的 tag/digest 策略覆盖项：
containers/image 使用最具体的作用域，不会继承仓库级要求。附件配置文件采用固定的
YAML 子集：唯一 `docker:` 根键、两空格仓库键、四空格的
`use-sigstore-attachments: true/false`；允许空行与整行注释，拒绝重复键、错误层级及
其他 YAML 表达形式。三个受保护仓库都必须开启附件。这是该受控配置文件的格式约定，
并非通用 YAML 解析器。

`--allow-missing-key` 只把缺钥与"无法做密码学验证"(无 openssl)降级为警告,
供本地无钥自检;发布工作流不使用该参数。本地开发构建(`build_files/build.sh`)
与 PR 构建(pr.yml,不认证、不推送、仅本地 oci-archive)不经过门检,因此无钥
也能运行。

## 构建与晋级中的自验

cosign 按钥验签只绑定密钥与 digest,不校验 ref 中的仓库名(同钥签名的他仓库
身份照样通过;测试已实证)。因此自验输出一律再经
`.github/scripts/verify-signature-result.py` 检查:已验签结果必须非空,且至少
一条签名的 `critical.identity.docker-reference` 等于目标仓库、
`critical.image.docker-manifest-digest` 等于目标 digest;错误身份或空结果
一律拒绝。

- `build.yml`:推送 build tag 后用 `release.json` 派生的公钥路径
  `cosign verify` 自验已推送 digest,并经上述 helper 核对身份与 digest;
  `github.event.repository.fork` 不再跳过验证,fork 与上游走同一路径。签名仍按
  原渠道用 `SIGNING_SECRET`(cosign 加密私钥)完成,签的是 digest 而非 tag
  (实测该形态下 payload 身份恰为裸仓库名)。
- `promote.yml`:晋级前以同一公钥、同一仓库身份验源 tag 的 digest,并经同一
  helper 核对,不通过不复制任何发布 tag;旧上游规范身份附加签名分支随上游
  工作流保留,不适用于本 fork。

## 密钥状态与待办

- `system_files/etc/pki/containers/freedom.pub` 尚不存在。在维护者提交真实公钥之前,
  两个发布工作流会明确失败——这是设计行为,不是缺陷。不得复制上游公钥充数,
  不得提交测试密钥或任何私钥;测试用临时密钥只存在于临时目录。
- 真实私钥由维护者经 GitHub `SIGNING_SECRET` 配置;本轮不设置远端 secrets、
  不生成生产私钥、不发布镜像。
- `build.yml` 的磁盘发布任务仍带 `github.event.repository.fork == false` 条件,
  而本仓库在 GitHub 上是 fork,因此磁盘发布不会触发。放开该门控需要维护者决策
  (并另行配置 R2 目标),属于发布验收范畴,不在本轮签名闭环内。
- 独立手动运行 `packages.yml` 仍可发布软件包产物；它不发布或晋级系统镜像。
  由 `build.yml` 调用时，软件包任务受前置检查约束。

## 验证边界

`tests/fork-signing-test.sh`(自动纳入 `just test` / `tests/run-tests.sh linux`)
分四层并如实标注:

- `[config]`:真实树上的 release.json/policy.json/registries.d 数据断言,以及
  两个 workflow 的接线断言(前置门检 job 先于 packages/build_push、无 fork 跳验、
  自验与晋级经 helper 核对身份与 digest)。
- `[script]`:沙箱树中门检的接受/拒绝行为——成功路径、缺钥、误交私钥、
  仓库身份不一致、fork 作用域被删/被改为 accept/被指向上游公钥、上游作用域被删、
  频道契约变更、`schema_version=true` 与重复字段被运行时 schema 拒绝、
  schema helper 缺失时门检失败、缺 openssl 生产模式失败/本地模式仅警告、
  附件配置缺失。
- `[helper]`:`verify-signature-result.py` 的接受/拒绝——精确身份与 digest
  通过,空列表、空输出、他仓库身份、错 digest、非数组输出拒绝。
- `[crypto]`:环境有 cosign 时,用临时密钥做真实离线签名/验签往返(对钥通过、
  错钥失败、错 digest 失败),并走与 CI 相同的
  "`cosign verify` 输出经 helper 检查"管线:裸仓库身份通过;同一测试密钥签出的
  他仓库(`ghcr.io/armada-os/armada`)身份在 cosign 验签下依然通过(缺口复现),
  被 helper 拒绝。测试密钥只在临时目录生成,不入库。

未验证的端到端行为:真实 GHCR 推送、sigstore 附件在 registry 上的取回、设备端
containers/bootc 按 policy 拒绝的运行时表现。这些依赖远端发布证据,按
`docs/fork-maintenance.md` 的约定,在没有实机验收前不报告发布成功。
