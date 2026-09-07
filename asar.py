# -*- coding: utf-8 -*-
"""
纯 Python 实现的 asar 归档读写库（零外部依赖）。
支持 extract / pack，兼容 Electron 使用的 asar 格式，
含 unpacked 文件（.asar.unpacked 目录）的处理。

参考 @electron/asar 的实现约定：
- 文件头 16 字节 pickle: <IIII> = (4, json_size+8, json_size+4, json_size)
- header 为紧凑 JSON（无多余空格），UTF-8
- 目录节点: {"files": {...}}；文件节点: {"size": N, "offset": "123"}
- unpacked 文件: {"size": N, "offset": "", "unpacked": true}，内容在 <asar>.unpacked 下
- executable 文件额外标记 "executable": true
"""
import hashlib
import json
import os
import re
import struct
import sys

PICKLE_HEADER = struct.Struct("<IIII")
BLOCK_SIZE = 4 * 1024 * 1024  # integrity 分块大小，与官方一致


def _file_integrity(data):
    """计算 asar integrity（与 @electron/asar 算法一致）：
    hash=整文件 SHA256，blocks=每 BLOCK_SIZE 一块的 SHA256。
    """
    full = hashlib.sha256(data).hexdigest()
    blocks = []
    if not data:
        blocks.append(hashlib.sha256(data).hexdigest())
    for off in range(0, len(data), BLOCK_SIZE):
        blocks.append(hashlib.sha256(data[off:off + BLOCK_SIZE]).hexdigest())
    return {"algorithm": "SHA256", "hash": full, "blockSize": BLOCK_SIZE, "blocks": blocks}


def _glob_to_regex(pattern):
    """将支持 ** / * / ? 的 glob 模式转换为正则（路径以 / 分隔）。"""
    out = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                if i + 2 < n and pattern[i + 2] == "/":
                    out.append("(?:[^/]+/)*")
                    i += 3
                else:
                    out.append(".*")
                    i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            while j < n and pattern[j] != "]":
                j += 1
            cls = pattern[i + 1:j]
            out.append("[" + cls.replace("\\", "\\\\") + "]")
            i = j + 1 if j < n else n
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def _match_unpack(relpath, patterns):
    if not patterns:
        return False
    for p in patterns:
        rx = _glob_to_regex(p)
        if rx.match(relpath):
            return True
    return False


def _is_executable(path):
    """按 @electron/asar 规则判断是否标记 executable。"""
    if not os.access(path, os.X_OK):
        return False
    if path.endswith((".js", ".json", ".html", ".css", ".png", ".txt",
                      ".yml", ".map", ".bnf", ".ts", ".md", ".svg")):
        return False
    return True


def _build_tree(src_dir):
    """构建 asar header 的 files 树；返回 (header, [(abspath, node, relpath)])。"""
    header = {"files": {}}
    file_list = []

    for root, dirs, files in os.walk(src_dir):
        # 稳定顺序：目录和文件都排序
        dirs.sort()
        files.sort()
        rel_root = os.path.relpath(root, src_dir)
        if rel_root == ".":
            rel_root = ""
        curr = header
        if rel_root:
            for part in rel_root.split(os.sep):
                curr = curr.setdefault("files", {}).setdefault(part, {"files": {}})
        for f in files:
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, src_dir).replace(os.sep, "/")
            node = {"size": os.path.getsize(fp)}
            if _is_executable(fp):
                node["executable"] = True
            curr.setdefault("files", {})[f] = node
            file_list.append((fp, node, rel))
    return header, file_list


def pack(src_dir, dest_asar, unpack_patterns=None):
    """
    将 src_dir 打包为 dest_asar。
    匹配 unpack_patterns（glob 列表）的文件写入 dest_asar.unpacked 目录，
    header 中标记 unpacked: true 且 offset 为空。
    """
    unpack_patterns = unpack_patterns or []
    header, file_list = _build_tree(src_dir)

    unpacked_root = dest_asar + ".unpacked"
    current_offset = 0
    for fp, node, rel in file_list:
        if _match_unpack(rel, unpack_patterns):
            node["unpacked"] = True
            # 内容写入 .unpacked 目录
            target = os.path.join(unpacked_root, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            _copy_file(fp, target)
            if node.get("executable"):
                os.chmod(target, os.stat(target).st_mode | 0o111)
            with open(target, "rb") as src:
                node["integrity"] = _file_integrity(src.read())
        else:
            node["offset"] = str(current_offset)
            with open(fp, "rb") as src:
                node["integrity"] = _file_integrity(src.read())
            current_offset += node["size"]

    json_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    json_size = len(json_bytes)
    # 官方将 JSON 补齐到 4 字节对齐，header pickle 总长 = 8 + align4(json_size)
    pad = (-json_size) % 4
    json_padded = json_bytes + b"\x00" * pad
    pickle_size = 8 + len(json_padded)
    os.makedirs(os.path.dirname(dest_asar) or ".", exist_ok=True)
    with open(dest_asar, "wb") as f:
        f.write(struct.pack("<II", 4, pickle_size))
        f.write(struct.pack("<II", 4 + len(json_padded), json_size))
        f.write(json_padded)
        # 按序遍历写入文件数据（unpacked 跳过）
        for fp, node, rel in file_list:
            if node.get("unpacked"):
                continue
            with open(fp, "rb") as src:
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
    return dest_asar


def _read_header(asar_path):
    """读取 asar header，返回 (header_dict, json_size, header_pickle_size)。
    文件布局：
      [0:4]   uint32 = 4（size pickle 的 payload 长度）
      [4:8]   uint32 = header pickle 总长 = 8 + align4(json_len)
      [8:12]  uint32 = header pickle payload 长 = 4 + align4(json_len)
      [12:16] int32  = JSON 字符串长度
      [16:16+json_len] JSON 字符串，其后补齐到 4 字节对齐
    数据区起点 = 8 + header_pickle_size。
    """
    with open(asar_path, "rb") as f:
        head = f.read(8)
        if len(head) != 8:
            raise ValueError("无效的 asar 文件头")
        v, pickle_size = struct.unpack("<II", head)
        # v 是外层 size pickle 的 payload 长度（Chromium Pickle 约定，恒为 4），
        # 并非格式版本号；pickle_size 为 header pickle 总长，需在合理范围内
        if v != 4 or pickle_size < 8 or pickle_size > 64 * 1024 * 1024:
            raise ValueError("无效的 asar 文件头")
        f.seek(12)
        len_bytes = f.read(4)
        if len(len_bytes) != 4:
            raise ValueError("asar header 读取不完整")
        json_size = struct.unpack("<i", len_bytes)[0]
        f.seek(16)
        data = f.read(json_size)
        if len(data) != json_size:
            raise ValueError("asar header 读取不完整")
        return json.loads(data.decode("utf-8")), json_size, pickle_size


def _data_offset(pickle_size, file_offset):
    """将 header 中文件的相对偏移转换为文件内的绝对偏移（数据区起点 = 8 + pickle_size）。"""
    return 8 + pickle_size + int(file_offset)


def extract(asar_path, dest_dir, with_unpacked=True):
    """
    将 asar 解包到 dest_dir。
    unpacked 文件：若 with_unpacked 为 True，则从 <asar>.unpacked 复制。
    """
    header, json_size, pickle_size = _read_header(asar_path)
    unpacked_root = asar_path + ".unpacked"
    count = 0

    def walk(node, rel):
        nonlocal count
        for name, child in node.get("files", {}).items():
            child_rel = rel + "/" + name if rel else name
            if "files" in child:  # 目录 -> 递归
                walk(child, child_rel)
                continue
            out_path = os.path.join(dest_dir, *child_rel.split("/"))
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            if child.get("unpacked"):
                if with_unpacked:
                    src_path = os.path.join(unpacked_root, *child_rel.split("/"))
                    if os.path.exists(src_path):
                        _copy_file(src_path, out_path)
                        count += 1
                    else:
                        # unpacked 文件缺失时创建空占位，避免结构破坏
                        open(out_path, "wb").close()
                        count += 1
                else:
                    open(out_path, "wb").close()
                    count += 1
            else:
                with open(asar_path, "rb") as f:
                    f.seek(_data_offset(pickle_size, child["offset"]))
                    data = f.read(child["size"])
                with open(out_path, "wb") as f:
                    f.write(data)
                if child.get("executable"):
                    os.chmod(out_path, os.stat(out_path).st_mode | 0o111)
                count += 1

    walk(header, "")
    return count


def list_files(asar_path):
    """列出 asar 内所有文件（相对路径）。"""
    header = _read_header(asar_path)
    out = []

    def walk(node, rel):
        for name, child in node.get("files", {}).items():
            child_rel = rel + "/" + name if rel else name
            if "files" in child:
                walk(child, child_rel)
            else:
                out.append((child_rel, child.get("size", 0), child.get("unpacked", False)))

    walk(header, "")
    return out


def _copy_file(src, dst):
    with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
        while True:
            chunk = fsrc.read(65536)
            if not chunk:
                break
            fdst.write(chunk)


if __name__ == "__main__":
    # 命令行自检：python3 asar.py <extract|pack|list> ...
    cmd = sys.argv[1]
    if cmd == "extract":
        n = extract(sys.argv[2], sys.argv[3])
        print("extracted %d files" % n)
    elif cmd == "pack":
        pack(sys.argv[2], sys.argv[3], sys.argv[4:] or None)
        print("packed -> %s" % sys.argv[3])
    elif cmd == "list":
        for rel, size, unp in list_files(sys.argv[2]):
            print("%s\t%s\t%s" % (rel, size, "unpacked" if unp else ""))
