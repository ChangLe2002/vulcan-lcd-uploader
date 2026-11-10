# SPDX-License-Identifier: MIT
"""项目元信息：名称、作者、版本、许可、目录约定。

集中放这里，安装包、关于窗口、命令行 --version、README 都从这里取，
避免多处写死导致对不上。
"""

from __future__ import annotations

__all__ = [
    "APP_NAME",
    "APP_NAME_EN",
    "APP_TITLE",
    "APP_AUTHOR",
    "APP_AUTHOR_FULL",
    "APP_VERSION",
    "APP_LICENSE",
    "PROJECT_URL",
    "PROJECT_TAGLINE",
    "RUNTIME_FOLDERS",
    "DEFAULT_INSTALL_DIR",
    "runtime_folder_rows",
]

APP_NAME = "火神智屏图传工具"
APP_NAME_EN = "Vulcan LCD Uploader"
APP_TITLE = f"{APP_NAME}（{APP_NAME_EN}）"

APP_AUTHOR = "常乐"
APP_AUTHOR_FULL = "常乐（Changle）"

APP_VERSION = "1.0.0"
APP_LICENSE = "MIT"

#: 项目主页占位：上传 GitHub 后把这里改成你的仓库地址
PROJECT_URL = "https://github.com/ChangLe2002/vulcan-lcd-uploader"

#: 绿色包的默认安装位置（仅用于提示，实际以程序所在目录为准）
DEFAULT_INSTALL_DIR = r"%LOCALAPPDATA%\Programs\VulcanLCDUploader"

PROJECT_TAGLINE = "面向 iGame 火神 RTX 50 系显卡副屏（LCD5A，1024×240）的开源上传工具"

#: 运行期会在磁盘上产生的东西（关于窗口会展示给用户，方便排查与清理）
RUNTIME_FOLDERS: tuple[tuple[str, str, str], ...] = (
    ("安装目录", "<安装目录>\\", "程序本体、_internal\\ 运行库、app.ico"),
    ("日志", "<安装目录>\\logs\\", "按天生成的 .log，出问题时可导出调试报告"),
    ("界面偏好", "<安装目录>\\ui_prefs.json", "关闭到托盘、独立模式、免责声明是否已读"),
    ("素材库", "<安装目录>\\recent_files.json", "最近上传过的图片路径（最多 30 条）"),
    ("设备缓存", "<安装目录>\\device_state.json", "上次读到的可用空间 / 固件 / 亮度"),
    ("用户配置", "<安装目录>\\config\\settings.user.json", "可选；覆盖默认配置时才存在"),
    ("设备端文件", "屏幕内部存储", "img1..imgN.pak，不占本地磁盘，可在软件里清理"),
)


def runtime_folder_rows() -> list[tuple[str, str, str]]:
    """返回目录说明的行（供关于窗口/文档复用）。"""
    return list(RUNTIME_FOLDERS)
