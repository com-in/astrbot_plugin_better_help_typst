import re
from dataclasses import dataclass, field

from astrbot.api import AstrBotConfig, logger

from . import DefaultCFG
from .schemas import CustomItem, CustomEntry

# 预编译正则
HEX_COLOR_REGEX = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")


@dataclass
class RenderingConfig:
    timeout_analysis: float
    timeout_compile: float
    max_concurrent_tasks: int
    giant_threshold: int
    webp_limit: int
    split_height: int
    ppi: float
    render_width: int


@dataclass
class ThemePreset:
    """单个外观预设"""
    name: str
    font_order: list[str]
    colors: dict[str, str] = field(default_factory=dict)


@dataclass
class AppearanceConfig:
    """外观配置聚合"""
    active_preset: str
    presets: dict[str, ThemePreset]
    background_image: str = ""
    background_opacity: float = 60.0
    bg_cache_enabled: bool = True
    # 内部缓存字段
    _color_cache: dict[str, str] | None = field(init=False, default=None, repr=False)

    def get_active_font_order(self) -> list[str]:
        """获取激活预设的字体列表"""
        preset = self.presets.get(self.active_preset)
        if preset:
            return preset.font_order
        return [] # 兜底： FontManager 补全默认值

    def get_active_colors(self) -> dict[str, str]:
        """获取激活预设的颜色配置"""
        if self._color_cache is not None:
            return self._color_cache # 命中缓存

        # 1. 默认
        final_colors = DefaultCFG.DEFAULT_COLORS.copy()

        # 2. 预设
        preset = self.presets.get(self.active_preset)

         # 3. 清洗 & 合并
        if preset and preset.colors:
            for key, user_val in preset.colors.items():
                if key not in final_colors:
                    continue
                
                # 校验
                if self._is_valid_hex(user_val):
                    final_colors[key] = user_val
                else:
                    logger.warning(
                        f"[HelpTypst] 颜色配置异常: '{key}' 的值 '{user_val}' 不是有效的十六进制颜色。\n"
                        f"已回退到默认值: {final_colors[key]}"
                    )

        # 4. 写入缓存
        self._color_cache = final_colors

        return final_colors

    def _is_valid_hex(self, color_str: str) -> bool:
        """校验 Hex Color"""
        if not isinstance(color_str, str):
            return False

        return bool(HEX_COLOR_REGEX.match(color_str))


@dataclass
class TypstPluginConfig:
    """插件全局配置聚合根"""
    enable_waiting_message: bool
    ignored_plugins: set[str]
    custom_font_path: str
    custom_template_path: str
    custom_items: list[CustomItem]
    menu_title: str
    event_title: str
    filter_title: str

    rendering: RenderingConfig
    appearance: AppearanceConfig

    @classmethod
    def load(cls, raw_config: AstrBotConfig) -> "TypstPluginConfig":
        """工厂方法：从 AstrBotConfig 加载配置，未配置项回退到 DefaultCFG"""
        enable_wait = raw_config.get("enable_waiting_message", False)

        ignored_list = raw_config.get("ignored_plugins", None)
        ignored_set = (
            set(ignored_list) if ignored_list is not None else DefaultCFG.IGNORED_PLUGINS.copy()
        )

        # Rendering
        raw_render = raw_config.get("rendering", {})
        render_cfg = RenderingConfig(
            timeout_analysis=raw_render.get(
                "timeout_analysis", DefaultCFG.TIMEOUT_ANALYSIS
            ),
            timeout_compile=raw_render.get(
                "timeout_compile", DefaultCFG.TIMEOUT_COMPILE
            ),
            max_concurrent_tasks=int(
                raw_render.get("max_concurrent_tasks", DefaultCFG.LIMIT_TASK)
            ),
            giant_threshold=raw_render.get("giant_threshold", DefaultCFG.LIMIT_GIANT),
            webp_limit=raw_render.get("webp_limit", DefaultCFG.LIMIT_WEBP),
            split_height=raw_render.get("split_height", DefaultCFG.LIMIT_SIDE),
            ppi=float(raw_render.get("ppi", DefaultCFG.LIMIT_PPI)),
            render_width=raw_render.get("render_width", DefaultCFG.LIMIT_WIDTH),
        )

        # Appearance
        raw_appearance = raw_config.get("appearance", {})
        active_preset_name = raw_appearance.get("active_preset", "default")
        raw_presets_list = raw_appearance.get("presets", [])  # 解析 template_list 列表
        presets_dict = {}

        default_preset = ThemePreset(
            name="default", 
            font_order=["Sarasa Gothic SC", "Noto Color Emoji"],
            colors={} 
        )
        presets_dict["default"] = default_preset  # 兜底：默认预设

        if isinstance(raw_presets_list, list):
            for p_data in raw_presets_list:
                # 解析用户配置的列表
                p_name = p_data.get("preset_name", "custom")
                p_fonts = p_data.get("font_order", [])

                 # 解析颜色配置
                p_colors = {}
                for color_key in DefaultCFG.DEFAULT_COLORS.keys():
                    if color_key in p_data:
                        raw_val = p_data[color_key] # 防 None、数字类型传入
                        p_colors[color_key] = str(raw_val) if raw_val is not None else ""

                presets_dict[p_name] = ThemePreset(
                    name=p_name, 
                    font_order=p_fonts, 
                    colors=p_colors
                )

        # 提取激活预设的背景图
        bg_image = ""
        bg_opacity = 60.0
        bg_cache_enabled = True
        if isinstance(raw_presets_list, list):
            for p_data in raw_presets_list:
                if p_data.get("preset_name") == active_preset_name:
                    bg_image = p_data.get("background_image", "") or ""
                    raw_opacity = p_data.get("background_opacity")
                    if raw_opacity is not None:
                        bg_opacity = float(raw_opacity)
                    bg_cache_enabled = p_data.get("bg_cache_enabled", True)
                    if bg_cache_enabled is None:
                        bg_cache_enabled = True
                    break

        appearance_cfg = AppearanceConfig(
            active_preset=active_preset_name, 
            presets=presets_dict,
            background_image=bg_image,
            background_opacity=bg_opacity,
            bg_cache_enabled=bg_cache_enabled
        )

        custom_font_path = raw_config.get("custom_font_path", "")
        custom_template_path = raw_config.get("custom_template_path", "") or ""
        
        # Title settings
        raw_titles = raw_config.get("title_settings", {})
        menu_title = raw_titles.get("menu_title", "AstrBot 指令菜单") or "AstrBot 指令菜单"
        event_title = raw_titles.get("event_title", "AstrBot 事件监听") or "AstrBot 事件监听"
        filter_title = raw_titles.get("filter_title", "AstrBot 过滤器分析") or "AstrBot 过滤器分析"
        
        # Custom items
        custom_items: list[CustomItem] = []
        raw_custom_items = raw_config.get("custom_items", [])
        if isinstance(raw_custom_items, list):
            for ci_data in raw_custom_items:
                raw_entries = ci_data.get("entries", "")
                entries: list[CustomEntry] = []
                if isinstance(raw_entries, str) and raw_entries.strip():
                    for line in raw_entries.strip().split("\n"):
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split("|", 1)
                        name = parts[0].strip()
                        desc = parts[1].strip() if len(parts) > 1 else ""
                        if name:
                            entries.append(CustomEntry(name=name, desc=desc))
                
                custom_items.append(CustomItem(
                    section_title=ci_data.get("section_title", "自定义项目") or "自定义项目",
                    section_desc=ci_data.get("section_desc", "") or "",
                    entries=entries
                ))
        
        logger.debug(
            f"[HelpTypst] 配置加载完毕: PPI={render_cfg.ppi}, Concurrency={render_cfg.max_concurrent_tasks}, 外观预设: {active_preset_name}"
        )

        return cls(
            enable_waiting_message=enable_wait,
            ignored_plugins=ignored_set,
            custom_font_path=custom_font_path,
            custom_template_path=custom_template_path,
            custom_items=custom_items,
            menu_title=menu_title,
            event_title=event_title,
            filter_title=filter_title,
            rendering=render_cfg,
            appearance=appearance_cfg
        )