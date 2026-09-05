---
name: antigravity-zh
description: 为 Google Antigravity 桌面客户端（Agent Manager）安装/还原中文汉化补丁。当用户要求“给 Antigravity 装中文/汉化”、汉化失效后重新安装、或需要还原英文原版时使用。纯 Python 零外部依赖，自动探测平台与安装路径，自动备份并支持一键还原。
---

# 谷歌反重力汉化插件（antigravity-zh）

为 Google Antigravity（Agent Manager）注入中文翻译引擎的零依赖安装器。

## 适用对象

- Antigravity 桌面客户端（Agent Manager），macOS / Windows / Linux
- 已适配版本基线：macOS 2.9.x（Electron 结构：`resources/app.asar` + `dist/preload.js`）

## 工作方式

1. 解包 `app.asar`
2. 向 `dist/preload.js` 与 `dist/ideInstall/wizardPreload.js` 注入 DOM 翻译引擎
   （MutationObserver + 全量字典，约 1560 条词条，覆盖主界面/设置/弹窗/报错）
3. 向 `dist/menu.js` 注入原生菜单翻译、`dist/tray.js` 注入托盘菜单翻译
4. 重新打包（chrome-devtools-mcp 保持 unpacked）
5. macOS 自动 ad-hoc 重签名

幂等设计：官方原版 → 注入完整引擎；已汉化版本 → 自动清理旧字典块并更新词条；
重复安装自动跳过，`app.asar.bak` 始终保留官方原版。

## 使用步骤

### 安装

```bash
git clone https://github.com/zhonghugo/antigravity-zh.git
cd antigravity-zh
python3 install.py            # 自动探测路径并安装
# 或指定路径：
python3 install.py --asar "/自定义路径/Contents/Resources/app.asar"
```

安装前会提示退出 Antigravity；安装后启动应用即可看到中文界面。

### 还原原版

```bash
python3 install.py --restore
```

### 查看状态

```bash
python3 install.py --status
```

## 注意事项

- 非官方语言包；修改本地 `app.asar`，安装前自动备份为 `app.asar.bak`
- Antigravity 官方升级会覆盖补丁，升级后重新运行 `python3 install.py` 即可
- macOS 若提示“应用已损坏”，执行：
  `sudo xattr -rd com.apple.quarantine /Applications/Antigravity.app`
- 本 skill 目录下的 `install.py` 与 `dicts/` 是运行所需文件，请保持相对结构
