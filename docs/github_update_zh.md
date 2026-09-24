# 将 GitHub 原版更新为 316 组版本

已于 2026-09-24 实时核对：jiasiqi312/dsa5208 的 master 和 HEAD 都为 b26b383d1ed2bccbb4e15ce4d1570f984e2a227b。本说明和补丁按这个版本制作。

## 需要改什么

| 文件或目录 | 修改目的 |
| --- | --- |
| src/project1/checker.py | 缺少必要证据时返回 INCONCLUSIVE；MW/WFR 使用实际依赖和经验证的局部探针，不用 seq 排序证明执行顺序 |
| src/project1/cassandra_executor.py | 去除额外审计写对业务结果的干扰；保存实际返回的 write ID、协调节点和异常；记录配置，关闭自动请求重试 |
| src/project1/failure_control.py、Docker 配置 | 只阻断节点间通信，保留客户端连接；为 iptables 和实验运行提供对应容器配置 |
| scripts/run_real_experiments.py | 初始化、MR 新值前提、故障生效验证、实际工作负载和测量/恢复辅助实现 |
| scripts/reproduce_independent.py | 按原计划顺序执行新的独立流程实验；可指定 36 或 316 组，此次不必运行 |
| scripts/summarize_completed.py | 离线重放并核对已有 316 组，不启动数据库 |
| CLI、模拟夹具及测试 | 区分模拟数据和真实实验，配合新的证据规则；28 项测试通过 |
| 报告、README、results/final-316-20260924/ | 与实际完成的实验对应，保留意外结果及局限 |

runner.py、model.py、executor.py 的原有框架不变。代码补丁共涉及 20 个文件，包含代码、配置和测试；不是“只改几行”，也不是另起一个项目。使用的是已经产生这 316 组记录的核心实现，未加入未执行的自动集群重启方案。

## 已准备的文件

- 01-code.patch：代码、配置、测试和两个复现/核验入口。
- 02-report-and-evidence.patch：报告、文档、316 组证据、两个执行阶段的来源记录。
- validation.json：在干净基线副本中实际应用两个补丁后的校验结果。
- 新 PDF：output/pdf/DSA5208_Experiment_Report_316.pdf。

这两个补丁是同一套提交内容。采用新报告时需要同时保留对应代码；不能将 GitHub 原版代码描述为 316 组结果的生成程序。大规模原计划仅作为历史来源保留，不代表完成了 1,080 组。

## 在这台 Mac 上具体操作

下面会新建一个副本，不覆盖当前有未提交修改的 /Users/miaaa/code/dsa5208。若目标目录已经存在，请换一个新目录名。

### 1. 克隆你的仓库，建立审阅分支

~~~bash
git clone https://github.com/jiasiqi312/dsa5208.git /Users/miaaa/code/dsa5208-github-316
cd /Users/miaaa/code/dsa5208-github-316
git switch -c review-316
git rev-parse HEAD
~~~

最后一条应显示 b26b383d1ed2bccbb4e15ce4d1570f984e2a227b。若不同，先重新比较，不要强制应用。

### 2. 应用代码补丁并提交

~~~bash
git apply --check /Users/miaaa/code/dsa5208/output/github-update/01-code.patch
git apply --index /Users/miaaa/code/dsa5208/output/github-update/01-code.patch
git diff --cached --stat
git commit -m "Fix consistency evidence and add independent experiment runner"
~~~

git apply --check 仅检查；下一条才将补丁写入工作区并暂存。若任一命令报错，先处理错误，不要继续提交。git commit 只产生本地提交，不会上传 GitHub。如果 Git 提示没有作者身份，请设置你自己的姓名和邮箱后再提交。

### 3. 应用报告和已有数据，离线核验后提交

~~~bash
git apply --check /Users/miaaa/code/dsa5208/output/github-update/02-report-and-evidence.patch
git apply --index /Users/miaaa/code/dsa5208/output/github-update/02-report-and-evidence.patch
python3 scripts/summarize_completed.py
git diff --cached --stat
git commit -m "Add 316 completed experiments and updated ElegantPaper report"
~~~

离线核验需要 Python 3.11+，无需启动 Docker。正确输出应包含 valid: true、histories: 316，以及 172 PASS、38 VIOLATION、106 INCONCLUSIVE。如果失败，请停下检查。

需要自己再检查单元测试时：

~~~bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev,cassandra]'
pytest -q
~~~

这一步也不启动数据库。预期为 28 passed。

### 4. 上传到你的分支

~~~bash
git push -u origin review-316
~~~

这是上述步骤里真正上传 GitHub 的动作。如提示登录，需要使用有权访问 jiasiqi312 仓库的账号完成认证；不使用之前已经过期的设备验证码。

上传后先把 review-316 分支链接分享给队友。要合并到你自己的 master，可在 GitHub 创建 PR，选择 base 为 jiasiqi312/dsa5208 的 master、compare 为 review-316。若最后需要合并回 Erchiusx 的原仓库，再从这个 fork 分支向原仓库创建跨仓库 PR。不要 force push。

## 给队友看的 PR 描述

> 保留原来的 trajectory → runner → executor → checker 框架，修正 MW/WFR 证据不足和顺序审计的问题，补充有效的 MR 前提及可保留客户端访问的分区控制。报告采用实际完成的 316 组，覆盖全部 36 种组合，每种 8–9 次；全部异常结果和两次准备阶段中断均保留。
>
> 验证：28 个单元测试通过，316 组离线重放和文件哈希核验通过。没有新增数据库实验。MW/WFR 结果限定为局部前驱可见性；两阶段准备策略不同、共享恢复历史和事后停止规则已在报告披露。

截至补丁交付，尚未向 GitHub 推送、创建 PR 或更改线上 master。

GitHub 官方 PR 操作说明：https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/creating-a-pull-request-from-a-fork
