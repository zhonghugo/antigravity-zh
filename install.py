# -*- coding: utf-8 -*-
"""
Antigravity 中文汉化安装器（纯 Python 零外部依赖）
====================================================
为 Google Antigravity 桌面客户端（Agent Manager）注入中文翻译引擎。

原理：解包 app.asar -> 向 dist/preload.js 与 dist/ideInstall/wizardPreload.js
注入 DOM 翻译引擎与全量字典 -> 重新打包 -> （macOS）ad-hoc 重签名。

用法：
    python3 install.py              # 安装汉化
    python3 install.py --restore    # 还原官方原版
    python3 install.py --status     # 查看当前状态
    python3 install.py --asar PATH  # 指定 app.asar 路径（非默认安装时）

说明：本工具修改本地 app.asar，非 Google 官方语言包；Antigravity 官方
升级后汉化会失效，重新运行本脚本即可。安装前会自动备份 app.asar.bak。
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

# 允许 install.py 从任意工作目录运行
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import asar  # noqa: E402

TAG = "Antigravity Chinese Translation Injection v3-full"
ANCHOR = "  const combinedDict = Object.assign({}, coreWords, dictionary);"
DICT_PLACEHOLDER = "__DICT_ITEMS__"
UNPACK_PATTERNS = ["**/node_modules/chrome-devtools-mcp/**"]

# 旧版标记（用于升级时清理）
OLD_TAGS = ["Antigravity Chinese Translation Injection v2-extra"]


def _load_engine_template():
    """读取翻译引擎模板（含 __DICT_ITEMS__ 占位符）。"""
    p = os.path.join(HERE, "dicts", "engine.js")
    if not os.path.exists(p):
        sys.exit("[ERR] 找不到引擎模板: %s" % p)
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def build_injection(dictionary):
    """由全量字典生成注入 JS（引擎模板 + 字典项）。"""
    items = []
    for k, v in dictionary.items():
        items.append("    %s: %s" % (json.dumps(k, ensure_ascii=False),
                                     json.dumps(v, ensure_ascii=False)))
    dict_block = "// ===== %s =====\n  const extraDict = {\n%s\n  };\n" % (
        TAG, ",\n".join(items))
    return _load_engine_template().replace(DICT_PLACEHOLDER, dict_block)


def build_injection_for_existing(dictionary):
    """为已注入引擎的 preload 生成字典块（extraDict 注入到 combinedDict 锚点前）。"""
    items = []
    for k, v in dictionary.items():
        items.append("    %s: %s" % (json.dumps(k, ensure_ascii=False),
                                     json.dumps(v, ensure_ascii=False)))
    return ("\n  // ===== %s =====\n  const extraDict = {\n%s\n  };\n"
            "  for (const ek in extraDict) {\n"
            "    if (!(ek in dictionary) && !(ek in coreWords)) dictionary[ek] = extraDict[ek];\n"
            "  }\n" % (TAG, ",\n".join(items)))


# ---------------------------------------------------------------- 平台与路径
def detect_paths(asar_path=None):
    """自动探测 Antigravity 安装路径；返回 (asar_path, resources_dir)。"""
    if asar_path:
        if not os.path.exists(asar_path):
            sys.exit("[ERR] 指定的 app.asar 不存在: %s" % asar_path)
        return os.path.abspath(asar_path), os.path.dirname(os.path.abspath(asar_path))

    system = sys.platform
    candidates = []
    if system == "darwin":
        candidates = [
            "/Applications/Antigravity.app/Contents/Resources/app.asar",
            os.path.expanduser("~/Applications/Antigravity.app/Contents/Resources/app.asar"),
        ]
    elif system == "win32":
        base = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            os.path.join(base, "Programs", "Antigravity", "resources", "app.asar"),
        ]
    elif system.startswith("linux"):
        candidates = [
            "/opt/Antigravity/resources/app.asar",
            os.path.expanduser("~/.local/share/Antigravity/resources/app.asar"),
        ]
    for c in candidates:
        if os.path.exists(c):
            return c, os.path.dirname(c)
    sys.exit(
        "[ERR] 未找到 Antigravity app.asar。\n"
        "      macOS: /Applications/Antigravity.app\n"
        "      Windows: %%LOCALAPPDATA%%\\Programs\\Antigravity\n"
        "      或使用 --asar 手动指定路径。"
    )


def check_app_running():
    """检测 Antigravity 是否在运行（覆盖写前应退出应用）。"""
    try:
        if sys.platform == "darwin":
            # 匹配应用主程序路径而非任意含 "Antigravity" 的命令行，
            # 避免误报（如打开了本仓库的编辑器进程）
            r = subprocess.run(["pgrep", "-f", "Antigravity.app/Contents/MacOS"],
                               capture_output=True)
            return r.returncode == 0
        elif sys.platform == "win32":
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Antigravity.exe"],
                               capture_output=True, text=True)
            return "Antigravity.exe" in r.stdout
    except Exception:
        pass
    return False


def codesign_macos(app_path):
    """macOS ad-hoc 重签名，解决修改后“应用已损坏”问题。"""
    if sys.platform != "darwin":
        return True
    try:
        r = subprocess.run(["codesign", "--force", "--deep", "--sign", "-", app_path],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("[!] 重签名失败（可忽略，若启动报“已损坏”再处理）: %s" % r.stderr.strip()[:200])
            return False
        print("[OK] macOS 重签名完成")
        return True
    except FileNotFoundError:
        return True


# ---------------------------------------------------------------- 字典与注入
def load_dictionary():
    d = {}
    dict_path = os.path.join(HERE, "dicts", "zh_cn.json")
    if not os.path.exists(dict_path):
        sys.exit("[ERR] 找不到字典文件: %s" % dict_path)
    with open(dict_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        d.update(data)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "key" in item and "value" in item:
                d[item["key"]] = item["value"]
    if not d:
        sys.exit("[ERR] 字典为空")
    return d


def strip_block(content, tag):
    """移除先前注入的字典块（注释标记 + extraDict 定义 + for 循环）。"""
    start = content.find("// ===== " + tag + " =====")
    if start == -1:
        return content, False
    end_marker = (
        "    if (!(ek in dictionary) && !(ek in coreWords)) dictionary[ek] = extraDict[ek];\n  }\n"
    )
    end = content.find(end_marker, start)
    if end == -1:
        print("[!] 找到标记但找不到块结束位置，跳过清理")
        return content, False
    end += len(end_marker)
    return content[:start] + content[end:], True


def patch_file(path, dictionary):
    """向 preload/wizardPreload 注入汉化。

    分两种情况：
    A. 原版（无引擎）-> 直接追加完整引擎（引擎模板 + 全量字典），无需锚点；
    B. 已有引擎（含 combinedDict 锚点）-> 先清理旧字典块，再在锚点前注入新字典块。
    """
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if TAG in content and "const extraDict" in content:
        print("[!] %s 已包含当前版本汉化，跳过" % os.path.basename(path))
        return

    engine_marker = "const combinedDict = Object.assign({}, coreWords, dictionary);"
    if engine_marker in content:
        # 情况 B：引擎已存在，仅更新字典块
        for old_tag in [TAG] + OLD_TAGS:
            content, _ = strip_block(content, old_tag)
        injection = build_injection_for_existing(dictionary)
        content = content.replace(engine_marker, injection + "\n" + engine_marker)
    else:
        # 情况 A：官方原版，追加完整引擎（含全量字典）
        content = content.rstrip() + "\n\n" + build_injection(dictionary) + "\n"

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("[OK] %s 注入完成" % os.path.basename(path))


def patch_native_menu(tmp):
    """注入原生菜单翻译（menu.js：File/Edit/View… 菜单栏）。"""
    menu_path = os.path.join(tmp, "dist", "menu.js")
    if not os.path.exists(menu_path):
        print("[!] menu.js 不存在，跳过菜单翻译")
        return
    with open(menu_path, "r", encoding="utf-8") as f:
        content = f.read()
    target_hook = "electron_1.Menu.setApplicationMenu(menu);"
    if "translateMenu" in content:
        print("[*] menu.js 已注入菜单翻译，跳过")
        return
    if target_hook not in content:
        print("[!] menu.js 未找到注入钩子，跳过")
        return
    content = content.replace(
        target_hook,
        "if (typeof translateMenu === 'function') { menu.items.forEach(translateMenu); } " + target_hook)
    content += "\n" + MENU_TRANSLATION_CODE
    with open(menu_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("[OK] 注入 原生菜单翻译: menu.js")


def patch_tray(tmp):
    """注入托盘菜单翻译（tray.js：智能体数量/打开/退出）。"""
    tray_path = os.path.join(tmp, "dist", "tray.js")
    if not os.path.exists(tray_path):
        print("[!] tray.js 不存在，跳过托盘翻译")
        return
    with open(tray_path, "r", encoding="utf-8") as f:
        content = f.read()
    if "translatedActions" in content:
        print("[*] tray.js 已注入托盘翻译，跳过")
        return
    old_template = "contextMenu = electron_1.Menu.buildFromTemplate(actions);"
    new_template = (
        "const translatedActions = actions.map(action => {\n"
        "        if (action.label === 'No agents running') action.label = '没有智能体在运行';\n"
        "        if (action.label && action.label.startsWith('Open ')) action.label = '打开 Antigravity';\n"
        "        if (action.label === 'Quit') action.label = '退出';\n"
        "        return action;\n"
        "    });\n"
        "    contextMenu = electron_1.Menu.buildFromTemplate(translatedActions);")
    old_label = "countItem.label = count > 0 ? `${count} active agents` : 'No agents running';"
    old_label_2 = "countItem.label = count > 0 ? `${count} active agents` : \"No agents running\";"
    new_label = "countItem.label = count > 0 ? `${count} 个智能体运行中` : '没有智能体在运行';"
    changed = False
    if old_template in content:
        content = content.replace(old_template, new_template)
        changed = True
    if old_label in content:
        content = content.replace(old_label, new_label)
        changed = True
    elif old_label_2 in content:
        content = content.replace(old_label_2, new_label)
        changed = True
    if changed:
        with open(tray_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("[OK] 注入 托盘翻译: tray.js")
    else:
        print("[!] tray.js 钩子未匹配，跳过")


def patch_quit_dialog(tmp):
    """汉化主进程退出确认弹窗（main.js：原生 dialog，DOM 引擎无法触及）。"""
    main_path = os.path.join(tmp, "dist", "main.js")
    if not os.path.exists(main_path):
        print("[!] main.js 不存在，跳过退出弹窗翻译")
        return
    with open(main_path, "r", encoding="utf-8") as f:
        content = f.read()
    if "AG_ZH_QUIT_DIALOG" in content:
        print("[*] main.js 已注入退出弹窗翻译，跳过")
        return
    replacements = [
        ("buttons: ['Cancel', 'Quit']", "buttons: ['取消', '退出'], // AG_ZH_QUIT_DIALOG"),
        ("title: 'Confirm Quit'", "title: '确认退出'"),
        ("message: 'Are you sure you want to quit?'", "message: '您确定要退出吗？'"),
        ("detail: 'There may be agents or background tasks running.'",
         "detail: '可能还有智能体或后台任务正在运行。'"),
    ]
    changed = False
    for old, new in replacements:
        if old in content:
            content = content.replace(old, new)
            changed = True
    if changed:
        with open(main_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("[OK] 注入 退出弹窗翻译: main.js")
    else:
        print("[!] main.js 退出弹窗钩子未匹配，跳过")


def patch_loading_overlay(tmp):
    """汉化启动加载画面（loadingOverlay.js：翻译引擎启动前显示）。"""
    overlay_path = os.path.join(tmp, "dist", "loadingOverlay.js")
    if not os.path.exists(overlay_path):
        print("[!] loadingOverlay.js 不存在，跳过加载画面翻译")
        return
    with open(overlay_path, "r", encoding="utf-8") as f:
        content = f.read()
    if "AG_ZH_LOADING" in content:
        print("[*] loadingOverlay.js 已注入加载画面翻译，跳过")
        return
    old = '<div class="text">Loading Antigravity</div>'
    new = '<div class="text">正在加载 Antigravity</div> <!-- AG_ZH_LOADING -->'
    if old in content:
        content = content.replace(old, new)
        with open(overlay_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("[OK] 注入 加载画面翻译: loadingOverlay.js")
    else:
        print("[!] loadingOverlay.js 钩子未匹配，跳过")


MENU_TRANSLATION_CODE = r"""
const menuTranslationMap = {
  'File': '文件',
  'Edit': '编辑',
  'View': '视图',
  'Window': '窗口',
  'Help': '帮助',
  'New Window': '新建窗口',
  'Docs': '使用文档',
  'Toggle Developer Tools': '开发者工具',
  'Check for Updates': '检查更新',
  'Checking for Updates...': '正在检查更新...',
  'Downloading Update...': '正在下载更新...',
  'Restart to Update': '重启以应用更新',
  'Undo': '撤销',
  'Redo': '重做',
  'Cut': '剪切',
  'Copy': '复制',
  'Paste': '粘贴',
  'Select All': '全选',
  'Minimize': '最小化',
  'Close': '关闭',
  'Quit Antigravity': '退出 Antigravity',
  'About Antigravity': '关于 Antigravity',
  'Services': '服务',
  'Hide Antigravity': '隐藏 Antigravity',
  'Hide Others': '隐藏其他',
  'Show All': '显示全部',
  'Force Reload': '强制重新加载',
  'Reload': '重新加载',
  'Actual Size': '实际大小',
  'Zoom In': '放大',
  'Zoom Out': '缩小',
  'Toggle Full Screen': '切换全屏'
};
function translateMenu(menuItem) {
  if (menuItem.label && menuTranslationMap[menuItem.label]) {
    menuItem.label = menuTranslationMap[menuItem.label];
  }
  if (menuItem.submenu && menuItem.submenu.items) {
    menuItem.submenu.items.forEach(translateMenu);
  }
}
"""


# ---------------------------------------------------------------- 主流程
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_install(asar_path, resources_dir):
    if check_app_running():
        print("[!] 检测到 Antigravity 正在运行。")
        print("    为避免文件被占用，请先完全退出 Antigravity 再运行本脚本。")
        sys.exit(1)

    # 1. 解包（含 .unpacked），同时判断当前是否已汉化
    tmp = tempfile.mkdtemp(prefix="agy_zh_")
    print("[*] 解包 app.asar ...")
    try:
        asar.extract(asar_path, tmp)
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        sys.exit("[ERR] 解包失败: %s" % e)

    preload = os.path.join(tmp, "dist", "preload.js")
    already = False
    if os.path.exists(preload):
        with open(preload, "r", encoding="utf-8") as f:
            already = TAG in f.read()
    if already:
        print("[*] 当前已是汉化版，跳过备份（保留官方原版 .bak）")

    # 2. 备份：仅当当前 asar 未被汉化（是官方版）时，才可能覆盖 .bak
    bak = asar_path + ".bak"
    if not already:
        if not os.path.exists(bak):
            shutil.copy2(asar_path, bak)
            print("[OK] 首次备份官方原版 -> %s" % bak)
        elif os.path.getmtime(asar_path) > os.path.getmtime(bak):
            shutil.copy2(asar_path, bak)
            print("[OK] 检测到官方版本已更新，重新备份 -> %s" % bak)
        else:
            print("[*] 已有官方备份，直接使用")

    # 3. 注入
    dictionary = load_dictionary()
    print("[*] 字典词条: %d" % len(dictionary))
    patch_file(preload, dictionary)
    wizard = os.path.join(tmp, "dist", "ideInstall", "wizardPreload.js")
    if os.path.exists(wizard):
        patch_file(wizard, dictionary)
    patch_native_menu(tmp)
    patch_tray(tmp)
    patch_quit_dialog(tmp)
    patch_loading_overlay(tmp)

    # 4. 重打包
    new_asar = os.path.join(tmp, "app.asar.new")
    print("[*] 重新打包（unpack: chrome-devtools-mcp）...")
    asar.pack(tmp, new_asar, UNPACK_PATTERNS)
    if not os.path.exists(new_asar) or os.path.getsize(new_asar) == 0:
        shutil.rmtree(tmp, ignore_errors=True)
        sys.exit("[ERR] 打包结果为空")

    # 5. 原子替换 asar 与 unpacked
    #    先把新 asar 复制到同目录暂存文件（保证同一文件系统），再用 os.replace
    #    原子替换，避免复制中途断电/磁盘满导致 app.asar 损坏；unpacked 同步切换，
    #    替换失败时自动回滚。
    staged_asar = asar_path + ".agzh_new"
    old_unpacked = asar_path + ".unpacked"
    old_unpacked_bak = asar_path + ".unpacked.agzh_old"
    if os.path.isdir(old_unpacked_bak):
        shutil.rmtree(old_unpacked_bak)
    shutil.copy2(new_asar, staged_asar)
    if os.path.isdir(old_unpacked):
        os.rename(old_unpacked, old_unpacked_bak)
    if os.path.isdir(new_asar + ".unpacked"):
        shutil.move(new_asar + ".unpacked", old_unpacked)
    try:
        os.replace(staged_asar, asar_path)
    except Exception:
        if os.path.isdir(old_unpacked):
            shutil.rmtree(old_unpacked, ignore_errors=True)
        if os.path.isdir(old_unpacked_bak):
            os.rename(old_unpacked_bak, old_unpacked)
        raise
    finally:
        if os.path.exists(staged_asar):
            os.remove(staged_asar)
    if os.path.isdir(old_unpacked_bak):
        shutil.rmtree(old_unpacked_bak, ignore_errors=True)
    print("[OK] 已替换 app.asar（新大小: %d bytes）" % os.path.getsize(asar_path))
    print("[OK] SHA256: %s" % sha256(asar_path))

    shutil.rmtree(tmp, ignore_errors=True)

    # 6. 签名（resources_dir -> Contents -> Antigravity.app）
    if sys.platform == "darwin":
        app_root = os.path.dirname(os.path.dirname(resources_dir))
        codesign_macos(app_root)

    print("[DONE] 汉化注入完成，请启动 Antigravity 查看效果。")


def cmd_restore(asar_path, resources_dir):
    bak = asar_path + ".bak"
    if not os.path.exists(bak):
        sys.exit("[ERR] 没有找到备份 %s，无法还原" % bak)
    shutil.copy2(bak, asar_path)
    # 注意：.unpacked（chrome-devtools-mcp 等）是官方原版内容且不被汉化修改，
    # 安装/还原时均保持一致，无需删除。
    if sys.platform == "darwin":
        # resources_dir -> Contents -> Antigravity.app
        app_root = os.path.dirname(os.path.dirname(resources_dir))
        codesign_macos(app_root)
    print("[OK] 已还原官方原版 app.asar（SHA256: %s）" % sha256(asar_path))
    print("[OK] 汉化已移除，请重启 Antigravity。")


def cmd_status(asar_path, resources_dir):
    print("asar 路径: %s" % asar_path)
    if not os.path.exists(asar_path):
        print("状态: 不存在")
        return
    print("SHA256: %s" % sha256(asar_path))
    print("大小: %d bytes" % os.path.getsize(asar_path))
    bak = asar_path + ".bak"
    if os.path.exists(bak):
        print("备份: 存在（%s）" % sha256(bak)[:16])
    else:
        print("备份: 无")
    try:
        tmp = tempfile.mkdtemp(prefix="agy_zh_st_")
        asar.extract(asar_path, tmp)
        preload = os.path.join(tmp, "dist", "preload.js")
        if os.path.exists(preload):
            with open(preload, "r", encoding="utf-8") as f:
                c = f.read()
            print("汉化: %s" % ("已注入 v3" if TAG in c else "未注入（原版）"))
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:
        print("检查失败: %s" % e)


def main():
    ap = argparse.ArgumentParser(description="Antigravity 中文汉化安装器（零依赖）")
    ap.add_argument("--restore", action="store_true", help="还原官方原版")
    ap.add_argument("--status", action="store_true", help="查看汉化状态")
    ap.add_argument("--asar", default=None, help="手动指定 app.asar 路径")
    args = ap.parse_args()

    asar_path, resources_dir = detect_paths(args.asar)
    print("[*] 使用 app.asar: %s" % asar_path)

    if args.restore:
        cmd_restore(asar_path, resources_dir)
    elif args.status:
        cmd_status(asar_path, resources_dir)
    else:
        cmd_install(asar_path, resources_dir)


if __name__ == "__main__":
    main()
