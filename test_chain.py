import chain
from brain import ProviderError


class Fake:
    def __init__(self, name, fail=False):
        self.name, self.fail, self.got = name, fail, []

    def reset(self): self.got = []
    def seed(self, u, r): self.got.append((u, r))

    def ask(self, text):
        if self.fail:
            raise ProviderError(self.name)
        return f"{self.name}:{text}"


def make(*ps):
    c = chain.ChainBrain.__new__(chain.ChainBrain)
    c.providers, c._cool_until, c.history = list(ps), [0.0] * len(ps), []
    return c


def test_falls_through_and_replays_history():
    a, b = Fake("a"), Fake("b")
    c = make(a, b)
    assert c.ask("one") == "a:one"
    a.fail = True
    assert c.ask("two") == "b:two"
    assert b.got == [("one", "a:one")]  # b was told what it missed


def test_all_down_message():
    c = make(Fake("a", True))
    assert "rate limited" in c.ask("x")


def test_schemas_build():
    import openai_brain, tools
    for f in tools.active_tools():
        s = openai_brain._schema(f)["function"]
        assert s["name"] and s["parameters"]["type"] == "object"
