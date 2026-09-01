"""An engine that starts nothing and remembers everything it was told.

Lets the context rules be tested exactly -- what each seat heard, in what
order, and what it was never given -- without a model, a process or a
subscription.
"""


class FakeAgent:
    provider = "fake"

    def __init__(self, engines, name, instructions):
        self.engines = engines
        self.name = name
        self.instructions = instructions
        self.heard = []             # every body of text delivered to this seat
        self.saw = []               # the image paths handed over, per turn
        self.turns = 0
        self.stopped = False
        self.accepts_images = name not in engines.blind

    def ask(self, text, timeout=None, images=()):
        self.heard.append(text)
        self.saw.append(list(images))
        self.turns += 1
        answer = self.engines.answers.get(
            (self.name, self.turns),
            self.engines.answers.get(self.name, "%s: ok" % self.name))
        if callable(answer):
            answer = answer(text)
        if isinstance(answer, Exception):
            return None, {"error": str(answer)}
        return answer, {"elapsed": 0.0, "tokens": 10 * self.turns}

    def status(self):
        return {"provider": self.provider, "model": "fake",
                "conversation": "fake", "activity": "", "turns": self.turns,
                "tokens": 10 * self.turns, "alive": not self.stopped,
                "pids": [], "shared_process": True}

    def stop(self):
        self.stopped = True


class FakeEngines:
    """Stands in for src.engines.Engines.

    `answers` maps a seat name -- or a (name, turn) pair -- to what it should
    reply. A callable receives the delivered text. `blind` names the seats
    whose engine cannot carry an image.
    """

    def __init__(self, answers=None, blind=()):
        self.answers = dict(answers or {})
        self.blind = set(blind)     # seat names whose engine cannot see
        self.agents = {}            # name -> the most recent agent
        self.history = []           # every agent ever made, stops included

    def agent(self, member, name, instructions):
        agent = FakeAgent(self, name, instructions)
        self.agents[name] = agent
        self.history.append(agent)
        return agent

    def models_for(self, engine):
        return ["fake/one", "fake/two"]

    def stop(self):
        for agent in self.history:
            agent.stop()

    def status(self):
        return []

    # ------------------------------------------------------------ reading
    def heard_by(self, name):
        return self.agents[name].heard if name in self.agents else []

    def seen_by(self, name):
        """Every image path handed to this seat, across all its turns."""
        return [p for turn in (self.agents[name].saw if name in self.agents
                               else []) for p in turn]

    def everything_heard_by(self, name):
        return "\n".join(self.heard_by(name))
