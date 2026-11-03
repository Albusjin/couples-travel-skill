# 通用发行版 1.2.1 · Windows 输出校验修复

日期：2026-11-03。仅在隔离临时仓库修改、打包和验证，不修改发布者已安装 Skill、软链接、配置或既有分享目录；完成远端验证后删除本次临时目录与本地 ZIP。

## 根因与修复

[1.2.0 的 Actions 运行](https://github.com/Albusjin/couples-travel-skill/actions/runs/41602548150) 中，Linux/macOS 四项通过，Windows 3.11/3.13 均有三个输出校验失败：新输出、刷新后的输出和网站输出被误判为非当前版本。

根因是 render.py 对字符串的 UTF-8 字节计算哈希，却用默认文本模式写文件；Windows 将 LF 换成 CRLF，落盘字节不等于计算哈希的字节。1.2.1 先编码一次，使用同一字节内容写盘及计算哈希，不依赖操作系统分支，也不放宽损坏检测。

新增回归在每个平台模拟 Windows 文本换行，覆盖 Markdown 和网站功能输出：修复前稳定失败，修复后通过。既有文件篡改检测继续通过。Windows 用户用新版本 render 重新导出即可刷新状态，保留旧输出和原始旅行数据。

截图里的 Node 20 消息是旧 Action 运行时警告，独立于 Python 测试失败。工作流更新到 checkout v5、setup-python v6、setup-node v6，均使用 Node 24 Action 运行时，测试用 Node 仍是 24，不新增业务依赖。

## 推送前验证

- 151 项 unittest：149 通过，2 项因本机 PATH 未配置 Node 跳过；远端三系统矩阵会执行这些项目。
- 新回归覆盖模拟 Windows 换行和两种输出模式，未跳过 Windows 或删除严格断言。
- 实际 1.2.1 ZIP 52 个条目，51 个文件纳入校验；包版本、逐文件校验及完整 mock 输出流程通过。
- ZIP：153,214 字节；SHA-256：`a5808011d20fd2a7041f95a3ff280d717d6ba745f7ec88df896d4b7a13daf288`。
- 更新 README、Agent 交接版本与更新日志，保留 1.2.0 历史归档；真实网站视觉设计仍暂停。

此记录描述推送前的验证；新提交的 Windows/Linux/macOS 远端结论以 [GitHub Actions](https://github.com/Albusjin/couples-travel-skill/actions) 对应运行最终结果为准。安装和旅游服务真实查询仍需目标机独立验收。
