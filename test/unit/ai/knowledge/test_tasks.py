from ai.knowledge import tasks

def test_knowledge_tasks_are_independent_and_return_snapshots(monkeypatch):
    from ai.memory import tasks as memory_tasks
    monkeypatch.setattr(memory_tasks, "_mem0_task", None)
    memory_tasks.set_mem0_task(progress=0.25)
    before = memory_tasks.current_mem0_task()
    tasks.set_mem0_task(progress=0.5)
    snapshot = tasks.current_mem0_task()
    assert snapshot["id"] != before["id"]
    assert snapshot["createdAt"] <= snapshot["updatedAt"]
    snapshot["progress"] = 1
    assert tasks.current_mem0_task()["progress"] == 0.5
    assert memory_tasks.current_mem0_task() == before
