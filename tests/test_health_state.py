from backend_health.health_state import PipelineHealthState


def test_record_increments_streak_on_failure():
    state = PipelineHealthState()
    state.record("tenant-a", ok=False, error="e1")
    health = state.record("tenant-a", ok=False, error="e2")
    assert health.consecutive_failures == 2
    assert health.last_status == "failed"
    assert health.last_error == "e2"


def test_record_resets_streak_on_success():
    state = PipelineHealthState()
    state.record("tenant-a", ok=False, error="e1")
    state.record("tenant-a", ok=False, error="e2")
    health = state.record("tenant-a", ok=True)
    assert health.consecutive_failures == 0
    assert health.last_status == "ok"
    assert health.last_error is None


def test_get_unknown_tenant_returns_none():
    assert PipelineHealthState().get("nope") is None


def test_all_lists_sorted_by_tenant_id():
    state = PipelineHealthState()
    state.record("tenant-b", ok=True)
    state.record("tenant-a", ok=False, error="x")
    assert [h.tenant_id for h in state.all()] == ["tenant-a", "tenant-b"]


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "health.json"
    state = PipelineHealthState()
    state.record("tenant-a", ok=False, error="boom")
    state.save(path)

    loaded = PipelineHealthState.load(path)
    health = loaded.get("tenant-a")
    assert health.consecutive_failures == 1
    assert health.last_error == "boom"


def test_load_missing_file_returns_empty_state(tmp_path):
    state = PipelineHealthState.load(tmp_path / "does-not-exist.json")
    assert state.all() == []


def test_load_corrupt_file_returns_empty_state_not_raise(tmp_path):
    path = tmp_path / "health.json"
    path.write_text("{not valid json")
    state = PipelineHealthState.load(path)
    assert state.all() == []


def test_load_wrong_shape_file_returns_empty_state_not_raise(tmp_path):
    path = tmp_path / "health.json"
    path.write_text("[1, 2, 3]")  # valid JSON, but not the expected {tenant: entry} mapping
    state = PipelineHealthState.load(path)
    assert state.all() == []


def test_malformed_per_tenant_entry_does_not_crash_record_or_get():
    state = PipelineHealthState({"tenant-a": "not-a-dict"})
    # record() must not crash reading the malformed prior entry
    health = state.record("tenant-a", ok=False, error="e")
    assert health.consecutive_failures == 1

    state2 = PipelineHealthState({"tenant-b": ["also", "not", "a", "dict"]})
    health2 = state2.get("tenant-b")
    assert health2.consecutive_failures == 0
    assert health2.last_status == "unknown"
