# Zim Wiki 窗口插件

本项目包含三个彼此独立、可分别启用的 Zim Desktop Wiki 插件：

- `alwaysontop`：让 Zim 主编辑窗口保持在普通窗口上方。
- `autocollapse`：主窗口失去焦点后隐藏编辑区与侧栏，只保留顶部菜单、工具栏或标题栏；窗口重新获得焦点后恢复。
- `systemtheme`：接收操作系统的主题变化通知，并同步切换 Zim 自带的深色或浅色主题。

## 兼容性

插件面向使用 GTK 3 的 Zim 0.75–0.77，并按 Zim 0.77.2 的插件接口实现。Linux/X11、Linux/Wayland、Windows 和 macOS 对“窗口置顶”提示的支持由各自的窗口管理器决定；部分 Wayland 合成器可能忽略该提示。

自动折叠插件不会在全屏状态下折叠。默认延迟 250 毫秒，并会忽略 Zim 自己打开的对话框，以免使用“首选项”“打开文件”等窗口时误折叠。这些选项可在插件配置中修改。

## 安装

1. 退出 Zim。
2. 将所需的 `alwaysontop`、`autocollapse` 和/或 `systemtheme` 文件夹复制到 Zim 用户插件目录：

   - Linux：`~/.local/share/zim/plugins/`
   - macOS 官方应用包：`~/Library/Application Support/org.zim-wiki.Zim/share/zim/plugins/`
   - Windows：通常为 `%APPDATA%\\zim\\data\\zim\\plugins\\`

3. 重新启动 Zim。
4. 打开“编辑 → 首选项 → 插件”，启用所需的 **Always on Top**、**Auto Collapse on Focus Loss** 和/或 **System Theme**。

最终目录结构应为：

```text
zim/plugins/
├── alwaysontop/
│   └── __init__.py
├── autocollapse/
│   └── __init__.py
└── systemtheme/
    └── __init__.py
```

## 系统主题同步

启用 **System Theme** 后无需配置。插件启动时同步一次当前系统主题，之后只接收系统通知，不会定时轮询：

- macOS：CoreFoundation 分布式外观通知。
- Windows：个性化主题注册表变化通知。
- GNOME/Linux：`org.gnome.desktop.interface` 的 `color-scheme` 变化通知。
- 其他桌面：GTK 主题名称变化通知。

插件不提供自定义配色，而是调用 Zim 自带的“偏好暗色主题”，因此编辑区、索引栏、书签栏、工具栏和按钮均由 Zim/GTK 原生主题统一绘制。禁用插件后会恢复启用前的 Zim 主题设置。

修改插件代码后必须完全退出并重启 Zim；Zim 会缓存已经导入的插件模块。

## 卸载

先在 Zim 的插件首选项中禁用插件，再退出 Zim 并删除对应文件夹。

## 许可证

GNU General Public License v2 或更高版本（GPL-2.0-or-later）。
