from src.retrieve import orchestrator


def test_load_config_returns_dict_from_real_file():
    config = orchestrator.load_config()

    assert "retrieval_order" in config
    assert config["matching"]["threshold"] == 0.80


def test_load_config_reads_given_path(tmp_path):
    config_path = tmp_path / "fake_sources.yaml"
    config_path.write_text("matching:\n  threshold: 0.5\n", encoding="utf-8")

    config = orchestrator.load_config(path=config_path)

    assert config == {"matching": {"threshold": 0.5}}


class _FakeAdapter:
    def __init__(self, index):
        self._index = index
        self.build_index_calls = 0

    def build_index(self):
        self.build_index_calls += 1
        return self._index

    def match(self, course_name, index):
        raise NotImplementedError

    def download(self, match, tier):
        raise NotImplementedError


def test_build_indices_calls_build_index_once_per_adapter():
    adapter_a = _FakeAdapter(index={"a": "url-a"})
    adapter_b = _FakeAdapter(index={"b": "url-b"})

    indices = orchestrator.build_indices([adapter_a, adapter_b])

    assert indices == {adapter_a: {"a": "url-a"}, adapter_b: {"b": "url-b"}}
    assert adapter_a.build_index_calls == 1
    assert adapter_b.build_index_calls == 1
