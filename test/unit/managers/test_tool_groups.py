"""Unit tests for tool group system: @tool(group=), ToolManager groups, LRU."""

import json
import pytest

from sdk.tool_registry import tool as sdk_tool, iter_registered_tools
from llm.tools.tool_manager import ToolManager


def _reset_tm():
    """Reset the ToolManager singleton for test isolation."""
    tm = ToolManager()
    tm._tools_definitions.clear()
    tm._functions.clear()
    tm._tool_groups.clear()
    tm._tool_risks.clear()
    return tm


class TestToolDecoratorGroup:
    def test_default_group_is_default(self):
        """@tool without group should get 'default'."""
        import llm.tools.tool_search  # ensures @tool decorator fires
        found = False
        for fn, nm, desc, grp, risk in iter_registered_tools():
            if (nm or fn.__name__) == "search_tools":
                assert grp == "default"
                found = True
        assert found, "search_tools should be registered with group=default"


class TestToolManagerGroups:
    def test_register_with_group(self):
        tm = _reset_tm()

        def my_func(x: int) -> int:
            """Test tool."""
            return x

        tm.register_function(my_func, name="my_tool", group="custom")
        assert tm.get_tool_group("my_tool") == "custom"

    def test_register_default_group(self):
        tm = _reset_tm()

        def my_func():
            return 1

        tm.register_function(my_func, name="default_tool")
        assert tm.get_tool_group("default_tool") == "default"

    def test_get_definitions_all(self):
        tm = _reset_tm()

        def foo():
            return 1
        def bar():
            return 2

        tm.register_function(foo, name="foo", group="a")
        tm.register_function(bar, name="bar", group="b")
        all_defs = tm.get_definitions()
        assert len(all_defs) == 2

    def test_get_definitions_filter_single_group(self):
        tm = _reset_tm()

        def foo():
            return 1
        def bar():
            return 2

        tm.register_function(foo, name="foo", group="alpha")
        tm.register_function(bar, name="bar", group="beta")
        defs = tm.get_definitions(groups="alpha")
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "foo"

    def test_get_definitions_filter_multiple_groups(self):
        tm = _reset_tm()

        def a():
            return 1
        def b():
            return 2
        def c():
            return 3

        tm.register_function(a, name="a", group="g1")
        tm.register_function(b, name="b", group="g2")
        tm.register_function(c, name="c", group="g3")
        defs = tm.get_definitions(groups=["g1", "g3"])
        assert len(defs) == 2
        names = {d["function"]["name"] for d in defs}
        assert names == {"a", "c"}

    def test_get_groups(self):
        tm = _reset_tm()

        def a():
            return 1
        def b():
            return 2

        tm.register_function(a, name="a", group="char")
        tm.register_function(b, name="b", group="mem")
        groups = tm.get_groups()
        assert "char" in groups
        assert "mem" in groups

    def test_get_tool_group(self):
        tm = _reset_tm()

        def x():
            return 1

        tm.register_function(x, name="x", group="testing")
        assert tm.get_tool_group("x") == "testing"
        assert tm.get_tool_group("nonexistent") == "default"

    def test_drop_tool_clears_group(self):
        tm = _reset_tm()

        def x():
            return 1

        tm.register_function(x, name="x", group="tmp")
        assert tm.get_tool_group("x") == "tmp"
        tm._drop_tool("x")
        assert tm.get_tool_group("x") == "default"

    def test_reregister_updates_group(self):
        tm = _reset_tm()

        def x():
            return 1
        def y():
            return 2

        tm.register_function(x, name="same", group="first")
        tm.register_function(y, name="same", group="second")
        assert tm.get_tool_group("same") == "second"


class TestSearchTools:
    def test_search_by_group_name(self):
        tm = _reset_tm()

        def mem_fn():
            """A memory tool."""
            return 1

        tm.register_function(mem_fn, name="mem_search", group="memory",
                             description="Search character memories")
        results = tm.search_tools("memory")
        assert len(results) >= 1
        assert any(r["name"] == "mem_search" for r in results)
        assert all("risk" in r for r in results)

    def test_search_by_description(self):
        tm = _reset_tm()

        def char_fn():
            """Get information about a character."""
            return 1

        tm.register_function(char_fn, name="char_info", group="character")
        results = tm.search_tools("character")
        assert len(results) >= 1
        assert results[0]["group"] == "character"

    def test_search_empty_keyword(self):
        tm = _reset_tm()

        def fn():
            return 1

        tm.register_function(fn, name="test", group="default")
        results = tm.search_tools("")
        assert results == []

    def test_search_no_match(self):
        tm = _reset_tm()

        def fn():
            return 1

        tm.register_function(fn, name="x", group="a")
        results = tm.search_tools("zzzz_nonexistent")
        assert results == []


class TestMCPToolsGroup:
    def test_register_mcp_with_custom_group(self):
        tm = _reset_tm()

        def mock_invoke(name: str, args: dict):
            return {"ok": True}

        mcp_tools = [
            {"name": "weather", "description": "Get weather", "inputSchema": {"type": "object", "properties": {}}}
        ]
        tm.register_mcp_tools(mcp_tools, invoke=mock_invoke, group="weather-mcp")
        assert tm.get_tool_group("weather") == "weather-mcp"

    def test_register_mcp_default_group(self):
        tm = _reset_tm()

        def mock_invoke(name: str, args: dict):
            return {"ok": True}

        mcp_tools = [
            {"name": "generic", "description": "Generic tool", "inputSchema": {"type": "object", "properties": {}}}
        ]
        tm.register_mcp_tools(mcp_tools, invoke=mock_invoke)
        assert tm.get_tool_group("generic") == "mcp"
        assert tm.get_tool_risk("generic") == "medium"

    def test_register_mcp_with_prefix(self):
        tm = _reset_tm()

        def mock_invoke(name: str, args: dict):
            return {"ok": True}

        mcp_tools = [
            {"name": "search", "description": "Search", "inputSchema": {"type": "object", "properties": {}}}
        ]
        tm.register_mcp_tools(mcp_tools, invoke=mock_invoke, name_prefix="mcp_", group="custom-grp")
        assert tm.get_tool_group("mcp_search") == "custom-grp"


class TestLRUGroupManagement:
    def test_initial_groups(self):
        """LLMManager starts with only default group."""
        from llm.llm_manager import LLMManager
        from test.mocks import MockLLMAdapter

        adapter = MockLLMAdapter(responses=[""])
        mgr = LLMManager(adapter=adapter, max_tokens=128000)
        assert mgr._active_tool_groups == ["default"]
        assert hasattr(mgr, "_max_active_groups")
        assert mgr._max_active_groups == 5

    def test_search_tools_expands_groups(self):
        """Simulate what happens when search_tools is called in chat."""
        from llm.llm_manager import LLMManager
        from test.mocks import MockLLMAdapter

        adapter = MockLLMAdapter(responses=[""])
        mgr = LLMManager(adapter=adapter, max_tokens=128000)

        # Simulate search_tools being called with keyword="memory"
        # The tool execution handler would do this group expansion
        _reset_tm()
        # Register some tools with groups so search has something to find
        tm = ToolManager()
        def mem_fn():
            return 1
        tm.register_function(mem_fn, name="mem", group="memory")

        # Simulate the expansion logic
        kw = "memory"
        for g in tm.get_groups():
            if g not in mgr._active_tool_groups and kw in g.lower():
                mgr._active_tool_groups.insert(0, g)
                if len(mgr._active_tool_groups) > mgr._max_active_groups:
                    mgr._active_tool_groups.pop()

        assert "memory" in mgr._active_tool_groups
        assert mgr._active_tool_groups[0] == "memory"  # inserted at front

    def test_lru_promotes_existing_group(self):
        """Searching an already-active group moves it to front."""
        adapter = __import__('test.mocks', fromlist=['MockLLMAdapter']).MockLLMAdapter
        from llm.llm_manager import LLMManager

        adapter = adapter(responses=[""])
        mgr = LLMManager(adapter=adapter, max_tokens=128000)

        mgr._active_tool_groups = ["memory", "character", "default"]
        # Search "character" again — should move to front
        kw = "character"
        tm = _reset_tm()
        for g in ["memory", "character", "default"]:
            tm.register_function(lambda: 1, name=f"fn_{g}", group=g)

        for g in tm.get_groups():
            if kw in g.lower():
                if g in mgr._active_tool_groups:
                    mgr._active_tool_groups.remove(g)
                mgr._active_tool_groups.insert(0, g)

        assert mgr._active_tool_groups[0] == "character"
        assert "character" in mgr._active_tool_groups
        assert len(mgr._active_tool_groups) == 3  # no duplicate

    def test_lru_evicts_when_full(self):
        """When max groups exceeded, oldest is evicted (truncate)."""
        from llm.llm_manager import LLMManager
        from test.mocks import MockLLMAdapter

        adapter = MockLLMAdapter(responses=[""])
        mgr = LLMManager(adapter=adapter, max_tokens=128000)
        mgr._max_active_groups = 3
        mgr._active_tool_groups = ["mem", "char", "default"]  # at limit

        _reset_tm()
        tm = ToolManager()
        for g in ["default", "char", "mem", "new_group"]:
            tm.register_function(lambda: 1, name=f"fn_{g}", group=g)

        # Simulate search for new_group — should evict default (oldest)
        kw = "new_group"
        for g in tm.get_groups():
            if kw in g.lower():
                if g in mgr._active_tool_groups:
                    mgr._active_tool_groups.remove(g)
                mgr._active_tool_groups.insert(0, g)
                if len(mgr._active_tool_groups) > mgr._max_active_groups:
                    mgr._active_tool_groups = mgr._active_tool_groups[:mgr._max_active_groups]

        assert "new_group" in mgr._active_tool_groups
        assert len(mgr._active_tool_groups) == 3

    def test_tool_manager_execute_returns_grouped(self):
        tm = _reset_tm()

        def my_tool(x: int) -> int:
            """Multiply input."""
            return x * 2

        tm.register_function(my_tool, name="multiply", group="math")
        result = tm.execute("multiply", '{"x": 5}')
        assert "10" in result

        defs = tm.get_definitions(groups="math")
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "multiply"
