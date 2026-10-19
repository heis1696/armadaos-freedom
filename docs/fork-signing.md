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
| `schema_version` | `1` | 门检校验 |

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

`.github/scripts/verify-release-config.py` 是发布门检,在 `build.yml`(构建/推送前)
与 `promote.yml`(任何 registry 动作前)执行,失败即终止:

- `release.json` 能作为数据解析,字段符合上表;
- `GITHUB_REPOSITORY`(Actions 注入)与 `image_repository` 一致,不得在他名下发布;
- fork 公钥存在于 `system_files` 下对应路径,是可被 openssl 解析的 PEM 公钥;
  出现 `PRIVATE KEY`/`ENCRYPTED` 标记直接拒绝;
- `policy.json`、`registries.d` 与上述身份、公钥互相一致,上游作用域未被删改。

`--allow-missing-key` 只把缺钥降级为警告,供本地无钥自检;发布工作流不使用该参数。
本地开发构建(`build_files/build.sh`)与 PR 构建(pr.yml,不认证、不推送)不经过
门检,因此无钥也能运行。

## 构建与晋级中的自验

- `build.yml`:推送 build tag 后用 `release.json` 派生的公钥路径
  `cosign verify` 自验已推送 digest;`github.event.repository.fork` 不再跳过验证,
  fork 与上游走同一路径。签名仍按原渠道用 `SIGNING_SECRET`(cosign 加密私钥)完成,
  签的是 digest 而非 tag。
- `promote.yml`:晋级前以同一公钥、同一仓库身份验源 tag 的 digest,不通过不复制
  任何发布 tag;旧上游规范身份附加签名分支随上游工作流保留,不适用于本 fork。

## 密钥状态与待办

- `system_files/etc/pki/containers/freedom.pub` 尚不存在。在维护者提交真实公钥之前,
  两个发布工作流会明确失败——这是设计行为,不是缺陷。不得复制上游公钥充数,
  不得提交测试密钥或任何私钥;测试用临时密钥只存在于临时目录。
- 真实私钥由维护者经 GitHub `SIGNING_SECRET` 配置;本轮不设置远端 secrets、
  不生成生产私钥、不发布镜像。
- `build.yml` 的磁盘发布任务仍带 `github.event.repository.fork == false` 条件,
  而本仓库在 GitHub 上是 fork,因此磁盘发布不会触发。放开该门控需要维护者决策
  (并另行配置 R2 目标),属于发布验收范畴,不在本轮签名闭环内。

## 验证边界

`tests/fork-signing-test.sh`(自动纳入 `just test` / `tests/run-tests.sh linux`)
分三层并如实标注:

- `[config]`:真实树上的 release.json/policy.json/registries.d 数据断言,以及
  两个 workflow 的接线断言(门检先于发布动作、无 fork 跳验、自验用配置公钥)。
- `[script]`:沙箱树中门检的接受/拒绝行为——成功路径、缺钥、误交私钥、
  仓库身份不一致、fork 作用域被删/被改为 accept/被指向上游公钥、上游作用域被删、
  频道契约变更、附件配置缺失。
- `[crypto]`:环境有 cosign 时,用临时密钥做真实离线签名/验签往返(对钥通过、
  错钥失败、错 digest 失败)。cosign 按钥验签只绑定密钥与 digest,不校验 ref 中
  的仓库名——fork 身份的精确匹配由 `policy.json` 的 `exactRepository` 承担,
  这里只做配置断言。

未验证的端到端行为:真实 GHCR 推送、sigstore 附件在 registry 上的取回、设备端
containers/bootc 按 policy 拒绝的运行时表现。这些依赖远端发布证据,按
`docs/fork-maintenance.md` 的约定,在没有实机验收前不报告发布成功。
