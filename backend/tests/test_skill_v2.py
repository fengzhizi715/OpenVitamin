"""
Skill v2 单元测试。

测试要求：
- 注册两个版本 skill
- 默认返回 latest
- 可以指定 version
- 执行返回统一 Response
- 非法输入触发 schema 校验错误
"""
import pytest
from datetime import datetime
from core.skills.models import SkillDefinition, Skill
from core.skills.registry import SkillRegistry
from core.skills.contract import SkillExecutionRequest, SkillExecutionResponse
from core.skills.executor import SkillExecutor


class TestSkillDefinition:
    """测试 SkillDefinition 模型"""
    
    def test_create_valid_definition(self):
        """创建有效的 Skill 定义"""
        definition = SkillDefinition(
            id="test.skill",
            name="Test Skill",
            version="1.0.0",
            description="Test description",
            input_schema={"type": "object"},
            output_schema={"type": "object"}
        )
        
        assert definition.id == "test.skill"
        assert definition.version == "1.0.0"
        assert definition.enabled is True
        assert definition.composable is True
        assert definition.visibility == "public"
    
    def test_version_required(self):
        """version 必填"""
        with pytest.raises(ValueError) as exc_info:
            SkillDefinition(
                id="test.skill",
                name="Test",
                version="",  # 空字符串
                description="Test",
                input_schema={"type": "object"},
                output_schema={"type": "object"}
            )
        assert "version is required" in str(exc_info.value)
    
    def test_input_schema_required(self):
        """input_schema 必填"""
        with pytest.raises(ValueError) as exc_info:
            SkillDefinition(
                id="test.skill",
                name="Test",
                version="1.0.0",
                description="Test",
                input_schema={},  # 空
                output_schema={"type": "object"}
            )
        assert "input_schema is required" in str(exc_info.value)
    
    def test_output_schema_required(self):
        """output_schema 必填"""
        with pytest.raises(ValueError) as exc_info:
            SkillDefinition(
                id="test.skill",
                name="Test",
                version="1.0.0",
                description="Test",
                input_schema={"type": "object"},
                output_schema={}  # 空
            )
        assert "output_schema is required" in str(exc_info.value)
    
    def test_to_dict(self):
        """转换为字典"""
        definition = SkillDefinition(
            id="test.skill",
            name="Test Skill",
            version="1.0.0",
            description="Test",
            category=["test"],
            tags=["tag1", "tag2"],
            input_schema={"type": "object"},
            output_schema={"type": "object"}
        )
        
        data = definition.to_dict()
        assert data["id"] == "test.skill"
        assert data["version"] == "1.0.0"
        assert data["category"] == ["test"]
        assert data["tags"] == ["tag1", "tag2"]


class TestSkillRegistry:
    """测试 SkillRegistry 多版本管理"""
    
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """每个测试前后清空注册表"""
        SkillRegistry.clear()
        yield
    
    def test_register_multiple_versions(self):
        """注册多个版本"""
        v1 = SkillDefinition(
            id="test.skill",
            name="Test Skill",
            version="1.0.0",
            description="Version 1",
            input_schema={"type": "object"},
            output_schema={"type": "object"}
        )
        
        v2 = SkillDefinition(
            id="test.skill",
            name="Test Skill",
            version="1.1.0",
            description="Version 2",
            input_schema={"type": "object"},
            output_schema={"type": "object"}
        )
        
        SkillRegistry.register(v1)
        SkillRegistry.register(v2)
        
        # 验证版本列表
        versions = SkillRegistry.list_versions("test.skill")
        assert len(versions) == 2
        assert "1.0.0" in versions
        assert "1.1.0" in versions
    
    def test_get_latest_version(self):
        """默认返回最新版本"""
        v1 = SkillDefinition(
            id="test.skill",
            name="Test Skill",
            version="1.0.0",
            description="Version 1",
            input_schema={"type": "object"},
            output_schema={"type": "object"}
        )
        
        v2 = SkillDefinition(
            id="test.skill",
            name="Test Skill",
            version="1.1.0",
            description="Version 2",
            input_schema={"type": "object"},
            output_schema={"type": "object"}
        )
        
        SkillRegistry.register(v1)
        SkillRegistry.register(v2)
        
        # 不指定版本，返回最新
        latest = SkillRegistry.get("test.skill")
        assert latest is not None
        assert latest.version == "1.1.0"
    
    def test_get_specific_version(self):
        """指定版本获取"""
        v1 = SkillDefinition(
            id="test.skill",
            name="Test Skill",
            version="1.0.0",
            description="Version 1",
            input_schema={"type": "object"},
            output_schema={"type": "object"}
        )
        
        v2 = SkillDefinition(
            id="test.skill",
            name="Test Skill",
            version="2.0.0",
            description="Version 2",
            input_schema={"type": "object"},
            output_schema={"type": "object"}
        )
        
        SkillRegistry.register(v1)
        SkillRegistry.register(v2)
        
        # 指定旧版本
        old = SkillRegistry.get("test.skill", version="1.0.0")
        assert old is not None
        assert old.version == "1.0.0"
        assert old.description == "Version 1"
    
    def test_deprecate_version(self):
        """废弃版本"""
        v1 = SkillDefinition(
            id="test.skill",
            name="Test Skill",
            version="1.0.0",
            description="Version 1",
            input_schema={"type": "object"},
            output_schema={"type": "object"}
        )
        
        v2 = SkillDefinition(
            id="test.skill",
            name="Test Skill",
            version="1.1.0",
            description="Version 2",
            input_schema={"type": "object"},
            output_schema={"type": "object"}
        )
        
        SkillRegistry.register(v1)
        SkillRegistry.register(v2)
        
        # 废弃旧版本
        result = SkillRegistry.deprecate("test.skill", "1.0.0")
        assert result is True
        
        # 验证已废弃
        v1_check = SkillRegistry.get("test.skill", version="1.0.0")
        assert v1_check.enabled is False
        
        # 验证最新版本仍然可用
        latest = SkillRegistry.get("test.skill")
        assert latest.version == "1.1.0"
        assert latest.enabled is True
    
    def test_cannot_deprecate_last_active_version(self):
        """不能废弃最后一个活跃版本"""
        v1 = SkillDefinition(
            id="test.skill",
            name="Test Skill",
            version="1.0.0",
            description="Version 1",
            input_schema={"type": "object"},
            output_schema={"type": "object"}
        )
        
        SkillRegistry.register(v1)
        
        # 尝试废弃唯一版本
        result = SkillRegistry.deprecate("test.skill", "1.0.0")
        assert result is False


class TestSkillExecutor:
    """测试 SkillExecutor 统一执行"""
    
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """每个测试前后清空注册表"""
        SkillRegistry.clear()
        yield
    
    @pytest.mark.asyncio
    async def test_execute_success(self):
        """成功执行"""
        # 注册 Skill
        definition = SkillDefinition(
            id="test.skill",
            name="Test Skill",
            version="1.0.0",
            description="Test",
            input_schema={"type": "object"},
            output_schema={"type": "object"}
        )
        SkillRegistry.register(definition)
        
        # 执行
        request = SkillExecutionRequest(
            skill_id="test.skill",
            input={"key": "value"},
            trace_id="trace_123",
            caller_id="user_456"
        )
        
        response = await SkillExecutor.execute(request)
        
        assert response.status == "success"
        assert response.trace_id == "trace_123"
        assert response.skill_id == "test.skill"
        assert response.version == "1.0.0"
        assert "latency_ms" in response.metrics
    
    @pytest.mark.asyncio
    async def test_execute_not_found(self):
        """Skill 未找到"""
        request = SkillExecutionRequest(
            skill_id="nonexistent.skill",
            input={"test": "data"},  # 需要非空 input
            trace_id="trace_123"
        )
        
        response = await SkillExecutor.execute(request)
        
        assert response.status == "error"
        assert response.error["code"] == "SKILL_NOT_FOUND"
    
    @pytest.mark.asyncio
    async def test_execute_invalid_request(self):
        """非法请求"""
        request = SkillExecutionRequest(
            skill_id="",  # 空
            input={}
        )
        
        response = await SkillExecutor.execute(request)
        
        assert response.status == "error"
        assert response.error["code"] == "INVALID_REQUEST"
    
    @pytest.mark.asyncio
    async def test_execute_with_version(self):
        """指定版本执行"""
        v1 = SkillDefinition(
            id="test.skill",
            name="Test Skill",
            version="1.0.0",
            description="Version 1",
            input_schema={"type": "object"},
            output_schema={"type": "object"}
        )
        
        v2 = SkillDefinition(
            id="test.skill",
            name="Test Skill",
            version="2.0.0",
            description="Version 2",
            input_schema={"type": "object"},
            output_schema={"type": "object"}
        )
        
        SkillRegistry.register(v1)
        SkillRegistry.register(v2)
        
        # 指定旧版本
        request = SkillExecutionRequest(
            skill_id="test.skill",
            input={"test": "data"},  # 需要非空 input
            version="1.0.0",
            trace_id="trace_123"
        )
        
        response = await SkillExecutor.execute(request)
        
        assert response.status == "success"
        assert response.version == "1.0.0"


class TestSchemaValidation:
    """测试 Schema 校验"""
    
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        SkillRegistry.clear()
        yield
    
    @pytest.mark.asyncio
    async def test_validate_required_fields(self):
        """校验必填字段"""
        definition = SkillDefinition(
            id="test.skill",
            name="Test Skill",
            version="1.0.0",
            description="Test",
            input_schema={
                "type": "object",
                "required": ["name", "age"]
            },
            output_schema={"type": "object"}
        )
        SkillRegistry.register(definition)
        
        # 缺少必填字段
        request = SkillExecutionRequest(
            skill_id="test.skill",
            input={"name": "Alice"},  # 缺少 age
            trace_id="trace_123"
        )
        
        response = await SkillExecutor.execute(request)
        
        assert response.status == "error"
        assert response.error["code"] == "SCHEMA_VALIDATION_ERROR"
        assert "age" in response.error["message"]
        assert "required" in response.error["message"].lower()


class TestV1Compatibility:
    """测试 v1 兼容性"""
    
    def test_v1_to_v2_conversion(self):
        """v1 转 v2"""
        from core.skills.models import Skill
        
        v1_skill = Skill(
            id="legacy.skill",
            name="Legacy Skill",
            description="Old skill",
            category="test",
            type="tool",
            definition={"tool_name": "test_tool"},
            input_schema={"type": "object"},
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        # 转换
        v2_def = v1_skill.to_v2()
        
        assert v2_def.id == "legacy.skill"
        assert v2_def.name == "Legacy Skill"
        assert v2_def.version == "1.0.0"  # 默认版本
        assert v2_def.category == ["test"]  # 转为列表
        assert v2_def.enabled is True
        assert v2_def.composable is True
        assert v2_def.visibility == "public"
    
    def test_backward_compatibility_api(self):
        """向后兼容 API"""
        from core.skills.executor import get_skill
        
        v1_skill = Skill(
            id="legacy.skill",
            name="Legacy Skill",
            description="Old skill",
            category="test",
            type="tool",
            definition={"tool_name": "test_tool"},
            input_schema={"type": "object"},
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        # 注册 v1
        SkillRegistry.register(v1_skill.to_v2())
        
        # 使用旧 API 获取
        skill = get_skill("legacy.skill")
        assert skill is not None
        assert skill.version == "1.0.0"
