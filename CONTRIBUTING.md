# 贡献指南 / Contributing

感谢帮助改进 TableProof。最有价值的贡献是一个小而明确、能够公开复现的转换差异。

## 报告问题

请提供 Python 与操作系统版本、TableProof 版本、完整命令（删除私密路径）、工作表/范围/表编号/表头选择、预期和实际状态。若问题涉及转换器，再提供名称、版本、参数和 Markdown 输出。用几行人工构造数据替代真实业务文件，注明哪些数据是合成的。不要上传秘密、个人身份信息、客户数据或生产日志。

Please include Python/OS/TableProof versions, the command with private paths removed, mapping options, expected and observed results. For conversion issues, include the converter name, version, parameters and generated Markdown. Replace real data with a minimal synthetic reproduction. Do not upload credentials or private data.

## 运行检查

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check src tests scripts
python -m build
```

新增规则先增加失败测试。预期值应独立、手工定义，不由待测转换器或待测校验器计算。支持且一致的输入应通过；确定差异应定位到正确坐标；证据不足应返回 `INDETERMINATE`。不要通过宽松匹配消除告警。

Add a failing regression test before changing a rule. Derive expected values independently of the converter and checker. Include an equal-value control and an unsupported/ambiguous case where relevant. Unknown must never become an unexplained pass.

## 范围与接口

数据比较规则和验证方式见 [验证与接口](docs/validation.md)。新格式或新推断需要明确证据边界。不要添加遥测、上传服务或隐式网络请求。公开合成样例在 `examples/`；`scripts/generate_examples.py` 可重新生成。

See [validation and interfaces](docs/validation.md) for comparison rules and reproducible checks. Keep parsing independent from conversion, preserve exact raw numeric strings, and document unverified cases. New features should not add telemetry, uploads or implicit network calls.

## 发布前检查

提交和推送前检查变更、暂存区与将推送的提交，排除真实数据、绝对个人路径和密钥。使用自己的 GitHub 关联身份，推荐已验证的 GitHub noreply 邮箱。此仓库的 CI 只测试和构建，不自动发布包或 Release。

Review files, the staging area and outgoing commits for private data and secrets. Use your own verified Git identity, preferably a GitHub noreply address. CI validates the project and builds a package; it does not publish packages or releases.
