# 🀄 Antigravity 中文汉化（antigravity-chinese）

为 **Google Antigravity** 桌面客户端（Agent Manager）注入中文翻译的**零依赖**安装器。
纯 Python 实现，无需 Node.js / npm / asar 工具，一键安装、一键还原。

> ⚠️ 非官方语言包。本工具会修改本地 `app.asar`，安装前自动备份，可随时还原。
> Antigravity 官方升级会覆盖补丁，升级后重新运行安装脚本即可。

## ✨ 特性

- **零外部依赖**：纯 Python 标准库，`python3 install.py` 即装即用
- **全界面汉化**：主界面、设置面板、侧边栏、弹窗、错误提示全覆盖（**1566 条词条**）
- **原生菜单 / 托盘翻译**：顶部菜单栏（File/Edit/View…）与系统托盘菜单一并汉化
- **跨平台**：macOS / Windows / Linux 自动探测安装路径
- **自动备份**：首次安装自动备份原版 `app.asar.bak`
- **一键还原**：`--restore` 恢复官方原版
- **macOS 自动重签名**：解决修改后“应用已损坏”问题
- **保留专有名词**：模型名（Claude Sonnet 4.6 (Thinking)）、斜杠命令（/goal）、品牌名保留英文

## 📥 安装

```bash
git clone https://github.com/<你的用户名>/antigravity-chinese.git
cd antigravity-chinese

# 安装汉化（自动探测路径）
python3 install.py

# 指定路径安装
python3 install.py --asar "/自定义路径/Contents/Resources/app.asar"

# 还原官方原版
python3 install.py --restore

# 查看状态
python3 install.py --status
```

> 安装前请先完全退出 Antigravity（脚本会检测并提示）。

## 🧩 工作原理

1. 解包 `app.asar`
2. 向 `dist/preload.js` 与 `dist/ideInstall/wizardPreload.js` 注入 DOM 翻译引擎
   （MutationObserver 实时监听 + 1566 条中英词典，属性/placeholder/title 一并翻译）
3. 向 `dist/menu.js` 注入原生菜单翻译、`dist/tray.js` 注入托盘菜单翻译
4. 重新打包（`chrome-devtools-mcp` 保持 unpacked，不影响功能）
5. macOS 自动 ad-hoc 重签名

## 📁 项目结构

```
antigravity-chinese/
├── install.py          # 主安装器（安装/还原/状态）
├── asar.py             # 纯 Python asar 解包/打包库
├── dicts/
│   ├── zh_cn.json      # 1566 条全量翻译词典
│   └── engine.js       # DOM 翻译引擎模板（含 __DICT_ITEMS__ 占位符）
├── SKILL.md            # AI 智能体技能说明（可直接作为豆包工作 Skill 使用）
└── LICENSE             # MIT
```

## 🔧 常见问题

**Q: 汉化后界面没变化？**
A: 确认已完全退出并重新启动 Antigravity（不是最小化）。

**Q: 提示“应用已损坏，无法打开”？**
A: 执行 `sudo xattr -rd com.apple.quarantine /Applications/Antigravity.app`。

**Q: 官方更新后汉化失效？**
A: 正常现象，重新运行 `python3 install.py` 即可。

**Q: 部分界面仍是英文？**
A: 新版本可能引入词典未覆盖的词条。欢迎在 `dicts/zh_cn.json` 中补充并提交 PR，
   或到 Issues 反馈缺失词条。

**Q: 如何完全恢复原版？**
A: `python3 install.py --restore`，脚本会用备份恢复。

## 🤝 贡献

- 补充翻译词条：编辑 `dicts/zh_cn.json`（`"英文原文": "中文翻译"`）
- 报告问题 / 建议：GitHub Issues

## ⚖️ 免责声明

本项目与 Google 及 Antigravity 官方团队无关，不包含 Antigravity 任何二进制内容。
修改 `app.asar` 可能违反官方服务条款，请自行评估使用风险。

## 📄 License

[MIT](LICENSE)
