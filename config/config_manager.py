import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from pydantic import ValidationError
from config.schema import AppConfig, Character, ApiConfig, SystemConfig, Background
from llm.constants import LLM_BASE_URLS
import traceback

class ConfigManager:
    """
    配置管理器：负责加载、保存和管理应用的全局配置。
    使用单例模式确保全局只有一个配置实例。
    """
    _instance: Optional['ConfigManager'] = None
    _config: Optional[AppConfig] = None
    
    # 配置文件路径定义
    _API_CONFIG_PATH = Path("data/config/api.yaml")
    _CHARACTERS_CONFIG_PATH = Path("data/config/characters.yaml")
    _SYSTEM_CONFIG_PATH = Path("data/config/system_config.yaml")
    _BACKGOUND_CONFIG_PATH = Path("data/config/background.yaml")

    def __new__(cls, *args, **kwargs):
        """实现单例模式"""
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            # 在首次创建时尝试加载配置
            cls._instance._load_all_configs()
        return cls._instance

    @property
    def config(self) -> AppConfig:
        """提供对 Pydantic AppConfig 实例的访问"""
        if self._config is None:
            # 如果配置尚未加载，尝试重新加载或抛出错误
            self._load_all_configs()
            if self._config is None:
                 raise RuntimeError("配置加载失败，无法访问配置数据。")
        return self._config

    # --- 内部加载/合并逻辑 ---
    def _load_yaml(self, file_path: Path) -> Dict[str, Any]:
        """加载单个 YAML 文件"""
        if not file_path.exists():
            print(f"警告：配置文件未找到：{file_path}")
            return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            raise IOError(f"加载配置文件 {file_path} 失败: {e}")

    def _load_all_configs(self) -> None:
        """加载所有配置并合并到一个结构中"""
        try:
            # 加载单个配置文件
            api_data = self._load_yaml(self._API_CONFIG_PATH)
            characters_data = self._load_yaml(self._CHARACTERS_CONFIG_PATH)
            system_data = self._load_yaml(self._SYSTEM_CONFIG_PATH)
            background_data = self._load_yaml(self._BACKGOUND_CONFIG_PATH)

            # 通过 Pydantic 进行验证和结构化
            api_config = ApiConfig.model_validate(api_data)
            system_config = SystemConfig.model_validate(system_data)

            # 对于 characters.yaml，它是一个列表，直接传递给 List[Character]
            if not isinstance(characters_data, list):
                characters_data = [] # 处理文件为空或格式错误的情况
                
            character_list = [Character.model_validate(item) for item in characters_data]
            background = [Background.model_validate(item) for item in background_data]

            # 构建顶层 AppConfig 实体
            self._config = AppConfig(
                api_config=api_config,
                system_config=system_config,
                characters=character_list,
                background_list=background
            )
            print("配置加载成功！")
        except ValidationError as e:
            self._config = None
            traceback.print_exc()
            raise ValidationError(f"配置验证失败，请检查配置文件格式: \n{e}")
        except Exception as e:
            self._config = None
            raise Exception(f"初始化配置管理器时发生错误: {e}")
            
    # --- 公共方法 ---

    def reload(self) -> None:
        """重新加载所有配置文件"""
        self._load_all_configs()
        
    def save_api_config(self) -> None:
        """独立保存 API 配置到 api.yaml"""
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存 API 配置。")
            return
        
        print("正在保存 api.yaml...")
        # 将 Pydantic 实体转换为字典进行保存
        self._save_single_config(
            self._API_CONFIG_PATH, 
            self.config.api_config.model_dump(by_alias=True)
        )
        print("api.yaml 保存完成。")

    def save_system_config(self) -> None:
        """独立保存系统配置到 system_config.yaml"""
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存系统配置。")
            return
            
        print("正在保存 system_config.yaml...")
        self._save_single_config(
            self._SYSTEM_CONFIG_PATH, 
            self.config.system_config.model_dump(by_alias=True)
        )
        print("system_config.yaml 保存完成。")
    
    def save_api_config_new(self, llm_provider: str, llm_model: str, api_key: str, base_url: str, sovits_url: str, gpt_sovits_api_path: str, t2i_url, t2i_work_path, t2i_workflow_path,prompt_node_id, output_node_id) -> str:
        """
        更新内存中的 ApiConfig，并将其保存到 api.yaml。
        """
        if self._config is None:
            return "错误：配置未加载或加载失败，无法保存 API 配置。"

        print("正在更新并保存 api.yaml...")
        current_api_config = self.config.api_config.model_copy(deep=True)
        current_api_config.llm_api_key[llm_provider] = api_key
        current_api_config.llm_model[llm_provider] = llm_model

        current_api_config.llm_provider = llm_provider
        current_api_config.llm_base_url = base_url
        current_api_config.gpt_sovits_url = sovits_url
        current_api_config.gpt_sovits_api_path = gpt_sovits_api_path
        current_api_config.t2i_api_url=t2i_url
        current_api_config.t2i_work_path=t2i_work_path
        current_api_config.t2i_default_workflow_path=t2i_workflow_path
        current_api_config.t2i_prompt_node_id=prompt_node_id
        current_api_config.t2i_output_node_id=output_node_id
        self.config.api_config = current_api_config

        
        # 6. 持久化到文件
        self._save_single_config(
            self._API_CONFIG_PATH, 
            self.config.api_config.model_dump(by_alias=True)
        )
        return "API配置已保存！"

    def update_llm_info(self, llm_provider: str) -> tuple[str, str, str]:
        """
        根据给定的 LLM 提供商名称，从配置中获取对应的 Base URL, 模型名称和 API Key。
        
        返回: (base_url, llm_model, api_key)
        """
        if self._config is None:
            raise RuntimeError("配置未加载，无法获取 LLM 信息。")

        api_config = self.config.api_config
        
        base_url = LLM_BASE_URLS.get(llm_provider,"")
        
        # 从字典中获取对应提供商的模型和 API Key
        llm_model = api_config.llm_model.get(llm_provider, "")
        api_key = api_config.llm_api_key.get(llm_provider, "")

        # 返回 Base URL, 模型名称, API Key
        return base_url, llm_model, api_key

    def save_characters_config(self) -> None:
        """独立保存角色列表配置到 characters.yaml"""
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存角色配置。")
            return
            
        print("正在保存 characters.yaml...")
        # 角色列表需要将每个 Character 实体转换为字典
        characters_data = [char.model_dump(by_alias=True) for char in self.config.characters]
        self._save_single_config(self._CHARACTERS_CONFIG_PATH, characters_data)
        print("characters.yaml 保存完成。")
    
    def save_background_config(self) -> None:
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存角色配置。")
            return
            
        print("正在保存 background.yaml...")
        # 角色列表需要将每个 Character 实体转换为字典
        background_data = [char.model_dump(by_alias=True) for char in self.config.background_list]
        self._save_single_config(self._BACKGOUND_CONFIG_PATH, background_data)
        print("background.yaml 保存完成。")

    def _save_single_config(self, file_path: Path, data: Union[Dict, List]) -> None:
        """保存单个配置到 YAML 文件"""
        file_path.parent.mkdir(parents=True, exist_ok=True) # 确保目录存在
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                # 使用 default_flow_style=False 提高 YAML 的可读性
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except Exception as e:
            print(f"错误：保存配置到 {file_path} 失败: {e}")

    def get_background_by_name(self, name: str) -> Optional[Background]:
        for char in self.config.background_list:
            if char.name.lower() == name.lower():
                return char
        return None

    def get_character_by_name(self, name: str) -> Optional[Character]:
        """根据角色名称获取角色配置实体"""
        for char in self.config.characters:
            if char.name.lower() == name.lower():
                return char
        return None

    def get_llm_api_config(self):
        llm_provider = self.config.api_config.llm_provider
        api_key = self.config.api_config.llm_api_key.get(llm_provider,"")
        model = self.config.api_config.llm_model.get(llm_provider,"")
        base_url = self.config.api_config.llm_base_url
        return llm_provider, model, base_url, api_key

    def get_gpt_sovits_config(self):
        return self.config.api_config.gpt_sovits_url, self.config.api_config.gpt_sovits_api_path

    def get_base_font_size(self) -> int:
        """获取基础字体大小"""
        return self.config.system_config.base_font_size_px