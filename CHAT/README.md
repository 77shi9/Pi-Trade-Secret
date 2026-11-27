# CHAT — Pi 与你的沟通文件（通过 GitHub 传递）

## 工作流（每一轮任务）

1. **Pi** 完成任务后：创建最新编号的 `round_NN.md`，写入
   「Pi 做了什么」「需要你（公司电脑）」两个部分，推送到 GitHub
2. **你（公司电脑）**：
   ```powershell
   git pull
   notepad CHAT\round_01.md        # 打开最新编号的文件
   # 在「用户回复区」下面粘贴命令输出 / 写结果
   # 保存关闭后：
   git add CHAT
   git commit -m "round 01 回复"
   git push
   ```
3. **Pi** 拉取、读取你的回复、处理并开始下一轮（创建 round_NN+1）

## 规则

- 最新一轮 = **编号最大**的 round 文件
- 文件只追加、不删除（全部留档，等于我们的工作日志）
- 贴**命令的文本输出**，不要贴二进制文件（.sqlite3 会乱码）
- 每次推送都打版本 tag，`git tag -l` 可确认推送是否成功
